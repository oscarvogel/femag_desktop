"""Importación de la lista de precios y del teléfono desde el Excel que exporta la app.

Contexto (#705): Gabriela prepara un Excel con la lista de precios de cada cliente y,
a medias, con el teléfono de algunos. Hay que traer eso a la base **sin pisar** lo que
el operador editó a mano.

Las reglas son las mismas del modo ``patch`` del importador del legacy (#746/#747):

- Se escribe **solo** ``lista_precios`` y, **únicamente si el cliente no tiene
  teléfono**, se completa ``phone``. Ningún otro campo se toca.
- **Nunca** se pisa un dato existente: si la base ya tiene teléfono se respeta, y si el
  archivo trae un teléfono distinto se reporta en vez de aplicarse.
- **Nunca** se crean clientes ni se borran.
- El matcheo es por **CUIT normalizado** (solo dígitos) porque en la base el CUIT
  viene con separadores (``20- 29646152-1``) y el índice único es sobre el texto. Si
  el CUIT no sirve, se matchea por **nombre normalizado** y solo si da un único
  cliente.
- Si el CUIT matchea **varias filas del mismo cliente** (mismo nombre normalizado,
  CUIT guardado en dos formatos), la lista del archivo se aplica a **todas** sus
  filas: el mismo cliente no puede tener dos listas de precios. Se avisa que
  conviene unificarlas, pero no se borra ninguna (#761).
- Si el CUIT matchea filas de **nombres distintos**, no se aplica nada: son
  clientes distintos y es un error de datos que hay que corregir a mano.
- Siempre hay una **vista previa que no escribe nada**: nada se toca hasta que el
  operador la mira y la confirma.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook

from app.models.masters import Client
from app.services.audit_service import AuditService

VALID_LISTAS = (1, 2, 3, 4)

COLUMN_CUIT = "cuit"
COLUMN_LISTA = "lista"
COLUMN_TELEFONO = "telefono"
COLUMN_NOMBRE = "nombre"
COLUMN_IVA = "iva"
COLUMN_EMAIL = "email"
COLUMN_CONTACTO = "contacto"

#: Encabezados aceptados, ya normalizados (minúsculas, sin acentos, sin doble espacio).
ENCABEZADOS_ACEPTADOS = {
    COLUMN_CUIT: {"cuit"},
    COLUMN_LISTA: {"lista", "lista de precios", "lista precios"},
    COLUMN_TELEFONO: {"celular / telefono", "celular", "telefono", "telefono / celular"},
    COLUMN_NOMBRE: {"nombre / razon social", "nombre", "razon social"},
    COLUMN_IVA: {"cond. iva", "condicion iva", "iva"},
    COLUMN_EMAIL: {"email", "correo", "correo electronico"},
    COLUMN_CONTACTO: {"contacto"},
}


class ImportPriceListError(RuntimeError):
    """Error de la importación, con un mensaje que se puede mostrar en pantalla."""


def normalizar_texto(valor) -> str:
    """Minúsculas, sin acentos y sin doble espacio, para comparar textos."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.strip().lower())


def normalizar_cuit(valor) -> str:
    """Devuelve el CUIT solo con dígitos, o vacío si no hay uno usable.

    El legacy completaba el CUIT con ceros y guiones cuando el cliente no lo tenía
    (``'00-00000000-0'``), y esos rellenos los comparten varias filas. Mismo criterio
    que ``LegacyDbfImporter._clean_cuit``.
    """
    digitos = re.sub(r"\D", "", str(valor or ""))
    if not digitos or set(digitos) == {"0"}:
        return ""
    return digitos


def normalizar_nombre(valor) -> str:
    """Nombre comparable: sin acentos, en mayúsculas y solo con espacios y letras."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", texto.upper()).strip()


def solo_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _parse_lista(valor) -> int | None:
    """Devuelve la lista 1..4 del archivo, o ``None`` si no es válida."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        entero = int(valor)
        return entero if entero in VALID_LISTAS else None
    texto = str(valor).strip()
    if not texto:
        return None
    if not re.fullmatch(r"\d+(\.0+)?", texto):
        return None
    entero = int(float(texto))
    return entero if entero in VALID_LISTAS else None


