"""Configuración y audiencia de la campaña de lista de precios (#705, Fase B).

Esta es la **base de la Fase B** (issue #763): todavía **no envía nada**. Define

1. la configuración de cada lista de precios (1 a 4): **su** PDF y **su** plantilla de mensaje,
   guardados en ``AppParameter`` (clave-valor, sin migración de base), y
2. el **cálculo de la audiencia**: qué clientes de esa lista se pueden mandar por WhatsApp,
   con el clasificador de teléfonos que ya usa la app (``whatsapp_phone_classifier``).

Por qué el filtro es estricto: un número local de 10 u 11 dígitos puede ser una línea fija o un
celular escrito sin el "15". Mandarle la lista a un número que no es del cliente no es solo un
error de datos: es lo que más rápido hace que el proveedor bloquee la línea. Por eso el
clasificador tiene tres estados y acá solo se marcan, por defecto, los **celulares sin ambigüedad**:
los "posibles" quedan a la vista con el número exacto que se mandaría, pero el operador tiene que
tildarlos a mano.

El motor de envío (cola, throttling, tope diario) y la pantalla viven en etapas siguientes del
mismo issue: este módulo es puro y se puede testear sin base de producción ni gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models.masters import Client
from app.models.system import AppParameter
from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_INVALIDO,
    ESTADO_POSIBLE,
    ESTADO_VACIO,
    clasificar_telefono,
)

#: Las listas de precios que acepta el maestro.
LISTAS_VALIDAS = (1, 2, 3, 4)

#: Nombre de la empresa en el mensaje. El default es FEMAG; se puede cambiar por puesto.
EMPRESA_POR_DEFECTO = "FEMAG"
EMPRESA_KEY = "empresa.nombre"

#: Plantilla por lista: ``lista_precios_pdf_{N}`` y ``lista_precios_mensaje_{N}``.
PDF_KEY = "lista_precios_pdf_{lista}"
MENSAJE_KEY = "lista_precios_mensaje_{lista}"

#: Variables que se sustituyen en la plantilla del mensaje.
VARIABLE_CLIENTE = "{cliente}"
VARIABLE_LISTA = "{lista}"
VARIABLE_EMPRESA = "{empresa}"

MENSAJE_POR_DEFECTO = (
    "Hola {cliente}, adjuntamos la lista de precios {lista} de {empresa}. "
    "Quedamos a disposición."
)


class CampaignConfigError(RuntimeError):
    """Error de configuración de la campaña, con un mensaje para mostrar en pantalla."""


def _validar_lista(lista) -> int:
    try:
        valor = int(lista)
    except (TypeError, ValueError) as exc:
        raise CampaignConfigError("La lista de precios tiene que ser 1, 2, 3 o 4.") from exc
    if valor not in LISTAS_VALIDAS:
        raise CampaignConfigError("La lista de precios tiene que ser 1, 2, 3 o 4.")
    return valor


@dataclass(frozen=True)
class PriceListCampaignConfig:
    """La configuración de una lista: su PDF y su plantilla de mensaje."""

    lista: int
    pdf_path: str = ""
    mensaje: str = ""
    empresa: str = EMPRESA_POR_DEFECTO

    @property
    def tiene_pdf(self) -> bool:
        return bool(self.pdf_path.strip())

    @property
    def pdf_existe(self) -> bool:
        """True si el PDF asociado todavía está en el disco."""
        if not self.tiene_pdf:
            return False
        return Path(self.pdf_path).is_file()

    def mensaje_para(self, nombre_cliente: str) -> str:
        """La plantilla con las variables sustituidas para un cliente."""
        plantilla = self.mensaje.strip() or MENSAJE_POR_DEFECTO
        return (
            plantilla.replace(VARIABLE_CLIENTE, nombre_cliente or "")
            .replace(VARIABLE_LISTA, str(self.lista))
            .replace(VARIABLE_EMPRESA, self.empresa or EMPRESA_POR_DEFECTO)
        )


@dataclass(frozen=True)
class Destinatario:
    """Un cliente de la lista, con el teléfono tal como está y el que se mandaría."""

    client_id: int
    nombre: str
    telefono_original: str
    telefono_normalizado: str
    estado: str
    motivo: str
    lista: int
    marcado: bool

    @property
    def es_celular(self) -> bool:
        return self.estado == ESTADO_CELULAR

    @property
    def es_posible(self) -> bool:
        return self.estado == ESTADO_POSIBLE

    @property
    def enviable(self) -> bool:
        """Si se puede llegar a mandar: tiene un número que el gateway va a aceptar."""
        return self.estado in {ESTADO_CELULAR, ESTADO_POSIBLE}


@dataclass(frozen=True)
class Audiencia:
    """A quién le corresponde la lista, con el motivo de cada caso."""

    lista: int
    destinatarios: tuple[Destinatario, ...] = ()
    inactivos_omitidos: int = 0

    @property
    def total(self) -> int:
        return len(self.destinatarios)

    @property
    def celulares(self) -> tuple[Destinatario, ...]:
        return tuple(d for d in self.destinatarios if d.es_celular)

    @property
    def posibles(self) -> tuple[Destinatario, ...]:
        return tuple(d for d in self.destinatarios if d.es_posible)

    @property
    def invalidos(self) -> tuple[Destinatario, ...]:
        return tuple(d for d in self.destinatarios if d.estado == ESTADO_INVALIDO)

    @property
    def vacios(self) -> tuple[Destinatario, ...]:
        return tuple(d for d in self.destinatarios if d.estado == ESTADO_VACIO)

    @property
    def marcados(self) -> tuple[Destinatario, ...]:
        """Los que van marcados: por defecto, solo los celulares."""
        return tuple(d for d in self.destinatarios if d.marcado)

    @property
    def a_enviar(self) -> int:
        return len(self.marcados)

    def contadores(self) -> dict:
        """Los números que la pantalla muestra antes de enviar."""
        return {
            "lista": self.lista,
            "total": self.total,
            "celulares": len(self.celulares),
            "posibles": len(self.posibles),
            "invalidos": len(self.invalidos),
            "sin_telefono": len(self.vacios),
            "inactivos_omitidos": self.inactivos_omitidos,
            "a_enviar": self.a_enviar,
        }


class PriceListCampaignService:
    """Configuración por lista y cálculo de la audiencia de la campaña."""

    # ------------------------------------------------------------- AppParameter

    @staticmethod
    def _get(key: str) -> str | None:
        fila = AppParameter.get_or_none(AppParameter.key == key)
        return fila.value if fila else None

    @staticmethod
    def _set(key: str, value: str | None) -> None:
        fila, _ = AppParameter.get_or_create(key=key)
        fila.value = value
        fila.save()

    # ------------------------------------------------------------ configuración

    @classmethod
    def config(cls, lista) -> PriceListCampaignConfig:
        """La configuración guardada de una lista."""
        numero = _validar_lista(lista)
        return PriceListCampaignConfig(
            lista=numero,
            pdf_path=(cls._get(PDF_KEY.format(lista=numero)) or "").strip(),
            mensaje=(cls._get(MENSAJE_KEY.format(lista=numero)) or "").strip(),
            empresa=(cls._get(EMPRESA_KEY) or "").strip() or EMPRESA_POR_DEFECTO,
        )

    @classmethod
    def guardar(cls, lista, *, pdf_path: str = "", mensaje: str = "", empresa: str = "") -> PriceListCampaignConfig:
        """Guarda la configuración de una lista. Devuelve lo que quedó guardado."""
        numero = _validar_lista(lista)
        ruta = cls.validar_pdf(pdf_path) if (pdf_path or "").strip() else ""
        cls._set(PDF_KEY.format(lista=numero), ruta)
        cls._set(MENSAJE_KEY.format(lista=numero), (mensaje or "").strip())
        if (empresa or "").strip():
            cls._set(EMPRESA_KEY, empresa.strip())
        return cls.config(numero)

    @staticmethod
    def validar_pdf(ruta) -> str:
        """Valida el PDF de la lista y devuelve la ruta absoluta.

        El PDF **va por lista**: no se puede mandar el de otra lista sin cambiarlo a mano, así que
        la validación es estricta (existe, es un archivo, no está vacío y es un ``.pdf``).
        """
        texto = str(ruta or "").strip()
        if not texto:
            raise CampaignConfigError("Elegí el PDF de la lista de precios.")
        camino = Path(texto).expanduser()
        if not camino.exists():
            raise CampaignConfigError(f"No existe el PDF: {camino}")
        if not camino.is_file():
            raise CampaignConfigError(f"El PDF no es un archivo: {camino}")
        if camino.suffix.lower() != ".pdf":
            raise CampaignConfigError("El archivo de la lista tiene que ser un PDF (.pdf).")
        try:
            if camino.stat().st_size <= 0:
                raise CampaignConfigError("El PDF está vacío.")
        except OSError as exc:  # pragma: no cover - depende del disco
            raise CampaignConfigError(f"No se pudo leer el PDF: {exc}") from exc
        return str(camino.resolve())

    # ---------------------------------------------------------------- audiencia

    @classmethod
    def calcular_audiencia(cls, lista, *, marcar_posibles: bool = False) -> Audiencia:
        """Calcula a quién le corresponde la lista, contra la base real.

        Solo entran los clientes **activos** de esa lista. Por defecto van marcados los
        **celulares sin ambigüedad**; los "posibles" (un local de 10 u 11 dígitos puede ser fijo o
        móvil escrito sin el "15") quedan a la vista pero **sin marcar**: mandarlos es decisión del
        operador, no del sistema.
        """
        numero = _validar_lista(lista)
        destinatarios: list[Destinatario] = []
        inactivos = 0

        clientes = (
            Client.select()
            .where(Client.lista_precios == numero)
            .order_by(Client.id)
        )
        for cliente in clientes:
            if not cliente.active:
                inactivos += 1
                continue
            clasificacion = clasificar_telefono(cliente.phone)
            marcado = clasificacion.estado == ESTADO_CELULAR or (
                marcar_posibles and clasificacion.estado == ESTADO_POSIBLE
            )
            destinatarios.append(
                Destinatario(
                    client_id=cliente.id,
                    nombre=cliente.name or "",
                    telefono_original=(cliente.phone or "").strip(),
                    telefono_normalizado=clasificacion.normalizado or "",
                    estado=clasificacion.estado,
                    motivo=clasificacion.motivo or "",
                    lista=numero,
                    marcado=marcado,
                )
            )

        return Audiencia(
            lista=numero,
            destinatarios=tuple(destinatarios),
            inactivos_omitidos=inactivos,
        )
