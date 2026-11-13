# #923 — Número de WhatsApp dedicado: plan de implementación

> **Para agentes que ejecutan este plan:** sub-skill REQUERIDA: usar `superpowers:subagent-driven-development` (recomendado) o `superpowers:executing-plans` para ejecutar este plan tarea por tarea. Los pasos usan casillas (`- [ ]`) para el seguimiento.

**Objetivo:** que clientes y vendedores tengan un número de WhatsApp verificado en un campo propio (`whatsapp_phone`), con `phone` libre para otros teléfonos, y que los envíos usen ese campo (preferido) sin dejar de funcionar con los números de hoy.

**Arquitectura:** tres piezas nuevas y separadas. (1) Un módulo **puro** `whatsapp_contact_resolver.py` que decide *qué número* es válido, sin tocar la base ni la interfaz. (2) Un **servicio** `whatsapp_contact_service.py` que guarda el número con validación estricta, audita, y expone los destinos que usan los envíos. (3) La **interfaz**: un diálogo de edición rápida en la grilla de Clientes, el campo en el alta/edición de Vendedores, y una pantalla de carga de los pendientes. La preferencia por el campo nuevo está **apagada por defecto** (`FEMAG_WHATSAPP_DEDICADO`): con el flag apagado el comportamiento es idéntico al de hoy.

**Stack:** Python 3.12, peewee (SQLite en tests, MySQL/MariaDB en producción), PyQt5, pytest.

## Restricciones globales

- **No se toca el esquema al arrancar.** La columna la aplica un administrador por `ensure_runtime_schema` (`app/config/schema.py`); la app solo la usa si existe. `FemagMySQLDatabase.connect()` migra únicamente con `FEMAG_AUTO_MIGRATE_SCHEMA=1`.
- **`phone` no se borra ni cambia de significado.** El campo nuevo es adicional.
- **Solo se acepta un número `celular`.** Un "posible" (línea fija o celular sin el "15") se rechaza al guardar; un inválido también.
- **El número se guarda normalizado** en formato internacional (`549...`), que es el que entiende el gateway.
- **El flag `FEMAG_WHATSAPP_DEDICADO` arranca apagado** (default `0`). Con el flag apagado, los envíos se comportan **exactamente** como hoy, incluidos los mensajes de error.
- **No se pierde la trazabilidad**: todo cambio de número se audita.
- **No se inventa nada**: el resolver nunca convierte un número, nunca le agrega el "15" a un fijo y nunca adivina.
- **Pantallas**: todo debe verse bien a **1638x969** y a **1366x768**.
- **Textos de la interfaz en español rioplatense**, sin tildes en el código (convención del repo).
- **Validación mínima antes de cerrar el PR** (de `AGENTS.md`):
  ```bash
  git diff --check
  python -m pytest
  python -m compileall app
  python -m app.main --smoke
  ```

---

### Tarea 1: El campo `whatsapp_phone` en Cliente y Vendedor

**Archivos:**
- Modificar: `app/models/masters.py:93-99` (`Salesperson`), `app/models/masters.py:101-133` (`Client`)
- Test: `tests/test_issue_923_whatsapp_dedicated.py` (nuevo)

**Interfaces:**
- Produce: `Client.whatsapp_phone: str | None` y `Salesperson.whatsapp_phone: str | None`, ambos `CharField(null=True)` sin default (o sea `None`).

- [ ] **Paso 1: escribir el test que falla**

Crear `tests/test_issue_923_whatsapp_dedicated.py`:

```python
"""Numero de WhatsApp dedicado para clientes y vendedores (#923)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_cliente_tiene_campo_whatsapp_phone(db):
    from app.models.masters import Client

    cliente = Client.create(name="Cliente 923", cuit="30923000001", iva_condition="RI")
    assert cliente.whatsapp_phone is None


def test_vendedor_tiene_campo_whatsapp_phone(db):
    from app.models.masters import Salesperson

    vendedor = Salesperson.create(name="Vendedor 923")
    assert vendedor.whatsapp_phone is None


def test_el_esquema_existente_gana_la_columna(db):
    """La columna tiene que aparecer sola en una base que ya existe (#923)."""
    from app.config.schema import ensure_runtime_schema
    from app.config.database import bind_database
    from peewee import SqliteDatabase, CharField
    from app.models.base import BaseModel

    class TablaVieja(BaseModel):
        name = CharField(null=True)

        class Meta:
            table_name = "tabla_vieja_923"

    base = SqliteDatabase(":memory:")
    bind_database(base)
    base.connect(reuse_if_open=True)
    base.create_tables([TablaVieja])
    assert "whatsapp_phone" not in {
        columna.name for columna in base.get_columns("tabla_vieja_923")
    }
    # ensure_runtime_schema crea lo que falta en TODOS los modelos declarados.
    ensure_runtime_schema(base)
    assert "whatsapp_phone" in {
        columna.name for columna in base.get_columns("client")
    }
    assert "whatsapp_phone" in {
        columna.name for columna in base.get_columns("salesperson")
    }
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL con `AttributeError: 'Client' object has no attribute 'whatsapp_phone'`.

- [ ] **Paso 3: implementación mínima**

En `app/models/masters.py`, en `Salesperson` (después de `phone`) y en `Client` (después de `phone`):

```python
    # Numero de WhatsApp verificado (#923). Es distinto de ``phone``:
    # ``phone`` guarda el telefono general (puede ser fijo o un segundo
    # celular) y este guarda el numero al que se le puede mandar WhatsApp.
    whatsapp_phone = CharField(null=True)
```

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: 3 passed.

- [ ] **Paso 5: commit**

```bash
git add app/models/masters.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): campo whatsapp_phone en cliente y vendedor"
```

---

### Tarea 2: El módulo resolver (qué número es válido)

**Archivos:**
- Crear: `app/services/whatsapp_contact_resolver.py`
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Consume: `app.services.whatsapp_phone_classifier.clasificar_telefono(texto) -> PhoneClassification` (ya existe; estados `celular`, `posible`, `invalido`, `vacio`; atributos `es_celular`, `normalizado`, `motivo`).
- Produce:
  ```python
  ORIGEN_DEDICADO = "whatsapp_phone"
  ORIGEN_TELEFONO = "phone"
  ORIGEN_NINGUNO = ""

  @dataclass(frozen=True)
  class WhatsAppContact:
      numero: str      # normalizado, o "" si no hay destino
      origen: str      # ORIGEN_DEDICADO | ORIGEN_TELEFONO | ORIGEN_NINGUNO
      estado: str      # estado del clasificador
      motivo: str      # por qué no es enviable ("" si es enviable)
      mensaje: str     # texto de error para el operador ("" si es enviable)

      @property
      def enviable(self) -> bool: ...

  def resolver_contacto(*, whatsapp_phone=None, phone=None, preferir_dedicado=True) -> WhatsAppContact: ...
  ```

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
# ------------------------------------------------------------------ resolver


def test_el_whatsapp_dedicado_manda_sobre_el_telefono():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_DEDICADO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="+5491153088679", phone="011 4441-2835"
    )
    assert contacto.enviable
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_DEDICADO


def test_sin_whatsapp_dedicado_cae_al_telefono_si_es_celular():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_TELEFONO,
        resolver_contacto,
    )

    contacto = resolver_contacto(whatsapp_phone="", phone="011 15 53088679")
    assert contacto.enviable
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_TELEFONO


def test_un_telefono_dudoso_no_es_destino():
    from app.services.whatsapp_contact_resolver import resolver_contacto

    contacto = resolver_contacto(whatsapp_phone="", phone="011 4441-2835")
    assert not contacto.enviable
    assert contacto.numero == ""
    assert "dudoso" in contacto.mensaje


def test_un_whatsapp_cargado_que_no_es_celular_no_cae_al_telefono():
    """Si el operador cargó un WhatsApp roto, no se manda a otro numero."""
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_DEDICADO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="011 4441-2835", phone="011 15 53088679"
    )
    assert not contacto.enviable
    assert contacto.origen == ORIGEN_DEDICADO


def test_sin_telefono_no_hay_destino():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_NINGUNO,
        resolver_contacto,
    )

    contacto = resolver_contacto(whatsapp_phone="", phone="")
    assert not contacto.enviable
    assert contacto.origen == ORIGEN_NINGUNO


def test_con_el_flag_apagado_se_ignora_el_campo_nuevo():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_TELEFONO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="+5491153088679",
        phone="011 15 53088679",
        preferir_dedicado=False,
    )
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_TELEFONO


def test_el_mensaje_es_el_mismo_que_el_de_hoy():
    """El texto de error no cambia: el operador ve lo mismo que siempre."""
    from app.services.account_statement_share_service import normalize_whatsapp_phone
    from app.services.whatsapp_contact_resolver import resolver_contacto

    for numero in ("011 4441-2835", "01148975105//01157357632", ""):
        try:
            normalize_whatsapp_phone(numero)
            esperado = None
        except ValueError as exc:
            esperado = str(exc)
        contacto = resolver_contacto(whatsapp_phone="", phone=numero)
        assert contacto.mensaje == esperado
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.whatsapp_contact_resolver'`.

