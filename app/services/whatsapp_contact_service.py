"""Guarda y audita el numero de WhatsApp de clientes y vendedores (#923).

El campo ``whatsapp_phone`` tiene un solo proposito: el numero al que se le
puede mandar WhatsApp. Por eso la validacion es **estricta**: solo entra un
celular sin ambiguedad. Un local de 10 u 11 digitos puede ser una linea fija
o un celular escrito sin el "15", y no se guarda porque el dia que sea fijo
el presupuesto se va a una linea fija.

El ``phone`` del contacto no se toca: ese campo sigue siendo el telefono
general y puede guardar un segundo numero.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.masters import Client, Salesperson
from app.services.audit_service import AuditService
from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_INVALIDO,
    ESTADO_POSIBLE,
    clasificar_telefono,
)

#: Que hacer segun el estado del numero. El consejo tiene que corresponder al
#: motivo: cargar el "15" no arregla un campo con dos telefonos, y un
#: internacional sin el 9 no se arregla volviendo a cargarlo como estaba.
CONSEJO_POR_ESTADO = {
    ESTADO_POSIBLE: "Cargue el celular con el 15 o en formato internacional con el 9.",
    ESTADO_INVALIDO: "Revise el numero y cargue un solo numero.",
}


@dataclass(frozen=True)
class ClientePendiente:
    """Un cliente al que todavia no se le puede mandar nada por WhatsApp."""

    client_id: int
    nombre: str
    vendedor: str
    telefono: str
    whatsapp_phone: str
    estado_telefono: str
    ultima_orden: str


class WhatsAppContactService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    @staticmethod
    def normalizar(numero: str) -> str:
        """Devuelve el numero en formato internacional, o explica por que no sirve.

        Un numero vacio no es un error: es "borrar el WhatsApp". Un ``None`` si
        lo es: es un error de quien lo llama, y borraria un numero que estaba
        cargado.
        """
        if numero is None:
            raise ValueError(
                "No se puede guardar un WhatsApp vacio: se paso None. "
                "Pase un numero o una cadena vacia para borrarlo."
            )
        texto = str(numero).strip()
        if not texto:
            return ""
        clasificacion = clasificar_telefono(texto)
        if clasificacion.estado != ESTADO_CELULAR:
            mensaje = f"Ese numero no se puede usar para WhatsApp: {clasificacion.motivo}."
            consejo = CONSEJO_POR_ESTADO.get(clasificacion.estado, "")
            if consejo:
                mensaje = f"{mensaje} {consejo}"
            raise ValueError(mensaje)
        return clasificacion.normalizado

    def set_client_whatsapp_phone(self, client: Client, numero: str) -> Client:
        normalizado = self.normalizar(numero)
        # La comparacion es contra el valor guardado **sin limpiar**: si en la
        # base quedo un numero con espacios, hay que corregirlo y auditarlo.
        anterior = client.whatsapp_phone or ""
        if anterior == normalizado:
            return client
        client.whatsapp_phone = normalizado or None
        client.save(only=[Client.whatsapp_phone, Client.updated_at])
        self.audit_service.record(
            user=self.current_user,
            module="Clientes",
            action="actualizar WhatsApp",
            record_ref=f"Client:{client.id}",
            old_value={"whatsapp_phone": anterior or None},
            new_value={"whatsapp_phone": normalizado or None},
        )
        return client

    def set_salesperson_whatsapp_phone(
        self, salesperson: Salesperson, numero: str
    ) -> Salesperson:
        normalizado = self.normalizar(numero)
        anterior = salesperson.whatsapp_phone or ""
        if anterior == normalizado:
            return salesperson
        salesperson.whatsapp_phone = normalizado or None
        salesperson.save(only=[Salesperson.whatsapp_phone, Salesperson.updated_at])
        self.audit_service.record(
            user=self.current_user,
            module="Vendedores",
            action="actualizar WhatsApp",
            record_ref=f"Salesperson:{salesperson.id}",
            old_value={"whatsapp_phone": anterior or None},
            new_value={"whatsapp_phone": normalizado or None},
        )
        return salesperson

    def listar_clientes_pendientes(
        self, *, solo_con_orden: bool = True
    ) -> list[ClientePendiente]:
        """Clientes sin WhatsApp cargado, ordenados por la ultima orden.

        Vienen primero los que mas duelen: los que tienen movimiento reciente.
        """
        consulta = (
            Client.select()
            .where(
                (Client.active == True)  # noqa: E712 - el filtro es explicito
                & (
                    (Client.whatsapp_phone.is_null(True))
                    | (Client.whatsapp_phone == "")
                )
            )
            .order_by(Client.name)
        )
        ultima_orden_por_cliente = self._ultimas_ordenes()
        nombre_por_vendedor = {
            vendedor.id: vendedor.name
            for vendedor in Salesperson.select(Salesperson.id, Salesperson.name)
        }
        pendientes = []
        for cliente in consulta:
            ultima_orden = ultima_orden_por_cliente.get(cliente.id, "")
            if solo_con_orden and not ultima_orden:
                continue
            clasificacion = clasificar_telefono(cliente.phone)
            pendientes.append(
                ClientePendiente(
                    client_id=cliente.id,
                    nombre=cliente.name,
                    vendedor=nombre_por_vendedor.get(cliente.salesperson_id, ""),
                    telefono=cliente.phone or "",
                    whatsapp_phone=cliente.whatsapp_phone or "",
                    estado_telefono=clasificacion.estado,
                    ultima_orden=ultima_orden,
                )
            )
        # Los que no tienen orden van al final: no son los que mas duelen.
        pendientes.sort(
            key=lambda pendiente: (
                pendiente.ultima_orden == "",
                pendiente.ultima_orden,
            ),
            reverse=True,
        )
        return pendientes

    @staticmethod
    def _ultimas_ordenes() -> dict[int, str]:
        """La fecha de la ultima orden vigente de cada cliente.

        Es una sola consulta para toda la pantalla: la carga se hace sobre la
        base real, donde hay miles de clientes y miles de ordenes.
        """
        from app.models.load_orders import LoadOrder

        ultimas: dict[int, str] = {}
        consulta = (
            LoadOrder.select(LoadOrder.client, LoadOrder.date)
            .where(LoadOrder.status != LoadOrder.STATUS_ANNULLED)
            .order_by(LoadOrder.date.desc(), LoadOrder.id.desc())
        )
        for cliente_id, fecha in consulta.tuples():
            if cliente_id is None or cliente_id in ultimas:
                continue
            ultimas[cliente_id] = str(fecha)
        return ultimas