@dataclass(frozen=True)
class FilaArchivo:
    """Una fila del Excel, ya normalizada para comparar."""

    numero: int
    nombre: str
    cuit: str
    cuit_normalizado: str
    lista: int | None
    lista_texto: str
    telefono: str
    iva: str
    email: str
    contacto: str


@dataclass
class Cambio:
    """Un cambio a aplicar sobre un cliente."""

    client_id: int
    nombre: str
    cuit: str
    motivo: str
    lista_anterior: int
    lista_nueva: int
    telefono_anterior: str
    telefono_nuevo: str
    fila: int

    @property
    def cambia_lista(self) -> bool:
        return self.lista_anterior != self.lista_nueva

    @property
    def completa_telefono(self) -> bool:
        return not self.telefono_anterior and bool(self.telefono_nuevo)


@dataclass
class Conflicto:
    """Algo que no se puede aplicar sin que un humano lo resuelva."""

    tipo: str
    detalle: str
    cuit: str = ""
    filas: tuple[int, ...] = ()
    nombres: tuple[str, ...] = ()


@dataclass
class FilaReportada:
    """Una fila del archivo que no se pudo aplicar, con el motivo."""

    fila: int
    nombre: str
    cuit: str
    motivo: str
    detalle: str = ""


@dataclass
class DiferenciaReportada:
    """Una diferencia entre el archivo y la base que no se aplica, pero se informa."""

    fila: int
    nombre: str
    cuit: str
    campo: str
    valor_base: str
    valor_archivo: str


@dataclass
class VistaPrevia:
    """Lo que la importación va a hacer, sin haberlo hecho todavía."""

    archivo: str
    filas: int
    cambios: list[Cambio] = field(default_factory=list)
    sin_cambio: list[dict] = field(default_factory=list)
    conflictos: list[Conflicto] = field(default_factory=list)
    no_encontrados: list[FilaReportada] = field(default_factory=list)
    invalidos: list[FilaReportada] = field(default_factory=list)
    diferencias: list[DiferenciaReportada] = field(default_factory=list)
    faltantes: list[dict] = field(default_factory=list)

    @property
    def cambios_lista(self) -> list[Cambio]:
        return [cambio for cambio in self.cambios if cambio.cambia_lista]

    @property
    def cambios_telefono(self) -> list[Cambio]:
        return [cambio for cambio in self.cambios if cambio.completa_telefono]

    @property
    def hay_conflictos(self) -> bool:
        return bool(self.conflictos)

    def resumen(self) -> dict:
        return {
            "filas": self.filas,
            "cambios_lista": len(self.cambios_lista),
            "cambios_telefono": len(self.cambios_telefono),
            "sin_cambio": len(self.sin_cambio),
            "conflictos": len(self.conflictos),
            "no_encontrados": len(self.no_encontrados),
            "invalidos": len(self.invalidos),
            "diferencias": len(self.diferencias),
            "faltantes": len(self.faltantes),
        }


@dataclass
class Resultado:
    """Lo que se aplicó de verdad."""

    cambios_lista: int = 0
    cambios_telefono: int = 0
    respaldo: str = ""
    errores: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errores