- [ ] **Paso 3: implementación mínima**

Crear `app/services/whatsapp_contact_resolver.py`:

```python
"""Decide que numero de WhatsApp es el destino valido de un contacto (#923).

Es un modulo **puro**: no toca la base ni la interfaz, para poder testearlo
entero y para que la regla viva en un solo lugar.

La regla:

- Si el contacto tiene ``whatsapp_phone`` cargado, ese manda.
- Si no, se cae a ``phone``, pero **solo si** ``phone`` es un celular sin
  ambiguedad: un local de 10 u 11 digitos puede ser una linea fija o un
  celular escrito sin el "15", y mandarle ahi es adivinar.
- Si el ``whatsapp_phone`` cargado no es un celular, **no** se cae al
  telefono: el operador lo cargo a proposito, y mandar a otro numero seria
  mandar a un destinatario que nadie eligio.

Nunca convierte, nunca le agrega el "15" a un fijo, nunca inventa.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_VACIO,
    PhoneClassification,
    clasificar_telefono,
)

ORIGEN_DEDICADO = "whatsapp_phone"
ORIGEN_TELEFONO = "phone"
ORIGEN_NINGUNO = ""


@dataclass(frozen=True)
class WhatsAppContact:
    """El destino de WhatsApp de un contacto, con el motivo si no hay."""

    numero: str
    origen: str
    estado: str
    motivo: str
    mensaje: str

    @property
    def enviable(self) -> bool:
        return bool(self.numero)


def _mensaje_de_error(clasificacion: PhoneClassification) -> str:
    """El mismo texto que hoy usa ``normalize_whatsapp_phone`` (#759)."""
    if clasificacion.estado == ESTADO_VACIO:
        return "El cliente no tiene un telefono valido para WhatsApp."
    if clasificacion.estado == "posible":
        return (
            "El telefono es dudoso para WhatsApp: "
            f"{clasificacion.motivo}. Reviselo y confirme el numero antes de enviar."
        )
    return (
        f"El telefono no es valido para WhatsApp: {clasificacion.motivo}."
    )


def _contacto(clasificacion: PhoneClassification, origen: str) -> WhatsAppContact:
    if clasificacion.estado == ESTADO_CELULAR:
        return WhatsAppContact(
            numero=clasificacion.normalizado,
            origen=origen,
            estado=clasificacion.estado,
            motivo="",
            mensaje="",
        )
    return WhatsAppContact(
        numero="",
        origen=origen,
        estado=clasificacion.estado,
        motivo=clasificacion.motivo,
        mensaje=_mensaje_de_error(clasificacion),
    )


def resolver_contacto(
    *,
    whatsapp_phone=None,
    phone=None,
    preferir_dedicado: bool = True,
) -> WhatsAppContact:
    """Resuelve el destino de WhatsApp de un contacto.

    ``preferir_dedicado`` es el flag ``FEMAG_WHATSAPP_DEDICADO``: con el flag
    apagado (el default) el campo nuevo se ignora y el destino sale del
    telefono, como antes de este issue.
    """
    dedicado = (whatsapp_phone or "").strip()
    if preferir_dedicado and dedicado:
        return _contacto(clasificar_telefono(dedicado), ORIGEN_DEDICADO)
    telefono = (phone or "").strip()
    if not telefono:
        return _contacto(clasificar_telefono(""), ORIGEN_NINGUNO)
    return _contacto(clasificar_telefono(telefono), ORIGEN_TELEFONO)
```

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/services/whatsapp_contact_resolver.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): modulo resolver del destino de WhatsApp"
```

---

### Tarea 3: El servicio que guarda el número

**Archivos:**
- Crear: `app/services/whatsapp_contact_service.py`
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Consume: `clasificar_telefono(texto) -> PhoneClassification` de `app/services/whatsapp_phone_classifier.py` (misma fuente de verdad que el resolver), `ESTADO_CELULAR`, y `AuditService.record(user, module, action, record_ref, old_value, new_value)` de `app/services/audit_service.py`.
- **No** consume `resolver_contacto`: el resolver decide *a quién* se manda (leer `phone` o `whatsapp_phone`), y esa decisión se implementa en la Tarea 10, no acá. Este servicio **guarda, normaliza y audita**.
- Produce:
  ```python
  class WhatsAppContactService:
      def __init__(self, current_user: str, audit_service: AuditService | None = None)
      @staticmethod
      def normalizar(numero: str) -> str          # levanta ValueError si no es celular
      def set_client_whatsapp_phone(self, client, numero: str) -> Client
      def set_salesperson_whatsapp_phone(self, salesperson, numero: str) -> Salesperson
  ```

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
# ------------------------------------------------------------------ servicio


def _usuario(nombre="admin923"):
    from app.models.security import User, UserProfile

    perfil, _ = UserProfile.get_or_create(name="Administrador")
    return User.create(username=nombre, password_hash="x", profile=perfil, active=True)


def test_guarda_el_whatsapp_normalizado(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS", cuit="30923000002", iva_condition="RI")
    WhatsAppContactService("admin923").set_client_whatsapp_phone(
        cliente, "011 15 53088679"
    )
    assert cliente.whatsapp_phone == "5491153088679"


def test_no_toca_el_telefono(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente WS2", cuit="30923000003", iva_condition="RI", phone="011 4441-2835"
    )
    WhatsAppContactService("admin923").set_client_whatsapp_phone(
        cliente, "+5491153088679"
    )
    assert cliente.phone == "011 4441-2835"


def test_rechaza_un_telefono_dudoso(db):
    import pytest

    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS3", cuit="30923000004", iva_condition="RI")
    with pytest.raises(ValueError):
        WhatsAppContactService("admin923").set_client_whatsapp_phone(
            cliente, "011 4441-2835"
        )
    assert cliente.whatsapp_phone is None


def test_rechaza_un_numero_invalido(db):
    import pytest

    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS4", cuit="30923000005", iva_condition="RI")
    with pytest.raises(ValueError):
        WhatsAppContactService("admin923").set_client_whatsapp_phone(
            cliente, "01148975105//01157357632"
        )


def test_audita_el_cambio(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS5", cuit="30923000006", iva_condition="RI")
    WhatsAppContactService("admin923").set_client_whatsapp_phone(
        cliente, "+5491153088679"
    )
    registro = (
        AuditLog.select()
        .where(AuditLog.record_ref == f"Client:{cliente.id}")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert registro is not None
    assert registro.action == "actualizar WhatsApp"


def test_si_no_cambia_no_escribe_ni_audita(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS6", cuit="30923000007", iva_condition="RI")
    servicio = WhatsAppContactService("admin923")
    servicio.set_client_whatsapp_phone(cliente, "+5491153088679")
    antes = AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}").count()
    servicio.set_client_whatsapp_phone(cliente, "011 15 53088679")
    despues = AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}").count()
    assert antes == despues


def test_guarda_el_whatsapp_del_vendedor(db):
    from app.models.masters import Salesperson
    from app.services.whatsapp_contact_service import WhatsAppContactService

    vendedor = Salesperson.create(name="Vendedor WS", phone="2236800402")
    WhatsAppContactService("admin923").set_salesperson_whatsapp_phone(
        vendedor, "+5491153088679"
    )
    assert vendedor.whatsapp_phone == "5491153088679"
    assert vendedor.phone == "2236800402"


def test_un_numero_vacio_borra_el_whatsapp(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente WS7", cuit="30923000028", iva_condition="RI", whatsapp_phone="5491153088679"
    )
    WhatsAppContactService("admin923").set_client_whatsapp_phone(cliente, "")
    assert cliente.whatsapp_phone is None
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.whatsapp_contact_service'`.

