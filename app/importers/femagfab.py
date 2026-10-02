from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os

import pymysql

from app.config.database import resolve_mysql_host_ipv4
from app.config.settings import load_settings
from app.utils.datetime_utils import as_datetime


TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class LegacyReceipt:
    comp: str
    received_at: datetime
    supplier_code: str
    supplier_name: str
    product_code: str
    product_name: str
    gross_kg: Decimal
    tare_kg: Decimal
    net_kg: Decimal
    payable_kg: Decimal
    earth_discount_pct: Decimal
    cepa_discount_pct: Decimal
    yield_1: Decimal
    yield_2: Decimal
    yield_3: Decimal
    yield_average: Decimal
    legacy_starch_kg: Decimal

    @property
    def theoretical_starch_kg(self) -> Decimal:
        return (self.payable_kg * self.yield_average / Decimal("100")).quantize(
            TWOPLACES, rounding=ROUND_HALF_UP
        )

    def payload(self) -> dict:
        return {
            "comp": self.comp,
            "received_at": as_datetime(self.received_at).isoformat(sep=" "),
            "supplier_code": self.supplier_code,
            "supplier_name": self.supplier_name,
            "product_code": self.product_code,
            "product_name": self.product_name,
            "gross_kg": str(self.gross_kg),
            "tare_kg": str(self.tare_kg),
            "net_kg": str(self.net_kg),
            "payable_kg": str(self.payable_kg),
            "earth_discount_pct": str(self.earth_discount_pct),
            "cepa_discount_pct": str(self.cepa_discount_pct),
            "yield_1": str(self.yield_1),
            "yield_2": str(self.yield_2),
            "yield_3": str(self.yield_3),
            "yield_average": str(self.yield_average),
            "legacy_starch_kg": str(self.legacy_starch_kg),
            "theoretical_starch_kg": str(self.theoretical_starch_kg),
        }

    @property
    def source_hash(self) -> str:
        raw = json.dumps(self.payload(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FemagFabSource:
    """Consulta femagfab exclusivamente con sentencias SELECT."""

    def __init__(self, *, host=None, port=None, database=None, user=None, password=None, instance=None):
        # femagfab vive en el mismo servidor que FEMAG Desktop. Reutilizamos la
        # conexión runtime (incluida la credencial segura/DPAPI en producción) y
        # cambiamos únicamente el schema de origen.
        settings = load_settings()
        self.host = host or settings.db_host
        self.port = int(port or settings.db_port)
        self.database = database or os.getenv("FEMAGFAB_DB_NAME", "femagfab")
        self.user = user or settings.db_user
        self.password = settings.db_password if password is None else password
        self.instance = instance or os.getenv("FEMAGFAB_SOURCE_INSTANCE", "femagfab")

    @property
    def configured(self) -> bool:
        return bool(self.host and self.database and self.user)

    def source_key(self, comp: str) -> str:
        return f"{self.instance}:{self.database}:movi:{comp}"

    def _connect(self):
        if not self.configured:
            raise RuntimeError("La conexión principal de FEMAG no está configurada para acceder a femagfab.")
        return pymysql.connect(
            host=resolve_mysql_host_ipv4(self.host), port=self.port, user=self.user,
            password=self.password, database=self.database, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, autocommit=True,
            read_timeout=15, write_timeout=15,
        )

    def fetch_day(self, day: date) -> list[LegacyReceipt]:
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        sql = """
            SELECT m.COMP comp, m.FECHA received_at, m.PROVEEDOR supplier_code,
                   COALESCE(pr.NOMBRE, '') supplier_name, m.PRODUCTO product_code,
                   COALESCE(p.NOMBRE, '') product_name, m.BRUTO gross_kg,
                   m.TARA tare_kg, m.NETO net_kg, m.TOTALK payable_kg,
                   m.DESCT earth_discount_pct, m.DESCC cepa_discount_pct,
                   m.RINDE1 yield_1, m.RINDE2 yield_2, m.RINDE3 yield_3,
                   m.PROMEDIO yield_average, m.FECULA legacy_starch_kg
              FROM movi m
              LEFT JOIN proveedo pr ON pr.CODIGO = m.PROVEEDOR
              LEFT JOIN productos p ON p.CODIGO = m.PRODUCTO
             WHERE m.FECHA >= %s AND m.FECHA < %s
               AND m.TARA > 0 AND m.TOTALK > 0 AND m.PROMEDIO > 0
               AND COALESCE(m.PRODUCTO, '') <> ''
             ORDER BY m.FECHA, m.COMP
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (start, end))
                return [self._row(row) for row in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def _decimal(value) -> Decimal:
        return Decimal(str(value or 0))

    def _row(self, row) -> LegacyReceipt:
        return LegacyReceipt(
            comp=str(row["comp"]).strip(), received_at=row["received_at"],
            supplier_code=str(row["supplier_code"] or "").strip(),
            supplier_name=str(row["supplier_name"] or "").strip(),
            product_code=str(row["product_code"] or "").strip(),
            product_name=str(row["product_name"] or "").strip(),
            gross_kg=self._decimal(row["gross_kg"]), tare_kg=self._decimal(row["tare_kg"]),
            net_kg=self._decimal(row["net_kg"]), payable_kg=self._decimal(row["payable_kg"]),
            earth_discount_pct=self._decimal(row["earth_discount_pct"]),
            cepa_discount_pct=self._decimal(row["cepa_discount_pct"]),
            yield_1=self._decimal(row["yield_1"]), yield_2=self._decimal(row["yield_2"]),
            yield_3=self._decimal(row["yield_3"]), yield_average=self._decimal(row["yield_average"]),
            legacy_starch_kg=self._decimal(row["legacy_starch_kg"]),
        )