class ClientPriceListImporter:
    """Importa la lista de precios (y completa el teléfono) desde un Excel."""

    def __init__(self, *, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    # ---------------------------------------------------------------- lectura

    def leer_filas(self, archivo: str | Path) -> list[FilaArchivo]:
        """Lee el Excel y devuelve sus filas. No toca la base."""
        ruta = Path(archivo)
        if not ruta.is_file():
            raise ImportPriceListError(f"No existe el archivo: {ruta}")
        if ruta.suffix.lower() != ".xlsx":
            raise ImportPriceListError("El archivo tiene que ser un Excel .xlsx")

        workbook = load_workbook(ruta, read_only=True, data_only=True)
        try:
            hoja = workbook.active
            filas = list(hoja.iter_rows(values_only=True))
        finally:
            workbook.close()

        if not filas:
            raise ImportPriceListError("El archivo está vacío.")

        columnas = self._detectar_columnas(filas[0])
        if COLUMN_CUIT not in columnas or COLUMN_LISTA not in columnas:
            raise ImportPriceListError(
                "El archivo tiene que tener las columnas CUIT y Lista. "
                "Use el Excel que exporta la app (Clientes > Exportar a Excel)."
            )

        resultado: list[FilaArchivo] = []
        for numero, valores in enumerate(filas[1:], start=2):
            fila = self._armar_fila(numero, valores, columnas)
            if fila is not None:
                resultado.append(fila)
        return resultado

    @staticmethod
    def _detectar_columnas(encabezados) -> dict[str, int]:
        columnas: dict[str, int] = {}
        for indice, encabezado in enumerate(encabezados or ()):
            clave = normalizar_texto(encabezado)
            if not clave:
                continue
            for nombre, aceptados in ENCABEZADOS_ACEPTADOS.items():
                if nombre in columnas:
                    continue
                if clave in aceptados:
                    columnas[nombre] = indice
                    break
        return columnas

    @staticmethod
    def _armar_fila(numero: int, valores, columnas: dict[str, int]) -> FilaArchivo | None:
        def valor(clave: str) -> str:
            indice = columnas.get(clave)
            if indice is None or indice >= len(valores or ()):
                return ""
            return str(valores[indice] or "").strip()

        nombre = valor(COLUMN_NOMBRE)
        cuit = valor(COLUMN_CUIT)
        lista_texto = valor(COLUMN_LISTA)
        if not any((nombre, cuit, lista_texto, valor(COLUMN_TELEFONO))):
            return None
        return FilaArchivo(
            numero=numero,
            nombre=nombre,
            cuit=cuit,
            cuit_normalizado=normalizar_cuit(cuit),
            lista=_parse_lista(valores[columnas[COLUMN_LISTA]] if COLUMN_LISTA in columnas else None),
            lista_texto=lista_texto,
            telefono=valor(COLUMN_TELEFONO),
            iva=valor(COLUMN_IVA),
            email=valor(COLUMN_EMAIL),
            contacto=valor(COLUMN_CONTACTO),
        )

    # ------------------------------------------------------- vista previa

    def construir_vista_previa(self, archivo: str | Path) -> VistaPrevia:
        """Arma el informe de lo que se va a aplicar. **No escribe nada.**"""
        filas = self.leer_filas(archivo)
        vista = VistaPrevia(archivo=str(archivo), filas=len(filas))

        clientes = list(Client.select().order_by(Client.id))
        por_cuit: dict[str, list[Client]] = defaultdict(list)
        por_nombre: dict[str, list[Client]] = defaultdict(list)
        for cliente in clientes:
            por_cuit[normalizar_cuit(cliente.cuit)].append(cliente)
            por_nombre[normalizar_nombre(cliente.name)].append(cliente)

        # Filas del archivo agrupadas por CUIT normalizado: el mismo cliente puede
        # estar escrito de dos formas (con el CUIT con guiones y sin guiones).
        grupos: dict[str, list[FilaArchivo]] = defaultdict(list)
        sin_cuit: list[FilaArchivo] = []
        for fila in filas:
            if fila.cuit_normalizado:
                grupos[fila.cuit_normalizado].append(fila)
            else:
                sin_cuit.append(fila)

        for cuit, grupo in grupos.items():
            self._procesar_grupo(grupo, por_cuit, por_nombre, vista)

        for fila in sin_cuit:
            self._procesar_sin_cuit(fila, por_nombre, vista)

        # Clientes de la base que el archivo no menciona: quedan como están.
        mencionados = {cambio.client_id for cambio in vista.cambios}
        mencionados.update(
            item["client_id"] for item in vista.sin_cambio if "client_id" in item
        )
        for cliente in clientes:
            if cliente.id not in mencionados:
                vista.faltantes.append(
                    {
                        "client_id": cliente.id,
                        "nombre": cliente.name,
                        "cuit": cliente.cuit or "",
                        "lista": cliente.lista_precios,
                    }
                )
        return vista

    def _procesar_grupo(
        self,
        grupo: list[FilaArchivo],
        por_cuit: dict[str, list[Client]],
        por_nombre: dict[str, list[Client]],
        vista: VistaPrevia,
    ) -> None:
        cuit = grupo[0].cuit_normalizado
        listas = {fila.lista for fila in grupo if fila.lista is not None}

        if len(listas) > 1:
            vista.conflictos.append(
                Conflicto(
                    tipo="cuit_duplicado_archivo",
                    detalle=(
                        "El mismo CUIT aparece en el archivo con listas distintas "
                        f"({', '.join(str(l) for l in sorted(listas))}). Dejá una sola fila "
                        "por cliente en el Excel y volvé a importar."
                    ),
                    cuit=cuit,
                    filas=tuple(fila.numero for fila in grupo),
                    nombres=tuple(sorted({fila.nombre for fila in grupo})),
                )
            )
            return

        invalidas = [fila for fila in grupo if fila.lista is None]
        for fila in invalidas:
            vista.invalidos.append(
                FilaReportada(
                    fila=fila.numero,
                    nombre=fila.nombre,
                    cuit=fila.cuit,
                    motivo="lista inválida",
                    detalle=(
                        f"La lista '{fila.lista_texto}' no es válida: tiene que ser 1, 2, 3 o 4."
                    ),
                )
            )
        validas = [fila for fila in grupo if fila.lista is not None]
        if not validas:
            return

        principal = validas[0]
        candidatos = por_cuit.get(cuit, [])
        if not candidatos:
            vista.no_encontrados.append(
                FilaReportada(
                    fila=principal.numero,
                    nombre=principal.nombre,
                    cuit=principal.cuit,
                    motivo="CUIT no encontrado en la base",
                    detalle=self._pista_por_nombre(principal, por_nombre),
                )
            )
            return

        if len(candidatos) > 1:
            nombres = {normalizar_nombre(candidato.name) for candidato in candidatos}
            if len(nombres) == 1:
                # Es el mismo cliente en varias filas de la base: el CUIT se
                # guardó en formatos distintos (el legacy sin guiones, la carga
                # manual con guiones) y el UNIQUE de la base es sobre el texto,
                # así que conviven. La lista del archivo se le aplica a TODAS
                # sus filas: el mismo cliente no puede tener dos listas de
                # precios. Se avisa que conviene unificarlas, pero no se borra
                # ninguna: las filas del legacy tienen historia (presupuestos,
                # remitos, cuenta corriente) y unificarlas es un trabajo aparte.
                for candidato in candidatos:
                    self._evaluar(candidato, principal, "cuit duplicado unificado", vista)
                vista.conflictos.append(
                    Conflicto(
                        tipo="duplicado_unificado",
                        detalle=(
                            "El CUIT corresponde a varias filas del mismo cliente en la base "
                            f"({candidatos[0].name}). Se actualizaron todas con la lista del "
                            "archivo; conviene unificarlas."
                        ),
                        cuit=cuit,
                        filas=(principal.numero,),
                        nombres=tuple(sorted({candidato.name for candidato in candidatos})),
                    )
                )
                return

            # Nombres distintos: son clientes distintos que comparten el CUIT.
            # No se aplica nada: es un error de datos que hay que corregir a mano.
            vista.conflictos.append(
                Conflicto(
                    tipo="cuit_ambiguo_base",
                    detalle=(
                        "El CUIT corresponde a más de un cliente en la base. "
                        "No se aplica nada: revisá a mano."
                    ),
                    cuit=cuit,
                    filas=tuple(fila.numero for fila in grupo),
                    nombres=tuple(sorted({candidato.name for candidato in candidatos})),
                )
            )
            return

        self._evaluar(candidatos[0], principal, "CUIT", vista)

    def _procesar_sin_cuit(
        self,
        fila: FilaArchivo,
        por_nombre: dict[str, list[Client]],
        vista: VistaPrevia,
    ) -> None:
        if fila.lista is None:
            vista.invalidos.append(
                FilaReportada(
                    fila=fila.numero,
                    nombre=fila.nombre,
                    cuit=fila.cuit,
                    motivo="lista inválida",
                    detalle=(
                        f"La lista '{fila.lista_texto}' no es válida: tiene que ser 1, 2, 3 o 4."
                    ),
                )
            )
            return
        candidatos = por_nombre.get(normalizar_nombre(fila.nombre), [])
        if len(candidatos) != 1:
            vista.no_encontrados.append(
                FilaReportada(
                    fila=fila.numero,
                    nombre=fila.nombre,
                    cuit=fila.cuit,
                    motivo="sin CUIT y el nombre no da un único cliente",
                    detalle=(
                        f"Hay {len(candidatos)} clientes con ese nombre en la base."
                        if candidatos
                        else "No hay ningún cliente con ese nombre en la base."
                    ),
                )
            )
            return
        self._evaluar(candidatos[0], fila, "nombre", vista)

    @staticmethod
    def _pista_por_nombre(fila: FilaArchivo, por_nombre: dict[str, list[Client]]) -> str:
        candidatos = por_nombre.get(normalizar_nombre(fila.nombre), [])
        if len(candidatos) == 1:
            return (
                f"En la base hay un cliente con ese nombre ({candidatos[0].name}) pero con "
                "otro CUIT: revisalo a mano."
            )
        return ""

    def _evaluar(
        self,
        cliente: Client,
        fila: FilaArchivo,
        motivo: str,
        vista: VistaPrevia,
    ) -> None:
        """Calcula qué cambia de un cliente contra la fila del archivo. No escribe."""
        lista_anterior = int(cliente.lista_precios or 1)
        lista_nueva = int(fila.lista)
        telefono_anterior = (cliente.phone or "").strip()
        telefono_nuevo = (fila.telefono or "").strip()

        cambia_lista = lista_anterior != lista_nueva
        completa_telefono = not telefono_anterior and bool(telefono_nuevo)

        if cambia_lista or completa_telefono:
            vista.cambios.append(
                Cambio(
                    client_id=cliente.id,
                    nombre=cliente.name,
                    cuit=cliente.cuit or "",
                    motivo=motivo,
                    lista_anterior=lista_anterior,
                    lista_nueva=lista_nueva,
                    telefono_anterior=telefono_anterior,
                    telefono_nuevo=telefono_nuevo,
                    fila=fila.numero,
                )
            )
        else:
            vista.sin_cambio.append(
                {
                    "client_id": cliente.id,
                    "nombre": cliente.name,
                    "cuit": cliente.cuit or "",
                    "lista": lista_anterior,
                    "motivo": motivo,
                }
            )

        # Diferencias que NO se aplican: se informan para que el operador las vea.
        if telefono_anterior and telefono_nuevo:
            if solo_digitos(telefono_anterior) != solo_digitos(telefono_nuevo):
                vista.diferencias.append(
                    DiferenciaReportada(
                        fila=fila.numero,
                        nombre=cliente.name,
                        cuit=cliente.cuit or "",
                        campo="teléfono",
                        valor_base=telefono_anterior,
                        valor_archivo=telefono_nuevo,
                    )
                )
        if fila.nombre and normalizar_nombre(fila.nombre) != normalizar_nombre(cliente.name):
            vista.diferencias.append(
                DiferenciaReportada(
                    fila=fila.numero,
                    nombre=cliente.name,
                    cuit=cliente.cuit or "",
                    campo="nombre",
                    valor_base=cliente.name,
                    valor_archivo=fila.nombre,
                )
            )
        if fila.iva and normalizar_texto(fila.iva) != normalizar_texto(cliente.iva_condition):
            vista.diferencias.append(
                DiferenciaReportada(
                    fila=fila.numero,
                    nombre=cliente.name,
                    cuit=cliente.cuit or "",
                    campo="condición de IVA",
                    valor_base=cliente.iva_condition,
                    valor_archivo=fila.iva,
                )
            )
        if fila.email and normalizar_texto(fila.email) != normalizar_texto(cliente.email):
            vista.diferencias.append(
                DiferenciaReportada(
                    fila=fila.numero,
                    nombre=cliente.name,
                    cuit=cliente.cuit or "",
                    campo="email",
                    valor_base=cliente.email or "",
                    valor_archivo=fila.email,
                )
            )
        if fila.contacto and normalizar_texto(fila.contacto) != normalizar_texto(cliente.contact):
            vista.diferencias.append(
                DiferenciaReportada(
                    fila=fila.numero,
                    nombre=cliente.name,
                    cuit=cliente.cuit or "",
                    campo="contacto",
                    valor_base=cliente.contact or "",
                    valor_archivo=fila.contacto,
                )
            )

    # ------------------------------------------------------------ aplicación

    def exportar_respaldo(self, destino: str | Path) -> Path:
        """Guarda el estado actual de lista y teléfono de todos los clientes."""
        ruta = Path(destino)
        if ruta.suffix.lower() != ".xlsx":
            ruta = ruta.with_suffix(".xlsx")
        ruta.parent.mkdir(parents=True, exist_ok=True)

        libro = Workbook()
        hoja = libro.active
        hoja.title = "Respaldo"
        hoja.append(["id", "Nombre", "CUIT", "Celular / Teléfono", "Lista"])
        for cliente in Client.select().order_by(Client.id):
            hoja.append(
                [
                    cliente.id,
                    cliente.name,
                    cliente.cuit or "",
                    cliente.phone or "",
                    cliente.lista_precios,
                ]
            )
        libro.save(ruta)
        return ruta

    def aplicar(
        self,
        vista: VistaPrevia,
        *,
        directorio_respaldo: str | Path | None = None,
    ) -> Resultado:
        """Aplica los cambios de la vista previa, en una sola transacción."""
        from app.config.database import database_proxy

        resultado = Resultado()
        if not vista.cambios:
            return resultado

        base = Path(vista.archivo).parent if directorio_respaldo is None else Path(directorio_respaldo)
        sello = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            respaldo = self.exportar_respaldo(base / f"respaldo_listas_{sello}.xlsx")
            resultado.respaldo = str(respaldo)
        except Exception as exc:  # pragma: no cover - depende del disco
            resultado.errores.append(f"No se pudo guardar el respaldo: {exc}")
            return resultado

        database = database_proxy.obj
        try:
            with database.atomic():
                for cambio in vista.cambios:
                    cliente = Client.get_by_id(cambio.client_id)
                    if cambio.cambia_lista:
                        anterior = int(cliente.lista_precios or 1)
                        cliente.lista_precios = cambio.lista_nueva
                        # ``updated_at`` va explícito: con ``only`` peewee solo
                        # escribe los campos listados, y sin esto la fila no
                        # dejaría rastro de cuándo se tocó.
                        cliente.save(only=[Client.lista_precios, Client.updated_at])
                        self.audit_service.record(
                            user=self.current_user,
                            module="Clientes",
                            action="actualizar lista de precios",
                            record_ref=f"Client:{cliente.id}",
                            old_value={"lista_precios": anterior},
                            new_value={"lista_precios": cambio.lista_nueva},
                        )
                        resultado.cambios_lista += 1
                    if cambio.completa_telefono:
                        cliente.phone = cambio.telefono_nuevo
                        cliente.save(only=[Client.phone, Client.updated_at])
                        self.audit_service.record(
                            user=self.current_user,
                            module="Clientes",
                            action="completar teléfono",
                            record_ref=f"Client:{cliente.id}",
                            old_value={"phone": cambio.telefono_anterior or None},
                            new_value={"phone": cambio.telefono_nuevo},
                        )
                        resultado.cambios_telefono += 1
        except Exception as exc:
            resultado.errores.append(f"No se pudo aplicar la importación: {exc}")
            return resultado
        return resultado