- [ ] **Paso 3: implementación mínima**

Crear `app/services/whatsapp_contact_service.py`:

```python
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
from app.services.whatsapp_phone_classifier import ESTADO_CELULAR, clasificar_telefono


class WhatsAppContactService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    @staticmethod
    def normalizar(numero: str) -> str:
        """Devuelve el numero en formato internacional, o explica por que no sirve.

        Un numero vacio no es un error: es "borrar el WhatsApp".
        """
        texto = (numero or "").strip()
        if not texto:
            return ""
        clasificacion = clasificar_telefono(texto)
        if clasificacion.estado != ESTADO_CELULAR:
            raise ValueError(
                "Ese numero no se puede usar para WhatsApp: "
                f"{clasificacion.motivo}. Cargue el celular con el 15 o en formato internacional."
            )
        return clasificacion.normalizado

    def set_client_whatsapp_phone(self, client: Client, numero: str) -> Client:
        normalizado = self.normalizar(numero)
        anterior = (client.whatsapp_phone or "").strip()
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
        anterior = (salesperson.whatsapp_phone or "").strip()
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
```

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/services/whatsapp_contact_service.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): servicio que guarda y audita el WhatsApp del contacto"
```

---

### Tarea 4: El flag `FEMAG_WHATSAPP_DEDICADO`

**Archivos:**
- Modificar: `app/config/settings.py:12-30` (dataclass `Settings`) y `app/config/settings.py:113-130` (`load_settings`)
- Modificar: `.env.example`
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Produce: `Settings.whatsapp_contact_dedicado: bool` — `True` solo si `FEMAG_WHATSAPP_DEDICADO` está en `{"1", "true", "yes", "si", "sí", "on"}` (usa el `_flag_enabled` que ya existe en el archivo).

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
# -------------------------------------------------------------------- flag


def test_el_flag_esta_apagado_por_default(monkeypatch):
    from app.config.settings import load_settings

    monkeypatch.delenv("FEMAG_WHATSAPP_DEDICADO", raising=False)
    assert load_settings().whatsapp_contact_dedicado is False


def test_el_flag_se_enciende_con_la_variable(monkeypatch):
    from app.config.settings import load_settings

    monkeypatch.setenv("FEMAG_WHATSAPP_DEDICADO", "1")
    assert load_settings().whatsapp_contact_dedicado is True
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL con `AttributeError: 'Settings' object has no attribute 'whatsapp_contact_dedicado'`.

- [ ] **Paso 3: implementación mínima**

En `app/config/settings.py`, en el dataclass `Settings`, después de `whatsapp_api_timeout`:

```python
    whatsapp_contact_dedicado: bool = False
```

Y en `load_settings()`, junto a los otros valores de WhatsApp:

```python
        whatsapp_contact_dedicado=_flag_enabled(
            os.getenv("FEMAG_WHATSAPP_DEDICADO", "false")
        ),
```

En `.env.example`, agregar:

```
# Preferir el numero de WhatsApp dedicado (campo whatsapp_phone) sobre el
# telefono general. Apagado por defecto: lo activa el administrador cuando
# los numeros estan cargados.
FEMAG_WHATSAPP_DEDICADO=0
```

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/config/settings.py .env.example tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): flag FEMAG_WHATSAPP_DEDICADO, apagado por defecto"
```

---

### Tarea 5: El diálogo de edición del WhatsApp del cliente

**Archivos:**
- Crear: `app/ui/whatsapp_phone_edit_widgets.py` (helper compartido)
- Crear: `app/ui/client_whatsapp_edit_dialog.py`
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Consume: `WhatsAppContactService.set_client_whatsapp_phone`, `clasificar_telefono`, `FormFeedback` de `app/ui/form_feedback.py`.
- Produce:
  ```python
  # app/ui/whatsapp_phone_edit_widgets.py
  ESTILOS_CLASIFICACION = {estado: (color, fondo, borde)}
  class ClasificacionLabel(QLabel):
      def mostrar(self, clasificacion: PhoneClassification) -> None: ...
  class BotonPropuesta(QPushButton):
      def mostrar(self, clasificacion: PhoneClassification) -> None: ...
      def aplicar(self) -> str: ...   # devuelve la propuesta
  ```
  ```python
  # app/ui/client_whatsapp_edit_dialog.py
  class ClientWhatsappEditDialog(QDialog):
      def __init__(self, *, client, current_user: str, parent=None)
      def whatsapp(self) -> str
  ```

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
# ----------------------------------------------------------------- interfaz


def test_el_dialogo_guarda_el_whatsapp(db):
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(name="Cliente Dialogo", cuit="30923000008", iva_condition="RI")
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 15 53088679")
    dialogo._guardar()
    assert cliente.whatsapp_phone == "5491153088679"


def test_el_dialogo_no_guarda_un_numero_dudoso(db):
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(name="Cliente Dialogo2", cuit="30923000009", iva_condition="RI")
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 4441-2835")
    dialogo._guardar()
    assert cliente.whatsapp_phone is None


def test_el_dialogo_muestra_el_estado_de_la_clasificacion(db):
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(name="Cliente Dialogo3", cuit="30923000010", iva_condition="RI")
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 15 53088679")
    assert "Celular" in dialogo.classification_label.text()
    dialogo.whatsapp_input.setText("011 4441-2835")
    assert "Revisar" in dialogo.classification_label.text()
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL con `ModuleNotFoundError: No module named 'app.ui.client_whatsapp_edit_dialog'`.

- [ ] **Paso 3: implementación mínima**

Crear `app/ui/whatsapp_phone_edit_widgets.py`, moviendo el mapa de estilos y el comportamiento del botón "Usar el primer número" que ya están en `app/ui/client_phone_edit_dialog.py:31-34` y `:65-68`, para que los dos diálogos los compartan y no se dupliquen:

