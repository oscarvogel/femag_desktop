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
