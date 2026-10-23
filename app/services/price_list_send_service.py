"""Motor de la campaña de lista de precios por WhatsApp (#705, Fase B, etapa B2).

El motor es **secuencial y con freno**: un envío a la vez, con intervalo, tope diario y
circuit breaker. Es lo que evita que la campaña queme la línea de la usuaria.

Reglas (spec §4.3):

- un solo hilo de trabajo, secuencial, con espera entre envíos;
- **intervalo con jitter, contado desde el envío anterior**;
- **lote inicial**: al completarlo, la campaña se detiene y espera la confirmación;
- **tope de 100 mensajes por día y por instancia**, contado desde ``whatsapp_envios``;
- **circuit breaker**: un rate-limit/ban del gateway detiene la campaña completa y deja el
  resto en cola; nunca se insiste contra un rechazo;
- **reintentos**: máximo 2, solo para errores transitorios (timeout, 5xx);
- **idempotencia**: la clave de campaña y el ``external_ref`` por destinatario hacen que
  reanudar no vuelva a mandar a quien ya tiene estado terminal.

El motor **no hereda de QThread**: es una clase común con el reloj, la espera y el servicio de
envío inyectados, para que los tests corran la cola entera en milisegundos y contra un gateway
falso. La pantalla (etapa B3) la corre dentro de un ``QRunnable``.

El número que se manda es el que devuelve el **clasificador** (``clasificar_telefono``), no el
normalizador viejo de los envíos 1 a 1: ese normalizador convierte líneas fijas en móviles
falsos (#759) y además **corrompe** un número que ya viene normalizado
(``5491153088679`` -> ``54954913088679``). Por eso acá el destino entra **ya normalizado** y se
escribe tal cual en la auditoría, sin pasar por ``create_attempt``.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.whatsapp import WhatsAppEnvio
from app.services.price_list_campaign_service import Destinatario
from app.services.whatsapp_envio_service import WhatsAppEnvioService

#: ``tipo_documento`` de la campaña en la auditoría de envíos.
TIPO_DOCUMENTO = "lista_precios"

#: Tope diario por instancia (spec §4.3).
TOPE_DIARIO = 100

#: Reintentos extra, solo para errores transitorios.
MAX_REINTENTOS = 2

#: Límites del intervalo configurables (spec §4.2).
INTERVALO_MINIMO = 60.0
INTERVALO_MAXIMO = 600.0

#: Zona horaria del puesto: el tope diario se cuenta de medianoche local.
#:
#: Argentina es UTC-3 fijo (no aplica horario de verano desde 2009), así que se usa un
#: desplazamiento constante en lugar de ``zoneinfo``: en Windows la base de zonas horarias del
#: sistema no está y ``zoneinfo`` necesita el paquete ``tzdata``, que no está en los requisitos
#: (y en el venv limpio del release la app no arrancaba). Con el desplazamiento fijo no hace
#: falta ninguna dependencia extra y el resultado es el mismo para el puesto.
ZONA = timezone(timedelta(hours=-3))

#: Estados que cortan la idempotencia: si el envío ya está en uno de estos, no se repite.
#: ``queued`` y ``accepted`` también cuentan: el gateway ya tomó el mensaje, mandarlo de vuelta
#: sería mandarlo dos veces. ``failed`` cuenta para que el reintento sea explícito, no automático.
ESTADOS_TERMINALES = {"delivered", "read", "failed", "accepted", "queued"}


class CampaignError(RuntimeError):
    """Error de la campaña, con un mensaje para mostrar en pantalla."""


class CircuitBreakerError(CampaignError):
    """El gateway rechazó la campaña (rate-limit/ban): hay que parar."""


def clave_campana(lista, pdf_path, momento=None) -> str:
    """Clave de la campaña: ``lista{N}-{pdf}-{AAAAMMDD-HHMM}``.

    Identifica "lista 1 + lista1.pdf + 23/10 17:30": sirve para retomar, auditar y no repetir.
    """
    numero = int(lista)
    nombre = Path(str(pdf_path)).stem or "lista"
    sello = (momento or datetime.now(ZONA)).strftime("%Y%m%d-%H%M")
    return f"lista{numero}-{nombre}-{sello}"


def external_ref(clave: str, client_id: int) -> str:
    """Referencia externa estable de un destinatario dentro de una campaña."""
    return f"femag:{TIPO_DOCUMENTO}:{clave}:{int(client_id)}"


def inicio_del_dia_utc(ahora=None) -> datetime:
    """La medianoche local de hoy, en UTC naive (así se guarda ``created_at``)."""
    if ahora is None:
        ahora = datetime.now(ZONA)
    elif ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=ZONA)
    local = ahora.astimezone(ZONA).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _a_utc_naive(valor) -> datetime | None:
    """Normaliza un ``created_at`` de la base a UTC naive."""
    if valor is None:
        return None
    if getattr(valor, "tzinfo", None) is not None:
        return valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def es_rate_limit(exc: Exception) -> bool:
    """True si el gateway está rechazando por rate-limit/ban."""
    texto = str(exc).lower()
    return any(
        marca in texto
        for marca in ("429", "rate limit", "ratelimit", "too many", "demasiados", "ban", "bloquead")
    )


def es_transitorio(exc: Exception) -> bool:
    """True si el error vale la pena reintentar (timeout, 5xx, red)."""
    if es_rate_limit(exc):
        return False
    texto = str(exc)
    if re.search(r"\b4\d\d\b", texto):
        return False
    return True


@dataclass(frozen=True)
class Pendiente:
    """Un destinatario con su número ya normalizado y su mensaje listo."""

    client_id: int
    nombre: str
    telefono: str
    caption: str = ""


@dataclass(frozen=True)
class Evento:
    """Lo que va contando la pantalla mientras corre la campaña."""

    tipo: str
    client_id: int = 0
    nombre: str = ""
    detalle: str = ""


@dataclass
class ResultadoCampana:
    """Cómo terminó la campaña."""

    enviados: int = 0
    fallidos: int = 0
    omitidos: int = 0
    detenido_por: str = ""
    motivo: str = ""
    errores: list[str] = field(default_factory=list)

    @property
    def terminada(self) -> bool:
        return not self.detenido_por


def ya_enviados(clave: str) -> set[int]:
    """Los ``client_id`` que ya tienen un envío terminal en esa campaña."""
    enviados: set[int] = set()
    consulta = WhatsAppEnvio.select().where(
        (WhatsAppEnvio.tipo_documento == TIPO_DOCUMENTO)
        & (WhatsAppEnvio.documento_id == clave)
    )
    for envio in consulta:
        if envio.estado not in ESTADOS_TERMINALES:
            continue
        try:
            enviados.add(int(str(envio.external_ref).rsplit(":", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return enviados


def contar_envios_del_dia(instance_id: str, ahora=None) -> int:
    """Cuántos mensajes de la campaña ya salieron hoy desde esa instancia."""
    if not instance_id:
        return 0
    inicio = inicio_del_dia_utc(ahora)
    total = 0
    consulta = WhatsAppEnvio.select().where(
        (WhatsAppEnvio.tipo_documento == TIPO_DOCUMENTO)
        & (WhatsAppEnvio.instance_id == instance_id)
    )
    for envio in consulta:
        creado = _a_utc_naive(envio.created_at)
        if creado is None or creado < inicio:
            continue
        total += 1
    return total


def destinatarios_pendientes(
    clave: str, destinatarios, *, cliente_ids: set[int] | None = None
) -> list[Destinatario]:
    """Saca de la audiencia a quien ya tiene un envío terminal en esa campaña.

    Es lo que hace que reanudar una campaña **no vuelva a mandar** a quien ya la recibió.
    """
    enviados = ya_enviados(clave)
    if cliente_ids:
        enviados = enviados | set(cliente_ids)
    return [d for d in destinatarios if d.client_id not in enviados]


class PriceListCampaignRunner:
    """La cola de envíos: uno a uno, con las reglas de freno de la campaña."""

    def __init__(
        self,
        *,
        clave: str,
        pdf_path,
        pendientes,
        usuario=None,
        envios: WhatsAppEnvioService | None = None,
        instance_id: str = "",
        intervalo: float = 180.0,
        lote_inicial: int = 20,
        tope_diario: int = TOPE_DIARIO,
        max_reintentos: int = MAX_REINTENTOS,
        jitter: float = 0.1,
        dormir=time.sleep,
        reloj=time.monotonic,
        azar=random.uniform,
        ahora=None,
        al_evento=None,
    ):
        self.clave = clave
        self.pdf_path = Path(str(pdf_path))
        self.pendientes = list(pendientes)
        self.usuario = usuario
        self.envios = envios or WhatsAppEnvioService()
        self.instance_id = instance_id
        self.intervalo = float(intervalo)
        self.lote_inicial = int(lote_inicial)
        self.tope_diario = int(tope_diario)
        self.max_reintentos = int(max_reintentos)
        self.jitter = float(jitter)
        self.dormir = dormir
        self.reloj = reloj
        self.azar = azar
        self.ahora = ahora or (lambda: datetime.now(ZONA))
        self.al_evento = al_evento
        self._pausa = threading.Event()
        self._cancelado = threading.Event()

    # ------------------------------------------------------------- control

    def pausar(self) -> None:
        self._pausa.set()

    def reanudar(self) -> None:
        self._pausa.clear()

    def cancelar(self) -> None:
        self._cancelado.set()
        self._pausa.clear()

    @property
    def pausado(self) -> bool:
        return self._pausa.is_set()

    @property
    def cancelado(self) -> bool:
        return self._cancelado.is_set()

    # ---------------------------------------------------------------- corrida

    def run(self) -> ResultadoCampana:
        """Ejecuta la cola. Devuelve cómo terminó."""
        resultado = ResultadoCampana()
        if not self.instance_id:
            self.instance_id = self.envios.resolve_instance_for_user(self.usuario)

        enviados_hoy = contar_envios_del_dia(self.instance_id, self.ahora())
        ultimo_envio = None

        for pendiente in self.pendientes:
            if self.cancelado:
                resultado.detenido_por = "cancelado"
                resultado.motivo = "La campaña se canceló."
                break

            self._esperar_reanudacion()
            if self.cancelado:
                resultado.detenido_por = "cancelado"
                resultado.motivo = "La campaña se canceló."
                break

            if enviados_hoy + resultado.enviados >= self.tope_diario:
                resultado.detenido_por = "tope_diario"
                resultado.motivo = (
                    f"Límite diario alcanzado ({self.tope_diario} mensajes). Mañana continúa."
                )
                self._emitir("tope", detalle=resultado.motivo)
                break

            envio, error = self._enviar_con_reintentos(pendiente)
            if envio is not None and not error:
                resultado.enviados += 1
                enviados_hoy += 1
                ultimo_envio = self.reloj()
                self._emitir("enviado", pendiente, envio.message_id or "")
                if (
                    self.lote_inicial
                    and resultado.enviados >= self.lote_inicial
                    and self._quedan_pendientes(pendiente)
                ):
                    resultado.detenido_por = "lote_inicial"
                    resultado.motivo = (
                        f"{resultado.enviados} enviados. "
                        "Confirmá si querés seguir con los que quedan."
                    )
                    self._emitir("detenido", detalle=resultado.motivo)
                    break
            else:
                if error and es_rate_limit(error):
                    resultado.detenido_por = "circuit_breaker"
                    resultado.motivo = (
                        "El gateway rechazó la campaña (límite de envíos). "
                        "Se paró para no hacer daño la línea."
                    )
                    resultado.errores.append(str(error))
                    self._emitir("circuit_breaker", pendiente, str(error))
                    break
                resultado.fallidos += 1
                resultado.errores.append(str(error) if error else "Error desconocido.")
                self._emitir("fallido", pendiente, str(error) if error else "")

            if ultimo_envio is not None:
                self._esperar_intervalo(ultimo_envio)

        if not resultado.detenido_por:
            resultado.omitidos = max(0, len(self.pendientes) - resultado.enviados - resultado.fallidos)
        return resultado

    # ------------------------------------------------------------- internos

    def _quedan_pendientes(self, actual) -> bool:
        return any(p is not actual for p in self.pendientes)

    def _esperar_reanudacion(self) -> None:
        while self.pausado and not self.cancelado:
            self.dormir(0.2)

    def _esperar_intervalo(self, ultimo_envio: float) -> None:
        """Espera el intervalo desde el envío anterior, con jitter que **solo alarga**.

        El jitter negativo haría que dos envíos consecutivos puedan estar más cerca que el
        intervalo configurado; alargando, la separación mínima se respeta siempre y el patrón
        mecánico (exactamente N segundos) también se rompe.
        """
        if self.intervalo <= 0:
            return
        extra = self.intervalo * self.azar(0, self.jitter)
        restante = self.intervalo - (self.reloj() - ultimo_envio)
        self.dormir(max(0, restante) + extra)

    def _enviar_con_reintentos(self, pendiente):
        """Manda un destinatario, con reintentos solo para errores transitorios.

        La fila de auditoría se crea **una vez**: los reintentos actualizan esa misma fila, así
        que el ``external_ref`` (único en la base) no se duplica.
        """
        envio = self._crear_envio(pendiente)
        intentos = 0
        while True:
            try:
                enviado = self.envios.send_pdf(
                    envio=envio,
                    pdf_path=self.pdf_path,
                    poll_attempts=1,
                    poll_interval=0,
                )
                return enviado, None
            except Exception as exc:  # noqa: BLE001 - el error se decide abajo
                if es_rate_limit(exc):
                    return None, exc
                if intentos < self.max_reintentos and es_transitorio(exc):
                    intentos += 1
                    self.dormir(2 ** intentos)
                    continue
                return None, exc

    def _crear_envio(self, pendiente) -> WhatsAppEnvio:
        """La fila de auditoría, con el número **ya normalizado** del clasificador.

        Si la fila ya existe (reintento o "reintentar fallidos"), se reutiliza: el
        ``external_ref`` es único y tiene que seguir siendo el mismo.
        """
        referencia = external_ref(self.clave, pendiente.client_id)
        envio = WhatsAppEnvio.get_or_none(WhatsAppEnvio.external_ref == referencia)
        if envio is not None:
            envio.estado = "preparing"
            envio.error = None
            envio.message_id = None
            envio.save()
            return envio
        return WhatsAppEnvio.create(
            tipo_documento=TIPO_DOCUMENTO,
            documento_id=self.clave,
            destinatario=pendiente.telefono,
            instance_id=self.instance_id,
            external_ref=referencia,
            caption=pendiente.caption or None,
            nombre_archivo=self.pdf_path.name,
            mime_type="application/pdf",
            estado="preparing",
            usuario=self.usuario,
            # ``created_at`` explícito en UTC naive: es como queda guardado en MySQL, y es lo que
            # permite contar los mensajes del día para el tope.
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

    def _emitir(self, tipo: str, pendiente: Pendiente | None = None, detalle: str = "") -> None:
        if self.al_evento is None:
            return
        self.al_evento(
            Evento(
                tipo=tipo,
                client_id=pendiente.client_id if pendiente else 0,
                nombre=pendiente.nombre if pendiente else "",
                detalle=detalle,
            )
        )