```python
"""Piezas compartidas por los dialogos de telefono y de WhatsApp (#923)."""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QPushButton

from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_POSIBLE,
    PhoneClassification,
)

ESTILOS_CLASIFICACION = {
    ESTADO_CELULAR: ("#166534", "#ecfdf3", "#4ade80"),
    ESTADO_POSIBLE: ("#92400e", "#fffbeb", "#f6c453"),
    "invalido": ("#991b1b", "#fef2f2", "#f87171"),
    "vacio": ("#374151", "#f3f4f6", "#d1d5db"),
}


class ClasificacionLabel(QLabel):
    """Muestra en vivo si el numero es un celular, dudoso o invalido."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)

    def mostrar(self, clasificacion: PhoneClassification) -> None:
        color, fondo, borde = ESTILOS_CLASIFICACION.get(
            clasificacion.estado, ESTILOS_CLASIFICACION["vacio"]
        )
        self.setText(clasificacion.detalle)
        self.setStyleSheet(
            f"QLabel {{"
            f"background-color: {fondo};"
            f"border: 1px solid {borde};"
            f"border-left: 4px solid {borde};"
            f"border-radius: 7px;"
            f"color: {color};"
            "font-size: 13px;"
            "font-weight: 600;"
            "padding: 9px 11px;"
            "}"
        )


class BotonPropuesta(QPushButton):
    """El boton que propone el numero a usar cuando el campo trae dos."""

    def __init__(self, parent=None):
        super().__init__("Usar el primer numero", parent)
        self.setVisible(False)

    def mostrar(self, clasificacion: PhoneClassification) -> None:
        self.setVisible(bool(clasificacion.propuesta))

    def aplicar(self, clasificacion: PhoneClassification) -> str:
        return clasificacion.propuesta
```

Crear `app/ui/client_whatsapp_edit_dialog.py`:

```python
"""Edicion rapida del numero de WhatsApp de un cliente (#923).

Es un dialogo chico con un solo campo, como el del telefono, pero **estricto**:
aqui solo se guarda un celular sin ambiguedad, porque el campo tiene un solo
proposito. Un numero dudoso se muestra, pero no se puede guardar.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services.whatsapp_contact_service import WhatsAppContactService
from app.services.whatsapp_phone_classifier import clasificar_telefono
from app.ui.form_feedback import FormFeedback
from app.ui.whatsapp_phone_edit_widgets import BotonPropuesta, ClasificacionLabel


class ClientWhatsappEditDialog(QDialog):
    """Cambia el numero de WhatsApp de un cliente y avisa como va a quedar."""

    def __init__(self, *, client, current_user: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"WhatsApp de {client.name}")
        self.setObjectName("clientWhatsappEditDialog")
        self.resize(480, 280)
        self.setMinimumSize(420, 260)

        self.client = client
        self.current_user = current_user

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Cliente: {client.name}"))

        self.whatsapp_input = QLineEdit(client.whatsapp_phone or "")
        self.whatsapp_input.setObjectName("clientWhatsappInput")
        self.whatsapp_input.setPlaceholderText("Ej.: 011 15 53088679")
        root.addWidget(self.whatsapp_input)

        self.classification_label = ClasificacionLabel()
        self.classification_label.setObjectName("clientWhatsappClassificationLabel")
        root.addWidget(self.classification_label)

        self.proposal_btn = BotonPropuesta()
        self.proposal_btn.setObjectName("clientWhatsappProposalButton")
        root.addWidget(self.proposal_btn)

        self.feedback = FormFeedback("clientWhatsappEditFeedback")
        root.addWidget(self.feedback)

        acciones = QHBoxLayout()
        acciones.addStretch(1)
        self.limpiar_btn = QPushButton("Borrar WhatsApp")
        self.limpiar_btn.setObjectName("clientWhatsappClearButton")
        self.cancelar_btn = QPushButton("Cancelar")
        self.cancelar_btn.setObjectName("clientWhatsappCancelButton")
        self.guardar_btn = QPushButton("Guardar")
        self.guardar_btn.setObjectName("clientWhatsappSaveButton")
        acciones.addWidget(self.limpiar_btn)
        acciones.addWidget(self.cancelar_btn)
        acciones.addWidget(self.guardar_btn)
        root.addLayout(acciones)

        self.whatsapp_input.textChanged.connect(self._reclasificar)
        self.proposal_btn.clicked.connect(self._usar_propuesta)
        self.limpiar_btn.clicked.connect(self._limpiar)
        self.cancelar_btn.clicked.connect(self.reject)
        self.guardar_btn.clicked.connect(self._guardar)
        self._reclasificar()

    def _reclasificar(self) -> None:
        clasificacion = clasificar_telefono(self.whatsapp_input.text())
        self.classification_label.mostrar(clasificacion)
        self.proposal_btn.mostrar(clasificacion)

    def _usar_propuesta(self) -> None:
        clasificacion = clasificar_telefono(self.whatsapp_input.text())
        if clasificacion.propuesta:
            self.whatsapp_input.setText(clasificacion.propuesta)

    def _limpiar(self) -> None:
        self.whatsapp_input.setText("")

    def _guardar(self) -> None:
        numero = self.whatsapp_input.text().strip()
        try:
            WhatsAppContactService(self.current_user).set_client_whatsapp_phone(
                self.client, numero
            )
        except ValueError as exc:
            self.feedback.show_warning(str(exc), focus_widget=self.whatsapp_input)
            return
        except Exception as exc:
            self.feedback.show_error(f"No se pudo guardar el WhatsApp: {exc}")
            return
        self.accept()

    def whatsapp(self) -> str:
        return self.whatsapp_input.text().strip()
```

> **Borrar:** un numero vacio no es un error: `normalizar` devuelve `""` y el servicio
> guarda `None` (se queda sin destino). Por eso el boton "Borrar WhatsApp" llama al mismo
> `_guardar` con el campo vacio, y no hace falta ningun camino especial.

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/ui/whatsapp_phone_edit_widgets.py app/ui/client_whatsapp_edit_dialog.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): dialogo de edicion rapida del WhatsApp del cliente"
```

---

### Tarea 6: Botón y columna en la grilla de Clientes

**Archivos:**
- Modificar: `app/ui/master_abm.py:456-465` (columnas de la config "clients"), `app/ui/master_abm.py:1927-1957` (`_client_rows`), `app/ui/master_abm.py:2157-2165` (botones), `app/ui/master_abm.py:2404-2424` (`edit_client_phone` y el nuevo `edit_client_whatsapp`), `app/ui/master_abm.py:2585-2590` (conexiones)
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Consume: `ClientWhatsappEditDialog` (Tarea 5), `WhatsAppContactService`.
- Produce: botón con objectName `editClientWhatsappButton`; columna "WhatsApp" en la grilla de Clientes (posición: después de "Vendedor").

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
def test_la_grilla_de_clientes_muestra_el_whatsapp(db):
    from app.models.masters import Client
    from app.ui.master_abm import master_abm_configs

    cliente = Client.create(
        name="Cliente Grilla",
        cuit="30923000011",
        iva_condition="RI",
        whatsapp_phone="5491153088679",
    )
    config = master_abm_configs()["clients"]
    assert "WhatsApp" in config.columns
    filas = config.rows_fn()
    fila = [f for f in filas if f[0] == cliente.id][0]
    assert fila[config.columns.index("WhatsApp")] == "5491153088679"
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL (no existe la columna "WhatsApp").

- [ ] **Paso 3: implementación mínima**

En `app/ui/master_abm.py`:

1. Columnas (línea 458): `["Nombre", "CUIT", "Vendedor", "WhatsApp", "Lista", "Estado"]`.
2. `_client_rows`: agregar el valor en la misma posición:
   ```python
                   client.whatsapp_phone or "",
   ```
3. Botón (junto a `phone_client_btn`, línea 2160):
   ```python
   whatsapp_client_btn = _action_button("editClientWhatsappButton", "WhatsApp", secondary=True)
   whatsapp_client_btn.setToolTip(
       "Carga el numero de WhatsApp del cliente. Solo se aceptan celulares: "
       "el telefono general queda aparte."
   )
   ```
4. Función nueva junto a `edit_client_phone` (línea 2404):
   ```python
   def edit_client_whatsapp() -> None:
       """Cambia solo el numero de WhatsApp del cliente seleccionado (#923)."""
       from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

       if not can_modify:
           client_feedback.show_warning("El perfil actual no permite modificar este maestro.")
           return
       cid = selected_client_id()
       if cid is None:
           client_feedback.show_warning(
               "Seleccione un cliente para cargarle el WhatsApp.", focus_widget=client_table
           )
           return
       dialogo = ClientWhatsappEditDialog(
           client=Client.get_by_id(cid),
           current_user=current_user,
           parent=parent,
       )
       if dialogo.exec_() == QDialog.Accepted:
           refresh_clients()
           client_feedback.show_success("WhatsApp actualizado.")
   ```
5. Conexión (línea 2587): `whatsapp_client_btn.clicked.connect(edit_client_whatsapp)`.

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/ui/master_abm.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): boton y columna de WhatsApp en la grilla de clientes"
```

