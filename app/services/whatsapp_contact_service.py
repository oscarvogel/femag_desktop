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

from dataclasses import dataclass, field

from app.models.masters import Client, Salesperson
from app.services.audit_service import AuditService
from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_INVALIDO,
    ESTADO_POSIBLE,
    ESTADO_VACIO,
    clasificar_telefono,
)

#: Los estados del telefono, en el orden en que se los muestra al operador.
ESTADOS_DE_TELEFONO = (ESTADO_CELULAR, ESTADO_POSIBLE, ESTADO_INVALIDO, ESTADO_VACIO)

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


@dataclass(frozen=True)
class BackfillInforme:
    """Que copio el backfill y que dejo sin destino (#923).

    ``omitidos`` es una lista de ``(tipo, nombre, motivo)``. El motivo lleva
    el estado del telefono adelante ("posible: ..."), asi el resumen puede
    agrupar por estado sin volver a clasificar.

    ``omitidos_por_estado`` cuenta los omitidos por tipo de contacto y por
    estado del telefono: ``{"cliente": {"posible": 3, ...}, ...}``.
    """

    copiados_clientes: int = 0
    copiados_vendedores: int = 0
    copiados_clientes_inactivos: int = 0
    omitidos: list = field(default_factory=list)
    omitidos_por_estado: dict = field(default_factory=dict)


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

        Con ``solo_con_orden`` prendido solo entran los clientes con una orden
        que **salio** (emitida o cerrada): una orden en borrador todavia no
        salio, asi que no cuenta como movimiento.
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
        ultima_orden_por_cliente = self._ultimas_ordenes(solo_emitidas=solo_con_orden)
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

    def backfill(
        self, *, usuario: str | None = None, aplicar: bool = True
    ) -> BackfillInforme:
        """Copia al campo nuevo los celulares que ya estan cargados (#923).

        Solo copia lo que el clasificador da como **celular**: un numero dudoso
        se deja vacio a proposito, para que el operador lo confirme.

        Es idempotente: no pisa un WhatsApp ya cargado, asi que la segunda
        corrida copia 0.

        Se copian **todos** los clientes, tambien los inactivos: la copia es un
        hecho sobre el telefono, no sobre la actividad del cliente. Si manana
        el cliente se reactiva, ya tiene el numero cargado.

        Con ``aplicar=False`` no se escribe nada: el recorrido es el mismo y el
        informe dice que se copiaria. Eso es lo que usa la vista previa del
        script.

        El ``usuario`` pisa el usuario de auditoria del servicio (si viene
        ``None`` se usa ``self.current_user``): el backfill corre desde la
        terminal, donde no hay nadie logueado.
        """
        servicio = self
        if usuario and usuario.strip():
            servicio = WhatsAppContactService(
                usuario.strip(), audit_service=self.audit_service
            )

        omitidos: list[tuple[str, str, str]] = []
        por_estado: dict[str, dict[str, int]] = {
            "cliente": {estado: 0 for estado in ESTADOS_DE_TELEFONO},
            "vendedor": {estado: 0 for estado in ESTADOS_DE_TELEFONO},
        }

        copiados_clientes = 0
        copiados_clientes_inactivos = 0
        for cliente in Client.select().where(self._sin_whatsapp(Client)):
            clasificacion = clasificar_telefono(cliente.phone)
            if clasificacion.estado != ESTADO_CELULAR:
                omitidos.append(("cliente", cliente.name, self._motivo(clasificacion)))
                por_estado["cliente"][clasificacion.estado] += 1
                continue
            if aplicar:
                servicio.set_client_whatsapp_phone(cliente, cliente.phone)
            copiados_clientes += 1
            if not cliente.active:
                copiados_clientes_inactivos += 1

        copiados_vendedores = 0
        for vendedor in Salesperson.select().where(self._sin_whatsapp(Salesperson)):
            clasificacion = clasificar_telefono(vendedor.phone)
            if clasificacion.estado != ESTADO_CELULAR:
                omitidos.append(("vendedor", vendedor.name, self._motivo(clasificacion)))
                por_estado["vendedor"][clasificacion.estado] += 1
                continue
            if aplicar:
                servicio.set_salesperson_whatsapp_phone(vendedor, vendedor.phone)
            copiados_vendedores += 1

        return BackfillInforme(
            copiados_clientes=copiados_clientes,
            copiados_vendedores=copiados_vendedores,
            copiados_clientes_inactivos=copiados_clientes_inactivos,
            omitidos=omitidos,
            omitidos_por_estado=por_estado,
        )

    @staticmethod
    def _sin_whatsapp(modelo):
        """Los contactos que todavia no tienen WhatsApp: vacio o NULL (#923).

        Un campo vacio es lo mismo que un campo sin cargar: los dos se
        completan. Es el mismo criterio que usa la pantalla de pendientes.
        """
        return (modelo.whatsapp_phone.is_null(True)) | (modelo.whatsapp_phone == "")

    @staticmethod
    def _motivo(clasificacion) -> str:
        """El motivo con el estado adelante: "posible: ..." (#923).

        Asi el resumen puede agrupar los omitidos por estado sin tener que
        volver a clasificar los telefonos.
        """
        return f"{clasificacion.estado}: {clasificacion.motivo}".strip()

    @staticmethod
    def _ultimas_ordenes(*, solo_emitidas: bool = True) -> dict[int, str]:
        """La fecha de la ultima orden de cada cliente.

        En la app real el cliente de una orden vive en ``LoadOrderDestination``:
        las ordenes se crean con ``client=None`` y cada destino es un cliente de
        la orden (``app/services/load_order_service.py:79-91`` y ``:1354``).
        Por eso un cliente "tiene orden" si es **destino** de alguna orden o,
        en el camino legacy, si es el cliente de la orden: el mismo criterio
        que usa ``LoadOrderService.list_orders``.

        El agregado se hace en SQL (``GROUP BY`` + ``MAX(date)``): la base real
        crece y la pantalla no puede recorrer todas las ordenes en memoria.

        Con ``solo_emitidas`` solo cuentan las ordenes que salieron (emitida o
        cerrada). Si se pide la lista completa, cuentan tambien las que estan
        en borrador; las anuladas no cuentan nunca.
        """
        from peewee import fn

        from app.models.load_orders import LoadOrder, LoadOrderDestination

        if solo_emitidas:
            estados = (LoadOrder.STATUS_ISSUED, LoadOrder.STATUS_CLOSED)
        else:
            estados = (*LoadOrder.ACTIVE_STATUSES, LoadOrder.STATUS_CLOSED)

        ultimas: dict[int, str] = {}
        por_destino = (
            LoadOrderDestination.select(
                LoadOrderDestination.client,
                fn.MAX(LoadOrder.date),
            )
            .join(LoadOrder, on=(LoadOrderDestination.order == LoadOrder.id))
            .where(LoadOrder.status.in_(estados))
            .group_by(LoadOrderDestination.client)
            .tuples()
        )
        for cliente_id, fecha in por_destino:
            ultimas[cliente_id] = str(fecha)
        # Camino legacy: el cliente de la orden. En la base real esta siempre
        # en NULL, pero no se tira.
        por_cliente = (
            LoadOrder.select(LoadOrder.client, fn.MAX(LoadOrder.date))
            .where(LoadOrder.status.in_(estados), LoadOrder.client.is_null(False))
            .group_by(LoadOrder.client)
            .tuples()
        )
        for cliente_id, fecha in por_cliente:
            valor = str(fecha)
            if valor > ultimas.get(cliente_id, ""):
                ultimas[cliente_id] = valor
        return ultimas
