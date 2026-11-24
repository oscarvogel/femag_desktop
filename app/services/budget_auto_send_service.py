"""Envio automatico de los presupuestos de una orden emitida (#706).

El envio corre **fuera** de la transaccion de emision: un problema de contacto,
de configuracion o del gateway no puede dejar la orden sin emitir ni bloquear
los demas envios. Cada documento y cada canal se resuelve por separado y el
resultado queda registrado.

Reglas decididas en el issue:

- un solo destinatario por presupuesto: el vendedor si el cliente tiene uno;
  si no, el cliente. Es el mismo destinatario para WhatsApp y correo;
- el destino de WhatsApp sale del resolver de #923 (``whatsapp_phone`` y su
  respaldo controlado por el flag ``FEMAG_WHATSAPP_DEDICADO``);
- si falta el contacto, el envio se **omite** con el motivo: no se adivina un
  numero ni se cae a la linea fija;
- un reintento no vuelve a mandar lo que ya salio: WhatsApp se controla por
  ``whatsapp_envios`` y el correo por una marca de auditoria;
- el envio automatico esta **apagado por defecto** (``FEMAG_PRESUPUESTOS_AUTOENVIO``):
  hasta que el administrador lo habilite, emitir no manda nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models.audit import AuditLog
from app.models.budgets import Budget
from app.models.load_orders import LoadOrder
from app.models.security import User
from app.models.whatsapp import WhatsAppEnvio
from app.services.account_statement_mail_service import (
    AccountStatementMailError,
    MailConfigurationError,
    send_document,
)
from app.services.audit_service import AuditService
from app.services.budget_print_service import BudgetPrintService
from app.services.client_email_service import ClientEmailService
from app.services.whatsapp_contact_service import WhatsAppContactService
from app.services.whatsapp_envio_service import WhatsAppEnvioService

TIPO_DOCUMENTO = "presupuesto"

CANAL_WHATSAPP = "whatsapp"
CANAL_CORREO = "correo"

MODULO = "Presupuestos"
ACCION_WHATSAPP = "envio_automatico_whatsapp"
ACCION_CORREO = "envio_automatico_correo"
ACCION_CORREO_ENVIADO = "envio_automatico_correo_enviado"
ACCION_PDF = "generar_autoenvio"

DESTINATARIO_VENDEDOR = "vendedor"
DESTINATARIO_CLIENTE = "cliente"

ESTADO_ENVIADO = "enviado"
ESTADO_OMITIDO = "omitido"
ESTADO_FALLIDO = "fallido"

#: Estados en los que el gateway ya tomo el mensaje. Un reintento no lo repite.
#: ``failed`` queda afuera a proposito: el reintento es explicito.
ESTADOS_YA_ENVIADOS = frozenset({"queued", "accepted", "delivered", "read"})


def autoenvio_habilitado(override: bool | None = None) -> bool:
    """Si el envio automatico de presupuestos esta encendido (#706).

    La decision es **central** (``AppParameter``, pantalla ``Parametros``): no
    se configura puesto por puesto. El ``.env`` queda como respaldo para
    demo/tests. Apagado por defecto: el comportamiento de emitir una orden no
    cambia hasta que un administrador lo habilite.
    """
    if override is not None:
        return bool(override)
    from app.services.budget_auto_send_configuration_service import (
        BudgetAutoSendConfigurationService,
    )

    try:
        return BudgetAutoSendConfigurationService.habilitado()
    except Exception:  # noqa: BLE001 - sin config legible sigue el comportamiento de hoy
        return False


@dataclass(frozen=True)
class EnvioDocumento:
    """El resultado de un canal para un presupuesto."""

    budget_id: int
    budget_number: int
    cliente: str
    destinatario_tipo: str
    destinatario_nombre: str
    canal: str
    estado: str
    motivo: str = ""
    envio_id: int | None = None


@dataclass
class ResultadoAutoEnvio:
    """Como termino el envio automatico de una orden."""

    order_id: int
    order_number: int
    documentos: list[EnvioDocumento] = field(default_factory=list)

    @property
    def enviados(self) -> list[EnvioDocumento]:
        return [item for item in self.documentos if item.estado == ESTADO_ENVIADO]

    @property
    def omitidos(self) -> list[EnvioDocumento]:
        return [item for item in self.documentos if item.estado == ESTADO_OMITIDO]

    @property
    def fallidos(self) -> list[EnvioDocumento]:
        return [item for item in self.documentos if item.estado == ESTADO_FALLIDO]


class BudgetAutoSendService:
    """Manda los presupuestos de una orden emitida, sin bloquear la emision."""

    def __init__(
        self,
        current_user: str,
        *,
        prints_dir: str | Path = Path("outputs") / "load_orders",
        envios: WhatsAppEnvioService | None = None,
        contactos: WhatsAppContactService | None = None,
        mailer=None,
        smtp_settings=None,
        smtp_factory=None,
        audit_service: AuditService | None = None,
        preferir_dedicado: bool | None = None,
    ):
        self.current_user = current_user
        self.prints_dir = Path(prints_dir)
        self.envios = envios or WhatsAppEnvioService()
        self.contactos = contactos or WhatsAppContactService(
            current_user, audit_service=audit_service
        )
        self.mailer = mailer or send_document
        self.smtp_settings = smtp_settings
        self.smtp_factory = smtp_factory
        self.audit_service = audit_service or AuditService()
        self.preferir_dedicado = preferir_dedicado
        self._pdfs: dict[int, Path] = {}
        self._usuario = None

    # ------------------------------------------------------------------ API

    def dispatch_order(self, order: LoadOrder) -> ResultadoAutoEnvio:
        """Envia los presupuestos activos de la orden, uno por destinatario.

        No levanta excepciones por los envios: los problemas quedan en el
        resultado y en la auditoria. La emision de la orden ya termino.
        """
        order = LoadOrder.get_by_id(order.id)
        resultado = ResultadoAutoEnvio(
            order_id=order.id, order_number=order.order_number
        )
        presupuestos = (
            Budget.select()
            .where(
                (Budget.load_order == order)
                & (Budget.status == Budget.STATUS_ACTIVE)
            )
            .order_by(Budget.budget_number)
        )
        for budget in presupuestos:
            try:
                resultado.documentos.extend(self._dispatch_budget(budget))
            except Exception as exc:  # noqa: BLE001 - un documento no frena el resto
                resultado.documentos.append(
                    self._resultado(
                        budget,
                        DESTINATARIO_CLIENTE,
                        getattr(budget.client, "name", ""),
                        "",
                        ESTADO_FALLIDO,
                        str(exc),
                    )
                )
        return resultado

    # ------------------------------------------------------------- interno

    def _dispatch_budget(self, budget: Budget) -> list[EnvioDocumento]:
        tipo, contacto, nombre = self._destinatario(budget)
        return [
            self._enviar_whatsapp(budget, tipo, contacto, nombre),
            self._enviar_correo(budget, tipo, contacto, nombre),
        ]

    def _destinatario(self, budget: Budget):
        """El unico destinatario del presupuesto: vendedor, o cliente si no hay.

        Preferencia: el snapshot del presupuesto (``budget.salesperson``, #546);
        respaldo: el vendedor actual del cliente.
        """
        vendedor = budget.salesperson or budget.client.salesperson
        if vendedor is not None:
            return DESTINATARIO_VENDEDOR, vendedor, vendedor.name
        return DESTINATARIO_CLIENTE, budget.client, budget.client.name

    def _enviar_whatsapp(self, budget, tipo, contacto, nombre) -> EnvioDocumento:
        if self._whatsapp_ya_enviado(budget):
            return self._resultado(
                budget,
                tipo,
                nombre,
                CANAL_WHATSAPP,
                ESTADO_OMITIDO,
                "Ya se envio este presupuesto por WhatsApp.",
            )
        try:
            destino = self._destino(tipo, contacto)
        except ValueError as exc:
            return self._registrar(
                budget,
                tipo,
                nombre,
                CANAL_WHATSAPP,
                ESTADO_OMITIDO,
                str(exc),
            )

        try:
            pdf_path = self._pdf(budget)
            envio = self.envios.create_attempt(
                tipo_documento=TIPO_DOCUMENTO,
                documento_id=str(budget.id),
                destinatario=destino,
                caption=self._caption(budget, tipo, nombre),
                pdf_path=pdf_path,
                usuario=self.usuario,
            )
            self.envios.send_pdf(
                envio=envio,
                pdf_path=pdf_path,
                poll_attempts=1,
                poll_interval=0,
            )
        except Exception as exc:  # noqa: BLE001 - se informa y sigue el resto
            return self._registrar(
                budget,
                tipo,
                nombre,
                CANAL_WHATSAPP,
                ESTADO_FALLIDO,
                str(exc),
                destino=destino,
            )
        return self._registrar(
            budget,
            tipo,
            nombre,
            CANAL_WHATSAPP,
            ESTADO_ENVIADO,
            destino=destino,
            envio_id=getattr(envio, "id", None),
        )

    def _enviar_correo(self, budget, tipo, contacto, nombre) -> EnvioDocumento:
        direccion = self._email(tipo, contacto)
        if not direccion:
            return self._registrar(
                budget,
                tipo,
                nombre,
                CANAL_CORREO,
                ESTADO_OMITIDO,
                "El destinatario no tiene correo electronico cargado.",
            )
        if self._correo_ya_enviado(budget):
            return self._registrar(
                budget,
                tipo,
                nombre,
                CANAL_CORREO,
                ESTADO_OMITIDO,
                "Ya se envio este presupuesto por correo.",
                destino=direccion,
            )

        try:
            pdf_path = self._pdf(budget)
            kwargs = {
                "recipient": direccion,
                "pdf_path": pdf_path,
                "subject": self._asunto(budget),
                "body": self._cuerpo_correo(budget, tipo, nombre),
                "settings": self.smtp_settings,
            }
            if self.smtp_factory is not None:
                kwargs["smtp_factory"] = self.smtp_factory
            self.mailer(**kwargs)
        except MailConfigurationError as exc:
            return self._registrar(
                budget,
                tipo,
                nombre,
                CANAL_CORREO,
                ESTADO_OMITIDO,
                str(exc),
                destino=direccion,
            )
        except (AccountStatementMailError, ValueError, OSError) as exc:
            return self._registrar(
                budget,
                tipo,
                nombre,
                CANAL_CORREO,
                ESTADO_FALLIDO,
                str(exc),
                destino=direccion,
            )
        except Exception as exc:  # noqa: BLE001 - un correo no frena los demas
            return self._registrar(
                budget,
                tipo,
                nombre,
                CANAL_CORREO,
                ESTADO_FALLIDO,
                str(exc),
                destino=direccion,
            )

        self._auditar(
            budget,
            ACCION_CORREO_ENVIADO,
            {
                "canal": CANAL_CORREO,
                "destinatario": direccion,
                "tipo_destinatario": tipo,
                "estado": ESTADO_ENVIADO,
            },
        )
        return self._registrar(
            budget,
            tipo,
            nombre,
            CANAL_CORREO,
            ESTADO_ENVIADO,
            destino=direccion,
        )

    # ------------------------------------------------------------ auxiliares

    @property
    def usuario(self):
        if self._usuario is None and self.current_user:
            self._usuario = User.get_or_none(
                User.username == self.current_user
            )
        return self._usuario

    def _destino(self, tipo, contacto) -> str:
        if tipo == DESTINATARIO_VENDEDOR:
            return self.contactos.destino_vendedor(
                contacto, preferir_dedicado=self.preferir_dedicado
            )
        return self.contactos.destino_cliente(
            contacto, preferir_dedicado=self.preferir_dedicado
        )

    @staticmethod
    def _email(tipo, contacto) -> str:
        if tipo == DESTINATARIO_VENDEDOR:
            return (getattr(contacto, "email", None) or "").strip()
        activos = ClientEmailService.active_for_client(contacto)
        for email in activos:
            if email.email:
                return email.email.strip()
        return (getattr(contacto, "email", None) or "").strip()

    def _pdf(self, budget: Budget) -> Path:
        if budget.id not in self._pdfs:
            self._pdfs[budget.id] = BudgetPrintService(
                current_user=self.current_user,
                audit_service=self.audit_service,
            ).export_pdf(
                budget,
                self.prints_dir,
                audit_action=ACCION_PDF,
            )
        return self._pdfs[budget.id]

    @staticmethod
    def _caption(budget: Budget, tipo: str, nombre: str) -> str:
        if tipo == DESTINATARIO_VENDEDOR:
            return (
                f"Hola {nombre}. Le enviamos adjunto el presupuesto "
                f"{budget.display_number} de {budget.client.name} de FEMAG con el "
                "detalle correspondiente. Ante cualquier consulta, quedamos a "
                "disposicion."
            )
        return (
            f"Hola {nombre}. Le enviamos adjunto el presupuesto "
            f"{budget.display_number} de FEMAG con el detalle correspondiente. "
            "Ante cualquier consulta, quedamos a disposicion."
        )

    @staticmethod
    def _asunto(budget: Budget) -> str:
        return f"Presupuesto {budget.display_number} - {budget.client.name}"

    def _cuerpo_correo(self, budget: Budget, tipo: str, nombre: str) -> str:
        return (
            self._caption(budget, tipo, nombre)
            + "\n\nSaludos.\nGRAEF HERMANOS S.R.L."
        )

    def _whatsapp_ya_enviado(self, budget: Budget) -> bool:
        return (
            WhatsAppEnvio.select()
            .where(
                (WhatsAppEnvio.tipo_documento == TIPO_DOCUMENTO)
                & (WhatsAppEnvio.documento_id == str(budget.id))
                & (WhatsAppEnvio.estado.in_(tuple(ESTADOS_YA_ENVIADOS)))
            )
            .exists()
        )

    def _correo_ya_enviado(self, budget: Budget) -> bool:
        return (
            AuditLog.select()
            .where(
                (AuditLog.module == MODULO)
                & (AuditLog.action == ACCION_CORREO_ENVIADO)
                & (AuditLog.record_ref == f"Budget:{budget.id}")
            )
            .exists()
        )

    def _resultado(
        self,
        budget: Budget,
        tipo: str,
        nombre: str,
        canal: str,
        estado: str,
        motivo: str = "",
        *,
        envio_id: int | None = None,
    ) -> EnvioDocumento:
        return EnvioDocumento(
            budget_id=budget.id,
            budget_number=budget.budget_number,
            cliente=getattr(budget.client, "name", ""),
            destinatario_tipo=tipo,
            destinatario_nombre=nombre,
            canal=canal,
            estado=estado,
            motivo=motivo,
            envio_id=envio_id,
        )

    def _registrar(
        self,
        budget: Budget,
        tipo: str,
        nombre: str,
        canal: str,
        estado: str,
        motivo: str = "",
        *,
        destino: str = "",
        envio_id: int | None = None,
    ) -> EnvioDocumento:
        accion = ACCION_WHATSAPP if canal == CANAL_WHATSAPP else ACCION_CORREO
        self._auditar(
            budget,
            accion,
            {
                "canal": canal,
                "destinatario": destino,
                "tipo_destinatario": tipo,
                "destinatario_nombre": nombre,
                "estado": estado,
                "motivo": motivo,
                "envio_id": envio_id,
            },
        )
        return self._resultado(
            budget,
            tipo,
            nombre,
            canal,
            estado,
            motivo,
            envio_id=envio_id,
        )

    def _auditar(self, budget: Budget, accion: str, detalle: dict) -> None:
        try:
            self.audit_service.record(
                user=self.current_user,
                module=MODULO,
                action=accion,
                record_ref=f"Budget:{budget.id}",
                new_value=detalle,
            )
        except Exception:  # noqa: BLE001 - la auditoria no puede voltear el envio
            pass