---

### Tarea 7: Vendedores (campo en el diálogo y columna en la grilla)

**Archivos:**
- Modificar: `app/services/master_service.py:242-316` (`create_salesperson` / `update_salesperson`)
- Modificar: `app/ui/master_abm.py:1105-1179` (`SalespersonEntryDialog`), `app/ui/master_abm.py:466-470` (columnas de "salespeople"), `app/ui/master_abm.py:1960-1973` (`_salesperson_rows`)
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Consume: `WhatsAppContactService.normalizar(numero) -> str` (Tarea 3).
- Produce: `MasterService.create_salesperson(..., whatsapp_phone: str | None = None)` y `MasterService.update_salesperson(..., whatsapp_phone: str | None | _UNSET = _UNSET)`. El sentinel `_UNSET` evita que un llamador que no conoce el campo **borre** el WhatsApp ya cargado.

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
def test_actualizar_vendedor_no_borra_el_whatsapp_si_no_se_pasa(db):
    """Un llamador que no conoce el campo no puede vaciarlo por accidente."""
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(name="Vendedor Master", whatsapp_phone="5491153088679")
    MasterService("admin923").update_salesperson(vendedor, "Vendedor Master")
    assert vendedor.whatsapp_phone == "5491153088679"


def test_actualizar_vendedor_guarda_el_whatsapp(db):
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(name="Vendedor Master2")
    MasterService("admin923").update_salesperson(
        vendedor, "Vendedor Master2", whatsapp_phone="011 15 53088679"
    )
    assert vendedor.whatsapp_phone == "5491153088679"


def test_crear_vendedor_rechaza_un_whatsapp_dudoso(db):
    import pytest

    from app.services.master_service import MasterService

    with pytest.raises(ValueError):
        MasterService("admin923").create_salesperson(
            "Vendedor Mal", whatsapp_phone="011 4441-2835"
        )


def test_la_grilla_de_vendedores_muestra_el_whatsapp(db):
    from app.models.masters import Salesperson
    from app.ui.master_abm import master_abm_configs

    vendedor = Salesperson.create(name="Vendedor Grilla", whatsapp_phone="5491153088679")
    config = master_abm_configs()["salespeople"]
    assert "WhatsApp" in config.columns
    filas = config.rows_fn()
    fila = [f for f in filas if f[0] == vendedor.id][0]
    assert fila[config.columns.index("WhatsApp")] == "5491153088679"
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL (`TypeError: unexpected keyword argument 'whatsapp_phone'`).

- [ ] **Paso 3: implementación mínima**

En `app/services/master_service.py`, arriba de la clase:

```python
class _Unset:
    """Marca un valor que el llamador no pasa (para no pisar lo cargado)."""

    def __repr__(self) -> str:  # pragma: no cover - solo ayuda al debug
        return "<UNSET>"


UNSET = _Unset()
```

En `create_salesperson`, agregar el parámetro y el `create`:

```python
        whatsapp_phone: str | None = None,
```
```python
        row = Salesperson.create(
            name=name,
            phone=(phone or "").strip() or None,
            whatsapp_phone=_normalizar_whatsapp(whatsapp_phone),
            ...
        )
```

En `update_salesperson`:

```python
        whatsapp_phone: str | None | _Unset = UNSET,
```
```python
        if not isinstance(whatsapp_phone, _Unset):
            salesperson.whatsapp_phone = _normalizar_whatsapp(whatsapp_phone)
```

Y el helper, en el mismo archivo:

```python
def _normalizar_whatsapp(numero: str | None) -> str | None:
    """Valida el numero de WhatsApp con la misma regla del servicio (#923)."""
    from app.services.whatsapp_contact_service import WhatsAppContactService

    if numero is None:
        return None
    normalizado = WhatsAppContactService.normalizar(numero)
    return normalizado or None
```

En `app/ui/master_abm.py`, `SalespersonEntryDialog`: agregar `self.whatsapp_input` (objectName `salespersonWhatsappInput`), la fila del formulario, la carga en `_load_record` y el `values` de `_save`:

```python
            "whatsapp_phone": self.whatsapp_input.text(),
```

En las columnas de "salespeople": `["Nombre", "Teléfono", "WhatsApp", "Email", "Estado"]`, y en `_salesperson_rows` agregar `salesperson.whatsapp_phone or ""` en esa posición.

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/services/master_service.py app/ui/master_abm.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): WhatsApp en el alta y edicion de vendedores"
```

---

### Tarea 8: La pantalla de carga de los pendientes

**Archivos:**
- Modificar: `app/services/whatsapp_contact_service.py` (agregar `listar_clientes_pendientes`)
- Crear: `app/ui/whatsapp_contact_load_dialog.py`
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Consume: `LoadOrder` de `app/models/load_orders.py` (campo `client`, `status`, `issue_date`/fecha de emisión), `Client.salesperson`.
- Produce:
  ```python
  @dataclass(frozen=True)
  class ClientePendiente:
      client_id: int
      nombre: str
      vendedor: str
      telefono: str
      whatsapp_phone: str
      estado_telefono: str
      ultima_orden: str      # ISO o ""

  class WhatsAppContactService:
      def listar_clientes_pendientes(self, *, solo_con_orden: bool = True) -> list[ClientePendiente]: ...
  ```
  y el diálogo:
  ```python
  class WhatsAppContactLoadDialog(QDialog):
      def __init__(self, *, current_user: str, parent=None)
  ```

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
def test_lista_los_clientes_con_orden_y_sin_whatsapp(db):
    from datetime import date

    from app.models.masters import Carrier, Client, Driver, Truck
    from app.models.load_orders import LoadOrder
    from app.services.whatsapp_contact_service import WhatsAppContactService

    transportista = Carrier.create(name="Transportista 923")
    chofer = Driver.create(name="Chofer 923", carrier=transportista, document="1")
    camion = Truck.create(domain="AB923CD", carrier=transportista)

    con_orden = Client.create(
        name="Con Orden", cuit="30923000012", iva_condition="RI", phone="011 15 53088679"
    )
    sin_orden = Client.create(
        name="Sin Orden", cuit="30923000013", iva_condition="RI", phone="011 15 53088679"
    )
    ya_cargado = Client.create(
        name="Ya Cargado",
        cuit="30923000014",
        iva_condition="RI",
        phone="011 15 53088679",
        whatsapp_phone="5491153088679",
    )
    LoadOrder.create(
        order_number=901,
        client=con_orden,
        carrier=transportista,
        driver=chofer,
        truck=camion,
        status=LoadOrder.STATUS_ISSUED,
        date=date(2026, 11, 1),
    )
    LoadOrder.create(
        order_number=902,
        client=ya_cargado,
        carrier=transportista,
        driver=chofer,
        truck=camion,
        status=LoadOrder.STATUS_ISSUED,
        date=date(2026, 11, 2),
    )

    pendientes = WhatsAppContactService("admin923").listar_clientes_pendientes()
    nombres = [p.nombre for p in pendientes]
    assert "Con Orden" in nombres
    assert "Ya Cargado" not in nombres
    assert "Sin Orden" not in nombres

    todos = WhatsAppContactService("admin923").listar_clientes_pendientes(
        solo_con_orden=False
    )
    assert "Sin Orden" in [p.nombre for p in todos]


def test_los_pendientes_vienen_por_ultima_orden_mas_reciente(db):
    from datetime import date

    from app.models.masters import Carrier, Client, Driver, Truck
    from app.models.load_orders import LoadOrder
    from app.services.whatsapp_contact_service import WhatsAppContactService

    transportista = Carrier.create(name="Transportista 924")
    chofer = Driver.create(name="Chofer 924", carrier=transportista, document="2")
    camion = Truck.create(domain="AB924CD", carrier=transportista)

    viejo = Client.create(name="Viejo", cuit="30923000023", iva_condition="RI")
    nuevo = Client.create(name="Nuevo", cuit="30923000024", iva_condition="RI")
    LoadOrder.create(
        order_number=911,
        client=viejo,
        carrier=transportista,
        driver=chofer,
        truck=camion,
        status=LoadOrder.STATUS_ISSUED,
        date=date(2026, 1, 5),
    )
    LoadOrder.create(
        order_number=912,
        client=nuevo,
        carrier=transportista,
        driver=chofer,
        truck=camion,
        status=LoadOrder.STATUS_ISSUED,
        date=date(2026, 11, 5),
    )

    pendientes = WhatsAppContactService("admin923").listar_clientes_pendientes()
    assert [p.nombre for p in pendientes] == ["Nuevo", "Viejo"]
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL (`AttributeError: 'WhatsAppContactService' object has no attribute 'listar_clientes_pendientes'`).

- [ ] **Paso 3: implementación mínima**

En `app/services/whatsapp_contact_service.py`, agregar el dataclass y el método:

```python
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
```

```python
    def listar_clientes_pendientes(
        self, *, solo_con_orden: bool = True
    ) -> list[ClientePendiente]:
        """Clientes sin WhatsApp cargado, ordenados por la ultima orden.

        Vienen primero los que mas duelen: los que tienen movimiento reciente.
        """
        from app.models.load_orders import LoadOrder
        from app.services.whatsapp_phone_classifier import clasificar_telefono

        consulta = (
            Client.select(Client, Salesperson)
            .join(Salesperson, JOIN.LEFT_OUTER)
            .where((Client.active == True) & (Client.whatsapp_phone.is_null(True)))  # noqa: E712
            .order_by(Client.name)
        )
        pendientes = []
        for cliente in consulta:
            ordenes = list(
                LoadOrder.select()
                .where(
                    (LoadOrder.client == cliente)
                    & (LoadOrder.status != LoadOrder.STATUS_ANNULLED)
                )
                .order_by(LoadOrder.date.desc(), LoadOrder.id.desc())
            )
            if solo_con_orden and not ordenes:
                continue
            clasificacion = clasificar_telefono(cliente.phone)
            pendientes.append(
                ClientePendiente(
                    client_id=cliente.id,
                    nombre=cliente.name,
                    vendedor=cliente.salesperson.name if cliente.salesperson_id else "",
                    telefono=cliente.phone or "",
                    whatsapp_phone=cliente.whatsapp_phone or "",
                    estado_telefono=clasificacion.estado,
                    ultima_orden=str(ordenes[0].date) if ordenes else "",
                )
            )
        pendientes.sort(key=lambda p: p.ultima_orden, reverse=True)
        return pendientes
```

Crear `app/ui/whatsapp_contact_load_dialog.py`: un `QDialog` con una `QTableWidget` (columnas Cliente, Vendedor, Teléfono, Estado, WhatsApp), un botón "Cargar WhatsApp" por fila que abre el `ClientWhatsappEditDialog` de la Tarea 5, un filtro "solo con orden emitida" y un botón "Guardar y cerrar". La tabla va con scroll dentro del dialogo: el alto del dialogo se limita a 720 px para que entre en 1366x768.

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/services/whatsapp_contact_service.py app/ui/whatsapp_contact_load_dialog.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): pantalla de carga de los WhatsApp pendientes"
```

---

### Tarea 9: El backfill

**Archivos:**
- Modificar: `app/services/whatsapp_contact_service.py` (agregar `backfill`)
- Crear: `scripts/backfill_whatsapp_phones.py`
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Produce:
  ```python
  @dataclass(frozen=True)
  class BackfillInforme:
      copiados_clientes: int
      copiados_vendedores: int
      omitidos: list[tuple[str, str, str]]   # (tipo, nombre, motivo)

  class WhatsAppContactService:
      def backfill(self, *, usuario: str | None = None) -> BackfillInforme: ...
  ```
  y el script `python scripts/backfill_whatsapp_phones.py [--aplicar] [--usuario X] [--json]`, que **sin `--aplicar` no escribe nada**.

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
def test_el_backfill_solo_copia_celulares(db):
    from app.models.masters import Client, Salesperson
    from app.services.whatsapp_contact_service import WhatsAppContactService

    celular = Client.create(
        name="Cliente Celular", cuit="30923000015", iva_condition="RI", phone="011 15 53088679"
    )
    dudoso = Client.create(
        name="Cliente Dudoso", cuit="30923000016", iva_condition="RI", phone="011 4441-2835"
    )
    vendedor = Salesperson.create(name="Vendedor Celular", phone="+5493758650849")

    informe = WhatsAppContactService("admin923").backfill()
    assert celular.whatsapp_phone == "5491153088679"
    assert dudoso.whatsapp_phone is None
    assert vendedor.whatsapp_phone == "5493758650849"
    assert informe.copiados_clientes == 1
    assert informe.copiados_vendedores == 1


def test_el_backfill_es_idempotente(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente Idempotente", cuit="30923000017", iva_condition="RI", phone="011 15 53088679"
    )
    WhatsAppContactService("admin923").backfill()
    segundo = WhatsAppContactService("admin923").backfill()
    assert cliente.whatsapp_phone == "5491153088679"
    assert segundo.copiados_clientes == 0


def test_el_backfill_no_pisa_un_whatsapp_cargado(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente Manual",
        cuit="30923000018",
        iva_condition="RI",
        phone="011 15 53088679",
        whatsapp_phone="5491153000000",
    )
    WhatsAppContactService("admin923").backfill()
    assert cliente.whatsapp_phone == "5491153000000"
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL (`AttributeError: 'WhatsAppContactService' object has no attribute 'backfill'`).

- [ ] **Paso 3: implementación mínima**

En `app/services/whatsapp_contact_service.py`, agregar el import y el dataclass:

```python
from dataclasses import dataclass, field
```

```python
@dataclass(frozen=True)
class BackfillInforme:
    """Que copio el backfill y que dejo sin destino."""

    copiados_clientes: int = 0
    copiados_vendedores: int = 0
    omitidos: list = field(default_factory=list)
```

```python
    def backfill(self, *, usuario: str | None = None) -> BackfillInforme:
        """Copia al campo nuevo los celulares que ya estan cargados.

        Solo copia lo que el clasificador da como **celular**: un numero
        dudoso se deja vacio a proposito, para que el operador lo confirme.
        Es idempotente: no pisa un WhatsApp ya cargado.
        """
        from app.services.whatsapp_phone_classifier import ESTADO_CELULAR, clasificar_telefono

        omitidos = []
        copiados_clientes = 0
        for cliente in Client.select().where(Client.whatsapp_phone.is_null(True)):
            clasificacion = clasificar_telefono(cliente.phone)
            if clasificacion.estado != ESTADO_CELULAR:
                omitidos.append(("cliente", cliente.name, clasificacion.motivo or clasificacion.estado))
                continue
            self.set_client_whatsapp_phone(cliente, cliente.phone)
            copiados_clientes += 1

        copiados_vendedores = 0
        for vendedor in Salesperson.select().where(Salesperson.whatsapp_phone.is_null(True)):
            clasificacion = clasificar_telefono(vendedor.phone)
            if clasificacion.estado != ESTADO_CELULAR:
                omitidos.append(("vendedor", vendedor.name, clasificacion.motivo or clasificacion.estado))
                continue
            self.set_salesperson_whatsapp_phone(vendedor, vendedor.phone)
            copiados_vendedores += 1

        return BackfillInforme(
            copiados_clientes=copiados_clientes,
            copiados_vendedores=copiados_vendedores,
            omitidos=omitidos,
        )
```

Crear `scripts/backfill_whatsapp_phones.py`, siguiendo el patrón de `scripts/import_client_price_lists.py` (mismo `sys.path.insert`, mismo `initialize_runtime_database`, mismo `ensure_runtime_schema`, salida JSON con `--json`, códigos de salida 0/1):

```python
"""Copia al campo de WhatsApp los celulares que ya estan cargados (#923).

Sin ``--aplicar`` solo muestra que copiaria: **no escribe nada**.

Códigos de salida:

- ``0``: todo bien (aplicado, o solo vista previa).
- ``1``: error (no se pudo aplicar).
"""
```

El script llama a `WhatsAppContactService(usuario).backfill()` **solo** con `--aplicar`; sin el flag, recorre los contactos y muestra el informe sin escribir.

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: todos pasan.

- [ ] **Paso 5: commit**

```bash
git add app/services/whatsapp_contact_service.py scripts/backfill_whatsapp_phones.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): backfill de los WhatsApp ya confirmados"
```

---

### Tarea 10: Los envíos usan el resolver (con el flag apagado, igual que hoy)

**Archivos:**
- Modificar: `app/services/whatsapp_contact_service.py` (agregar `destino_cliente` y `destino_vendedor`)
- Modificar: `app/ui/desktop_app.py:294-297` (`_current_client_phone`) y `app/ui/desktop_app.py:1320-1324` (flujo del vendedor)
- Test: `tests/test_issue_923_whatsapp_dedicated.py`

**Interfaces:**
- Produce:
  ```python
  class WhatsAppContactService:
      def destino_cliente(self, client, *, preferir_dedicado: bool | None = None) -> str
      def destino_vendedor(self, salesperson, *, preferir_dedicado: bool | None = None) -> str
  ```
  Ambos devuelven el numero normalizado o levantan `ValueError` con el mensaje que ya usa la app.

- [ ] **Paso 1: escribir el test que falla**

Agregar a `tests/test_issue_923_whatsapp_dedicated.py`:

```python
def test_el_destino_con_el_flag_apagado_es_el_telefono(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente Destino",
        cuit="30923000019",
        iva_condition="RI",
        phone="011 15 53088679",
        whatsapp_phone="5491153000000",
    )
    servicio = WhatsAppContactService("admin923")
    assert servicio.destino_cliente(cliente, preferir_dedicado=False) == "5491153088679"


def test_el_destino_con_el_flag_encendido_usa_el_campo_nuevo(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente Destino2",
        cuit="30923000020",
        iva_condition="RI",
        phone="011 15 53088679",
        whatsapp_phone="5491153000000",
    )
    servicio = WhatsAppContactService("admin923")
    assert servicio.destino_cliente(cliente, preferir_dedicado=True) == "5491153000000"


def test_el_destino_sin_whatsapp_cae_al_telefono(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente Destino3", cuit="30923000021", iva_condition="RI", phone="011 15 53088679"
    )
    servicio = WhatsAppContactService("admin923")
    assert servicio.destino_cliente(cliente, preferir_dedicado=True) == "5491153088679"


def test_el_destino_sin_numero_levanta_el_error_de_hoy(db):
    import pytest

    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente Destino4", cuit="30923000022", iva_condition="RI")
    with pytest.raises(ValueError):
        WhatsAppContactService("admin923").destino_cliente(cliente)


def test_el_prefill_del_dialogo_no_levanta_si_no_hay_numero(db):
    """Sin numero no hay traceback: el dialogo de envio avisa al operador."""
    from app.models.masters import Client
    from app.ui.desktop_app import _current_client_phone

    cliente = Client.create(name="Cliente Destino5", cuit="30923000025", iva_condition="RI")
    assert _current_client_phone(cliente) == ""
```

- [ ] **Paso 2: correr el test y ver que falla**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
```

Expected: FAIL (`AttributeError: ... 'destino_cliente'`).

- [ ] **Paso 3: implementación mínima**

En `app/services/whatsapp_contact_service.py`, agregar el import y los metodos:

```python
from app.services.whatsapp_contact_resolver import resolver_contacto
```

```python
    def _preferir_dedicado(self, override: bool | None) -> bool:
        if override is not None:
            return bool(override)
        from app.config.settings import load_settings

        return bool(load_settings().whatsapp_contact_dedicado)

    def destino_cliente(self, client: Client, *, preferir_dedicado: bool | None = None) -> str:
        """El numero al que se le puede mandar WhatsApp a este cliente."""
        contacto = resolver_contacto(
            whatsapp_phone=client.whatsapp_phone,
            phone=client.phone,
            preferir_dedicado=self._preferir_dedicado(preferir_dedicado),
        )
        if not contacto.enviable:
            raise ValueError(contacto.mensaje)
        return contacto.numero

    def destino_vendedor(self, salesperson: Salesperson, *, preferir_dedicado: bool | None = None) -> str:
        contacto = resolver_contacto(
            whatsapp_phone=salesperson.whatsapp_phone,
            phone=salesperson.phone,
            preferir_dedicado=self._preferir_dedicado(preferir_dedicado),
        )
        if not contacto.enviable:
            raise ValueError(contacto.mensaje)
        return contacto.numero
```

En `app/ui/desktop_app.py`, reemplazar `_current_client_phone` (línea 294) por una versión que consulta el servicio **sin levantar excepción**: el diálogo de envío ya sabe avisarle al operador cuando el número no sirve, y hoy ese es el camino que se usa cuando el cliente no tiene teléfono.

```python
def _current_client_phone(client) -> str:
    """El numero de destino del cliente, con la regla del resolver (#923).

    Con el flag apagado es el telefono de siempre: el comportamiento no cambia
    hasta que el administrador habilite la preferencia por el campo nuevo.
    Si no hay un numero valido, devuelve "" y deja que el dialogo de envio
    avise al operador, como pasa hoy con los clientes sin telefono.
    """
    from app.services.whatsapp_contact_service import WhatsAppContactService

    client_id = getattr(client, "id", None)
    current_client = Client.get_or_none(Client.id == client_id) if client_id is not None else None
    destino = current_client or client
    try:
        return WhatsAppContactService("").destino_cliente(destino)
    except ValueError:
        return ""
```

Y en el flujo del vendedor (`app/ui/desktop_app.py:1322`), cambiar `phone=salesperson.phone` por el destino del vendedor, con el mismo criterio (sin levantar):

```python
def _current_salesperson_phone(salesperson) -> str:
    """El numero de destino del vendedor, con la regla del resolver (#923)."""
    from app.services.whatsapp_contact_service import WhatsAppContactService

    try:
        return WhatsAppContactService("").destino_vendedor(salesperson)
    except ValueError:
        return ""
```

```python
            phone=_current_salesperson_phone(salesperson),
```

> **Por qué no se levanta la excepción:** en ambos flujos el diálogo se arma **fuera** del
> `try/except` que maneja los errores de envío. Si `_current_client_phone` levantara, el
> error escaparía como traceback en vez de mostrarse al operador. Devolver `""` deja que el
> diálogo muestre el aviso, que es lo que ya pasa hoy con un cliente sin teléfono.

- [ ] **Paso 4: correr el test y ver que pasa**

```bash
python -m pytest tests/test_issue_923_whatsapp_dedicated.py -q
python -m pytest tests/test_issue_453_budget_whatsapp.py tests/test_issue_482_whatsapp_extract_ui.py -q
```

Expected: todos pasan, y los tests de los flujos de WhatsApp existentes siguen en verde.

- [ ] **Paso 5: commit**

```bash
git add app/services/whatsapp_contact_service.py app/ui/desktop_app.py tests/test_issue_923_whatsapp_dedicated.py
git commit -m "feat(#923): los envíos toman el destino del resolver (#923)"
```

---

### Tarea 11: Validación contra la base real, documentación y PR

**Archivos:**
- Modificar: `docs/issue-923-whatsapp-dedicado.md` (bitácora)
- Test: `tests/test_issue_923_whatsapp_dedicated.py` (el test de la base real va aparte, no en la suite)

- [ ] **Paso 1: correr la validación mínima del proyecto**

```bash
git diff --check
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Anotar en el PR el resultado real de cada comando.

- [ ] **Paso 2: preparar la base real de prueba**

La base real es el dump MySQL 5.7 del cliente importado en MariaDB de WSL (puerto 3308, base `femag_desktop`). Desde WSL:

```bash
wsl -e bash -lc "nohup mysqld --defaults-file=/home/oscar/mysql_an/my.cnf --user=oscar > /home/oscar/mysql_an/start.log 2>&1 & sleep 8; ss -lnt | grep 3308"
```

- [ ] **Paso 3: aplicar la columna con el camino oficial**

```bash
python scripts/init_db.py
```

Verificar que quedaron las dos columnas:

```bash
wsl -e bash -lc "mysql --socket=/home/oscar/mysql_an/run/mysql.sock -u root -e \"SHOW COLUMNS FROM femag_desktop.client LIKE 'whatsapp_phone'; SHOW COLUMNS FROM femag_desktop.salesperson LIKE 'whatsapp_phone';\""
```

- [ ] **Paso 4: correr el backfill en modo vista previa y revisar el informe**

```bash
python scripts/backfill_whatsapp_phones.py
```

Expected: informa 26 clientes y 8 vendedores con celular, y deja los demas sin destino. **Comparar con los numeros de la auditoria** (26 celular de 904 clientes, 8 de 9 vendedores). Si no coinciden, **no seguir**: el dump cambio.

- [ ] **Paso 5: respaldar y aplicar**

Respaldo antes de escribir (mysqldump desde WSL; el `.cnf` de credenciales va dentro de WSL con permisos 600, porque mysqldump ignora los archivos world-readable de `/mnt/c`):

```bash
wsl -e bash -lc "mysqldump --defaults-file=/home/oscar/mysql_an/my.cnf --socket=/home/oscar/mysql_an/run/mysql.sock -u root femag_desktop > /home/oscar/backups/femag_desktop_pre_923.sql && ls -la /home/oscar/backups/femag_desktop_pre_923.sql"
```

Luego:

```bash
python scripts/backfill_whatsapp_phones.py --aplicar
```

- [ ] **Paso 6: verificar con consultas de solo lectura**

```bash
wsl -e bash -lc "mysql --socket=/home/oscar/mysql_an/run/mysql.sock -u root -e \"SELECT COUNT(*) AS con_whatsapp FROM femag_desktop.client WHERE whatsapp_phone IS NOT NULL; SELECT COUNT(*) AS clientes FROM femag_desktop.client WHERE active = 1;\""
```

Expected: 26 clientes con WhatsApp (de 904 activos). Verificar tambien que `phone` **no** cambio: comparar el conteo de `phone` no nulos antes y despues.

- [ ] **Paso 7: restaurar la base con el dump limpio**

Como el backfill escribe en la base de prueba, restaurar la base con el dump original para no dejar datos de prueba mezclados con los del cliente.

- [ ] **Paso 8: actualizar la bitácora del documento**

En `docs/issue-923-whatsapp-dedicado.md`, agregar a la tabla de bitácora:

```
| 13/11/2026 | Implementado en `feat/issue-923-whatsapp-dedicado`: campo, resolver, servicio, UI, backfill. Backfill validado contra la base real: 26 clientes + 8 vendedores, resto sin destino. |
```

Y actualizar la seccion de pendientes.

- [ ] **Paso 9: commit**

```bash
git add docs/issue-923-whatsapp-dedicado.md
git commit -m "docs(#923): bitacora de la implementacion y la validacion contra la base real"
```

- [ ] **Paso 10: abrir el PR**

```bash
gh pr create --base main --head feat/issue-923-whatsapp-dedicado --title "feat(#923): numero de WhatsApp dedicado para clientes y vendedores" --body-file .pr_body_tmp.md
```

El cuerpo del PR debe incluir: resumen, issue relacionado, alcance incluido, **fuera de alcance** (el envío automático del #706 y la activación del flag), archivos agregados o modificados, validaciones ejecutadas con su resultado real, riesgos conocidos, y la nota de que el flag queda apagado.

- [ ] **Paso 11: comentar el estado operativo en el issue**

En el issue #923, comentar: qué se implementó, qué se validó (con los comandos y sus resultados), qué quedó pendiente (activar el flag cuando los números estén cargados, que es parte del #706) y el próximo paso recomendado.

---

## Mapa de archivos

**Nuevos:**
- `app/services/whatsapp_contact_resolver.py` — la regla de qué número es válido (puro).
- `app/services/whatsapp_contact_service.py` — guardar, auditar, listar pendientes, backfill.
- `app/ui/whatsapp_phone_edit_widgets.py` — piezas compartidas por los dos diálogos de teléfono.
- `app/ui/client_whatsapp_edit_dialog.py` — edición rápida del WhatsApp del cliente.
- `app/ui/whatsapp_contact_load_dialog.py` — pantalla de carga de los pendientes.
- `scripts/backfill_whatsapp_phones.py` — backfill con vista previa por defecto.
- `tests/test_issue_923_whatsapp_dedicated.py` — toda la cobertura.

**Modificados:**
- `app/models/masters.py` — los dos campos.
- `app/config/settings.py` — el flag.
- `.env.example` — el flag documentado.
- `app/ui/master_abm.py` — botón, columna y campo de Vendedores.
- `app/ui/desktop_app.py` — los destinos salen del resolver.
- `app/services/master_service.py` — el kwarg del vendedor con sentinel.
- `docs/issue-923-whatsapp-dedicado.md` — bitácora.

**No se tocan:** `app/services/whatsapp_envio_service.py` (sigue normalizando igual), `app/services/account_statement_share_service.py` (el resolver reutiliza sus mensajes, no lo cambia), los cálculos de presupuestos, la impresión y el importador legacy.

## Reglas de la revisión

- Cada PR debe ser chico: este PR es **una** unidad de trabajo (el contacto de WhatsApp del cliente y del vendedor).
- Todo cambio de esquema pasa por el camino oficial del administrador; la app no migra al arrancar.
- Si un comando de validación no se puede ejecutar, se documenta como pendiente en el PR. No se inventan resultados.
