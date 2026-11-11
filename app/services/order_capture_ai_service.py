"""Precarga asistida por IA de ordenes de despacho (#913).

La IA lee una foto o un PDF de la orden impresa y propone **lote y fechas**
para las lineas que ya existen en FEMAG. Nunca crea ordenes, clientes,
productos ni cantidades, y nunca escribe en la base: devuelve una propuesta
que la ficha web muestra prellenada para que el operador la revise y confirme.

Proveedor por defecto: **MiniMax**, usando su API compatible con OpenAI
(``POST {base_url}/chat/completions``). La clave se configura por entorno; el
servicio queda deshabilitado si no hay proveedor o clave.

El contrato de salida es propio y versionado. Todo lo que llega del modelo se
valida contra las lineas reales de la orden antes de usarse.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import Iterable
from urllib import error, request

from PIL import Image

#: Version del contrato que se le pide al modelo.
SCHEMA_VERSION = 1

#: Formatos de imagen que acepta MiniMax para entrada multimodal.
SUPPORTED_IMAGE_MIME = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
SUPPORTED_MIME = SUPPORTED_IMAGE_MIME | {"application/pdf"}

#: Modelo multimodal recomendado por MiniMax al cierre de este issue.
DEFAULT_MODEL = "MiniMax-M3.1-Flash"
#: Endpoint internacional. Para cuentas de China continental: https://api.minimaxi.com/v1
DEFAULT_BASE_URL = "https://api.minimax.io/v1"

#: Lado maximo al que se reescala una foto antes de mandarla. Las fotos de
#: celular son grandes; achicarlas baja costo y latencia sin perder legibilidad.
MAX_IMAGE_LONG_SIDE = 2600
JPEG_QUALITY = 88
MAX_LOTE_LENGTH = 255

_DATE_PATTERNS = (
    re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$"),
    re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$"),
)
_DATE_TOKEN = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")


class CaptureError(Exception):
    """Error base de la captura asistida."""


class CaptureDisabledError(CaptureError):
    """El proveedor no esta configurado o le falta la clave."""


class CaptureInputError(CaptureError):
    """El archivo subido no es valido (tipo, tamano, paginas)."""


class CaptureProviderError(CaptureError):
    """El proveedor fallo, respondio tarde o devolvio algo invalido."""


@dataclass(frozen=True)
class CaptureConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    timeout_seconds: float
    max_mb: int
    max_pages: int
    detail: str
    rate_limit_per_hour: int
    enabled: bool
    missing_key: bool

    def disabled_reason(self) -> str:
        if self.provider in {"", "disabled", "none", "off"}:
            return (
                "La importación con IA está deshabilitada. Configurá "
                "FEMAG_ORDER_CAPTURE_AI_PROVIDER=minimax y la API key."
            )
        if self.missing_key:
            return (
                "Falta la API key de MiniMax. Pegala en "
                "FEMAG_ORDER_CAPTURE_AI_API_KEY y reiniciá el servidor web."
            )
        return ""


@dataclass(frozen=True)
class CaptureLot:
    lote: str
    fecha_elaboracion: date | None
    fecha_envasado: date | None
    pallets: int | None
    confidence: float
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptureLine:
    line_key: str | None
    product_text: str
    destination_text: str
    match_status: str
    lots: tuple[CaptureLot, ...]
    warnings: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class CaptureLineContext:
    """Linea de orden para pedirle la lectura a la IA sin depender de Flask.

    La webapp usa ``webapp.load_groups.LoadLine``; el escritorio arma estas
    lineas directamente desde ``LoadOrderProduct`` para no importar la webapp
    (que arrastra Flask) dentro de PyQt.
    """

    key: str
    product: str
    client: str
    destination: str
    quantity: float = 0.0
    unit: str = ""
    pallets: int = 0
    loose: bool = False


@dataclass(frozen=True)
class CaptureProposal:
    schema_version: int
    order_number: str | None
    date: date | None
    client: str | None
    lines: tuple[CaptureLine, ...]
    warnings: tuple[str, ...]
    provider: str
    model: str
    file_sha256: str
    usage: dict = field(default_factory=dict, repr=False)


# ----------------------------------------------------------------------
# Configuracion
# ----------------------------------------------------------------------


def _env_int(env, name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(env, name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_capture_config(env=None) -> CaptureConfig:
    """Lee la configuracion del proveedor en cada llamada.

    Leer el entorno en cada llamada (y no al importar el modulo) permite
    activar o desactivar la funcion sin tocar codigo y hace testeable la
    configuracion con ``monkeypatch.setenv``.
    """

    values = os.environ if env is None else env
    # El proveedor ya viene elegido: alcanza con pegar la API key para activar
    # la funcion. Sin clave, ``enabled`` queda en False y no se llama a nadie.
    provider = (
        values.get("FEMAG_ORDER_CAPTURE_AI_PROVIDER") or "minimax"
    ).strip().lower()
    api_key = (values.get("FEMAG_ORDER_CAPTURE_AI_API_KEY") or "").strip()
    model = (values.get("FEMAG_ORDER_CAPTURE_AI_MODEL") or DEFAULT_MODEL).strip()
    base_url = (
        values.get("FEMAG_ORDER_CAPTURE_AI_BASE_URL") or DEFAULT_BASE_URL
    ).strip().rstrip("/")
    detail = (values.get("FEMAG_ORDER_CAPTURE_AI_DETAIL") or "high").strip().lower()
    if detail not in {"low", "default", "high"}:
        detail = "high"
    missing_key = provider not in {"", "disabled", "none", "off"} and not api_key
    enabled = provider not in {"", "disabled", "none", "off"} and bool(api_key)
    return CaptureConfig(
        provider=provider or "disabled",
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=_env_float(values, "FEMAG_ORDER_CAPTURE_AI_TIMEOUT_SECONDS", 60.0),
        max_mb=_env_int(values, "FEMAG_ORDER_CAPTURE_MAX_MB", 10),
        max_pages=_env_int(values, "FEMAG_ORDER_CAPTURE_MAX_PAGES", 3),
        detail=detail,
        rate_limit_per_hour=_env_int(values, "FEMAG_ORDER_CAPTURE_RATE_LIMIT_PER_HOUR", 10),
        enabled=enabled,
        missing_key=missing_key,
    )


# ----------------------------------------------------------------------
# Normalizacion y validacion
# ----------------------------------------------------------------------


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return " ".join(
        "".join(char for char in text if not unicodedata.combining(char)).upper().split()
    )


_MATCH_PUNCTUATION = re.compile(r"[^0-9A-Z]+")


def normalize_match_text(value: str | None) -> str:
    """Normaliza para comparar: sin acentos, mayusculas y sin puntuacion.

    La ficha separa cliente/destino con un punto medio (``·``) y el modelo
    puede devolver guiones, barras o comas. Para comparar, todos esos signos
    valen lo mismo: un espacio.
    """

    cleaned = _MATCH_PUNCTUATION.sub(" ", normalize_text(value))
    return " ".join(cleaned.split())


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_lote(value) -> tuple[str, list[str]]:
    """Devuelve el lote normalizado y las advertencias de normalizacion."""

    warnings: list[str] = []
    if value is None:
        return "", warnings
    text = str(value).strip().strip("\"'`")
    text = " ".join(text.split()).upper()
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    if not text:
        return "", warnings
    if len(text) > MAX_LOTE_LENGTH:
        warnings.append(
            f"El lote detectado supera {MAX_LOTE_LENGTH} caracteres y se recortó."
        )
        text = text[:MAX_LOTE_LENGTH]
    if any(ord(char) < 32 for char in text):
        warnings.append("El lote detectado tenía caracteres de control y se limpió.")
        text = "".join(char for char in text if ord(char) >= 32)
    return text, warnings


def parse_capture_date(value) -> date | None:
    """Acepta fechas ISO o manuscritas (DD/MM/YY, DD-MM-YYYY, etc.)."""

    if value is None:
        return None
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if not re.search(r"\d", raw):
        return None

    for pattern in _DATE_PATTERNS:
        match = pattern.match(raw)
        if not match:
            continue
        first, second, third = (int(part) for part in match.groups())
        if len(match.group(1)) == 4:
            year, month, day = first, second, third
        else:
            day, month, year = first, second, third
            if year < 100:
                year += 2000
        try:
            parsed = date(year, month, day)
        except ValueError:
            continue
        if 2000 <= parsed.year <= date.today().year + 1:
            return parsed
    return None


def _date_from_free_text(value: str | None) -> date | None:
    """Busca una fecha embebida en un texto manuscrito ('elab. 30-10')."""

    if not value:
        return None
    direct = parse_capture_date(value)
    if direct is not None:
        return direct
    match = _DATE_TOKEN.search(value)
    if match:
        return parse_capture_date(match.group(0))
    return None


def _confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _pallets(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
    else:
        match = re.search(r"\d+", str(value))
        if not match:
            return None
        number = int(match.group(0))
    return number if number > 0 else None


def _strings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    if not raw:
        raise CaptureProviderError("La IA no devolvió contenido.")
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise CaptureProviderError("La respuesta de la IA no es un JSON válido.")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise CaptureProviderError(
            "La respuesta de la IA no es un JSON válido."
        ) from exc
    if not isinstance(payload, dict):
        raise CaptureProviderError("La respuesta de la IA no es un objeto JSON.")
    return payload


def _line_keys(load_lines: Iterable) -> set[str]:
    return {line.key for line in load_lines}


def _resolve_line_key(
    raw_key,
    *,
    product_text: str,
    destination_text: str,
    load_lines: list,
) -> tuple[str | None, str]:
    """Valida la clave que propone el modelo y, si falta, intenta mapear.

    El modelo recibe las claves reales de la orden. Aun asi no se confia en
    ellas: si la clave no existe se descarta y se intenta un match determinista
    por producto + cliente/destino, que es el mismo criterio de la ficha.
    """

    keys = _line_keys(load_lines)
    candidate = str(raw_key).strip() if raw_key is not None else ""
    if candidate and candidate in keys:
        return candidate, "matched"

    product_norm = normalize_match_text(product_text)
    destination_norm = normalize_match_text(destination_text)
    if not product_norm:
        return None, "unmatched"

    def same_product(line) -> bool:
        line_product = normalize_match_text(line.product)
        return bool(line_product) and (
            line_product == product_norm
            or line_product in product_norm
            or product_norm in line_product
        )

    candidates = [line for line in load_lines if same_product(line)]
    if not candidates:
        return None, "unmatched"
    if len(candidates) == 1:
        return candidates[0].key, "matched"

    if destination_norm:
        narrowed = [
            line
            for line in candidates
            if normalize_match_text(line.client) in destination_norm
            or normalize_match_text(line.destination) in destination_norm
            or destination_norm in normalize_match_text(line.client)
            or destination_norm in normalize_match_text(line.destination)
        ]
        if len(narrowed) == 1:
            return narrowed[0].key, "matched"
        if len(narrowed) > 1:
            return None, "ambiguous"

    return None, "ambiguous"


def _validate_lot(raw: dict, *, index: int) -> tuple[CaptureLot | None, list[str]]:
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"El lote {index + 1} no tiene el formato esperado."]

    lote, lote_warnings = normalize_lote(raw.get("lote"))
    warnings.extend(lote_warnings)
    fecha = parse_capture_date(raw.get("fecha_elaboracion"))
    fecha_raw = raw.get("fecha_elaboracion")
    if fecha_raw and fecha is None:
        warnings.append(
            f"No se pudo interpretar la fecha de elaboración del lote {index + 1}."
        )
    envasado = parse_capture_date(raw.get("fecha_envasado"))
    envasado_raw = raw.get("fecha_envasado")
    if envasado_raw and envasado is None:
        warnings.append(
            f"No se pudo interpretar la fecha de envasado del lote {index + 1}."
        )
    if not lote and fecha is None and envasado is None:
        return None, warnings
    return (
        CaptureLot(
            lote=lote,
            fecha_elaboracion=fecha,
            fecha_envasado=envasado,
            pallets=_pallets(raw.get("pallets")),
            confidence=_confidence(raw.get("confianza")),
            warnings=tuple(_strings(raw.get("advertencias"))),
        ),
        warnings,
    )


def _validate_line(raw: dict, *, load_lines: list, index: int) -> tuple[CaptureLine | None, list[str]]:
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"La línea {index + 1} no tiene el formato esperado."]

    product_text = str(raw.get("producto_texto") or "").strip()
    destination_text = str(
        raw.get("cliente_destino_texto") or raw.get("destino_texto") or ""
    ).strip()
    if normalize_match_text(product_text) in {
        "TOTAL",
        "TOTALES",
        "SUBTOTAL",
        "SUBTOTALES",
    }:
        return None, [
            "La IA devolvió una fila de totales como si fuera una línea de despacho; se descartó."
        ]
    line_key, status = _resolve_line_key(
        raw.get("line_key"),
        product_text=product_text,
        destination_text=destination_text,
        load_lines=load_lines,
    )

    raw_status = str(raw.get("match_status") or "").strip().lower()
    if line_key is not None:
        status = "matched"
    elif raw_status == "ambiguous":
        status = "ambiguous"
    # Si no hay key, el estado ambiguo/unmatched ya lo resolvio el mapeo. No se
    # deja que un "matched" del modelo convierta una ambiguedad real en unmatched.

    if raw.get("line_key") and line_key is None:
        warnings.append(
            "La IA devolvió una línea que no pertenece a esta orden; se descartó la clave."
        )

    lots: list[CaptureLot] = []
    raw_lots = raw.get("lotes")
    if isinstance(raw_lots, str):
        raw_lots = [{"lote": raw_lots}]
    if not isinstance(raw_lots, list) or not raw_lots:
        raw_lots = []
        legacy_lote = raw.get("lote")
        if legacy_lote or raw.get("fecha_elaboracion") or raw.get("fecha_envasado"):
            raw_lots = [
                {
                    "lote": legacy_lote,
                    "fecha_elaboracion": raw.get("fecha_elaboracion"),
                    "fecha_envasado": raw.get("fecha_envasado"),
                    "pallets": raw.get("pallets"),
                    "confianza": raw.get("confianza"),
                    "advertencias": raw.get("advertencias"),
                }
            ]
    for lot_index, raw_lot in enumerate(raw_lots):
        lot, lot_warnings = _validate_lot(raw_lot, index=lot_index)
        warnings.extend(lot_warnings)
        if lot is not None:
            lots.append(lot)

    line_warnings = _strings(raw.get("advertencias"))
    if status == "ambiguous":
        line_warnings.append(
            "La IA no pudo distinguir a qué línea de la orden pertenece."
        )
    elif status == "unmatched":
        line_warnings.append(
            "La IA detectó un producto/destino que no coincide con la orden."
        )

    return (
        CaptureLine(
            line_key=line_key,
            product_text=product_text,
            destination_text=destination_text,
            match_status=status,
            lots=tuple(lots),
            warnings=tuple(warnings + line_warnings),
            confidence=_confidence(raw.get("confianza")),
        ),
        warnings,
    )


def validate_extraction(payload: dict, *, load_lines: list) -> tuple[tuple[CaptureLine, ...], tuple[str, ...]]:
    """Valida el JSON del modelo contra las lineas reales de la orden."""

    if not isinstance(payload, dict):
        raise CaptureProviderError("La respuesta de la IA no es un objeto JSON.")

    schema_version = payload.get("schema_version", SCHEMA_VERSION)
    try:
        schema_version = int(schema_version)
    except (TypeError, ValueError) as exc:
        raise CaptureProviderError("La IA devolvió una versión de esquema inválida.") from exc
    if schema_version != SCHEMA_VERSION:
        raise CaptureProviderError(
            f"La IA devolvió el esquema {schema_version}; esta versión espera {SCHEMA_VERSION}."
        )

    raw_lines = payload.get("lineas")
    if raw_lines is None:
        raise CaptureProviderError("La respuesta de la IA no trae la lista de líneas.")
    if not isinstance(raw_lines, list):
        raise CaptureProviderError("La lista de líneas de la IA no es válida.")

    lines: list[CaptureLine] = []
    warnings = _strings(payload.get("advertencias"))
    seen: dict[str, int] = {}
    for index, raw_line in enumerate(raw_lines):
        line, line_warnings = _validate_line(raw_line, load_lines=load_lines, index=index)
        if line is None:
            warnings.extend(line_warnings)
            continue
        if line.line_key:
            if line.line_key in seen:
                previous = lines[seen[line.line_key]]
                warnings.append(
                    f"La IA devolvió más de una lectura para «{line.product_text}»; "
                    "se conservó la de mayor confianza."
                )
                if line.confidence > previous.confidence:
                    lines[seen[line.line_key]] = line
                continue
            seen[line.line_key] = len(lines)
        lines.append(line)

    for line in lines:
        for warning in line.warnings:
            if warning not in warnings:
                warnings.append(warning)

    return tuple(lines), tuple(warnings)


# ----------------------------------------------------------------------
# Archivos: imagenes y PDF
# ----------------------------------------------------------------------


def _sniff_mime(data: bytes, declared: str | None) -> str:
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if declared:
        declared = declared.split(";")[0].strip().lower()
        if declared in SUPPORTED_MIME:
            return declared
    try:
        with Image.open(BytesIO(data)) as image:
            fmt = (image.format or "").upper()
    except Exception as exc:
        raise CaptureInputError(
            "El archivo no es una imagen o un PDF válido."
        ) from exc
    mapping = {
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }
    mime = mapping.get(fmt)
    if not mime:
        raise CaptureInputError(
            "Formato de imagen no soportado. Usá JPG, PNG, WEBP o PDF."
        )
    return mime


def _normalize_image(image: Image.Image) -> bytes:
    """Convierte a JPEG RGB, quita EXIF y limita el lado mayor."""

    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.split()[-1])
        normalized = background
    else:
        normalized = image.convert("RGB")
    normalized.thumbnail((MAX_IMAGE_LONG_SIDE, MAX_IMAGE_LONG_SIDE), Image.LANCZOS)
    buffer = BytesIO()
    normalized.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def _image_media(data: bytes) -> list[tuple[str, bytes]]:
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            normalized = _normalize_image(image)
    except CaptureInputError:
        raise
    except Exception as exc:
        raise CaptureInputError("No se pudo leer la imagen.") from exc
    return [("image/jpeg", normalized)]


def _render_pdf_pages(data: bytes, *, max_pages: int) -> list[Image.Image]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise CaptureProviderError(
            "Falta la dependencia pypdfium2 para leer PDFs."
        ) from exc

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise CaptureInputError("El PDF está dañado o protegido.") from exc

    try:
        total = len(document)
        if total == 0:
            raise CaptureInputError("El PDF no tiene páginas.")
        if total > max_pages:
            raise CaptureInputError(
                f"El PDF tiene {total} páginas y el máximo permitido es {max_pages}."
            )
        pages: list[Image.Image] = []
        for index in range(total):
            page = document[index]
            try:
                bitmap = page.render(scale=2.2)
                try:
                    pages.append(bitmap.to_pil())
                finally:
                    bitmap.close()
            finally:
                page.close()
        return pages
    finally:
        document.close()


def _pdf_media(data: bytes, *, max_pages: int) -> list[tuple[str, bytes]]:
    pages = _render_pdf_pages(data, max_pages=max_pages)
    return [("image/jpeg", _normalize_image(page)) for page in pages]


def prepare_media(data: bytes, mime: str, *, config: CaptureConfig) -> list[tuple[str, bytes]]:
    """Valida el archivo y lo convierte en imagenes listas para el modelo."""

    if not data:
        raise CaptureInputError("El archivo está vacío.")
    max_bytes = max(1, config.max_mb) * 1024 * 1024
    if len(data) > max_bytes:
        raise CaptureInputError(
            f"El archivo supera el máximo de {config.max_mb} MB."
        )

    mime = _sniff_mime(data, mime)
    if mime == "application/pdf":
        return _pdf_media(data, max_pages=max(1, config.max_pages))
    if mime not in SUPPORTED_IMAGE_MIME:
        raise CaptureInputError(
            "Formato no soportado. Usá JPG, PNG, WEBP o PDF."
        )
    return _image_media(data)


# ----------------------------------------------------------------------
# Prompt y llamada al proveedor
# ----------------------------------------------------------------------


_SYSTEM_PROMPT = """Sos un asistente experto en leer órdenes de despacho impresas de FEMAG (fécula de mandioca).

Recibís una o más imágenes de UNA sola orden de despacho y la lista de líneas que ya existen en el sistema. Tu única tarea es extraer el LOTE, la FECHA DE ELABORACIÓN y la FECHA DE ENVASADO de cada línea de despacho.

Reglas obligatorias:
- Devolvés SOLO un objeto JSON válido, sin markdown, sin explicaciones y sin texto antes o después.
- No inventes datos. Si no podés leer un valor, devolvé null y una advertencia.
- Las columnas manuscritas suelen ser "Lote", "Elab." y a veces "Pallet".
- Ignorá el bloque de TOTALES, los subtotales, los encabezados repetidos y la sección de transporte: no son líneas de despacho.
- Una orden puede tener varios clientes/destinos y el mismo producto repetido en más de uno. Usá el cliente/destino para desambiguar.
- Para cada línea detectada, elegí exactamente una "key" de la lista de líneas de la orden. Si no hay coincidencia segura, usá null y match_status "unmatched". Si hay más de una coincidencia posible, usá null y match_status "ambiguous".
- "SUELTO" significa mercadería sin pallet. Los textos como "11 pallets" indican cantidad de pallets.
- Las fechas se devuelven como YYYY-MM-DD. Si el año viene con dos dígitos, asumí 20XX. Si la fecha es dudosa, devolvé null.
- La confianza es un número entre 0 y 1 por línea y por lote."""


def _user_prompt(context: dict) -> str:
    return (
        "Leé las imágenes de la orden y devolvé el JSON con este contrato exacto:\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "orden_numero": "string|null",\n'
        '  "fecha": "YYYY-MM-DD|null",\n'
        '  "cliente_principal": "string|null",\n'
        '  "lineas": [\n'
        "    {\n"
        '      "line_key": "key de la lista o null",\n'
        '      "producto_texto": "texto leído",\n'
        '      "cliente_destino_texto": "texto leído",\n'
        '      "match_status": "matched|ambiguous|unmatched",\n'
        '      "confianza": 0.0,\n'
        '      "lotes": [\n'
        "        {\n"
        '          "lote": "string|null",\n'
        '          "fecha_elaboracion": "YYYY-MM-DD|null",\n'
        '          "fecha_envasado": "YYYY-MM-DD|null",\n'
        '          "pallets": 0,\n'
        '          "confianza": 0.0,\n'
        '          "advertencias": ["texto"]\n'
        "        }\n"
        "      ],\n"
        '      "advertencias": ["texto"]\n'
        "    }\n"
        "  ],\n"
        '  "transporte": {"empresa": "string|null", "dominio": "string|null"},\n'
        '  "advertencias": ["texto"]\n'
        "}\n\n"
        "Líneas de la orden en FEMAG (usá estas keys):\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def build_messages(context: dict, media: list[tuple[str, bytes]]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": _user_prompt(context)}]
    for mime, data in media:
        encoded = base64.b64encode(data).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{encoded}",
                    "detail": "high",
                },
            }
        )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def build_order_context(
    load_lines: Iterable,
    *,
    order_number=None,
    order_date: date | None = None,
    client_name: str | None = None,
) -> dict:
    def pallet_count(line) -> int:
        explicit = getattr(line, "pallets", None)
        if explicit is not None:
            return int(explicit)
        return len([c for c in getattr(line, "contents", ()) if c.kind == "pallet"])

    def has_loose(line) -> bool:
        explicit = getattr(line, "loose", None)
        if explicit is not None:
            return bool(explicit)
        return any(c.kind == "loose" for c in getattr(line, "contents", ()))

    return {
        "orden_numero": str(order_number) if order_number is not None else None,
        "fecha": order_date.isoformat() if order_date else None,
        "cliente": client_name,
        "lineas": [
            {
                "key": line.key,
                "producto": line.product,
                "cliente": line.client,
                "destino": line.destination,
                "cantidad": line.quantity,
                "unidad": line.unit,
                "pallets": pallet_count(line),
                "suelto": has_loose(line),
            }
            for line in load_lines
        ],
    }


def _provider_error_detail(detail: str) -> str:
    """Extrae el mensaje util del JSON de error del proveedor."""

    if not detail:
        return ""
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return detail.strip()
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"]).strip()
        if payload.get("message"):
            return str(payload["message"]).strip()
    return detail.strip()


def _post_json(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    """POST JSON con la libreria estandar.

    Se aisla en una funcion para que los tests puedan reemplazarla y para no
    agregar dependencias HTTP al servidor de la fabrica.
    """

    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        message = f"El proveedor de IA respondió HTTP {exc.code}."
        clean_detail = _provider_error_detail(detail)
        if clean_detail:
            message = f"El proveedor de IA rechazó la solicitud: {clean_detail}"
        raise CaptureProviderError(message) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise CaptureProviderError(
            "No se pudo conectar con el proveedor de IA. Revisá la conexión."
        ) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureProviderError(
            "El proveedor de IA devolvió una respuesta inválida."
        ) from exc


def call_minimax(config: CaptureConfig, messages: list[dict]) -> tuple[str, dict]:
    """Llama a MiniMax y devuelve (contenido, usage)."""

    if not config.enabled:
        raise CaptureDisabledError(config.disabled_reason() or "La captura con IA no está habilitada.")

    url = f"{config.base_url}/chat/completions"
    payload = {
        "model": config.model,
        "messages": messages,
        # El pensamiento adaptativo consume parte del presupuesto de salida.
        # Con 4000 el modelo podía gastarlo pensando y devolver content vacío.
        "max_completion_tokens": 32768,
        "reasoning_effort": "low",
        # MiniMax-M3.1-Flash exige pensamiento adaptativo: rechaza
        # thinking.type=disabled con HTTP 400.
        "thinking": {"type": "adaptive"},
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = _post_json(url, headers, payload, config.timeout_seconds)

    base_resp = response.get("base_resp") if isinstance(response, dict) else None
    if isinstance(base_resp, dict):
        code = base_resp.get("status_code")
        if code not in (None, 0, "0"):
            message = base_resp.get("status_msg") or f"status_code {code}"
            raise CaptureProviderError(f"MiniMax rechazó la solicitud: {message}")

    try:
        choice = response["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise CaptureProviderError(
            "El proveedor de IA no devolvió una respuesta utilizable."
        ) from exc

    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    # Con pensamiento adaptativo el modelo puede dejar content vacío y volcar
    # el JSON en reasoning_content. Se usa solo si parece el JSON esperado.
    if not isinstance(content, str) or not content.strip():
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and '"lineas"' in reasoning:
            content = reasoning
    if not isinstance(content, str) or not content.strip():
        finish_reason = (
            choice.get("finish_reason") if isinstance(choice, dict) else None
        )
        detail = f" (finish_reason={finish_reason})" if finish_reason else ""
        raise CaptureProviderError(
            f"El proveedor de IA devolvió una respuesta vacía{detail}. "
            "Probá con una foto más chica o reportá el problema."
        )
    usage = response.get("usage") if isinstance(response, dict) else None
    return content, usage if isinstance(usage, dict) else {}


# ----------------------------------------------------------------------
# Punto de entrada
# ----------------------------------------------------------------------


def extract_capture(
    data: bytes,
    filename: str,
    mime: str | None,
    *,
    load_lines: list,
    order_number=None,
    order_date: date | None = None,
    client_name: str | None = None,
    config: CaptureConfig | None = None,
) -> CaptureProposal:
    """Lee una foto/PDF y devuelve la propuesta validada.

    No escribe nada. Los errores de entrada y de proveedor se distinguen para
    que la pantalla pueda mostrar un mensaje util.
    """

    config = config or load_capture_config()
    if not config.enabled:
        raise CaptureDisabledError(config.disabled_reason() or "La captura con IA no está habilitada.")
    if not load_lines:
        raise CaptureInputError("La orden no tiene líneas para precargar.")

    media = prepare_media(data, mime or "", config=config)
    context = build_order_context(
        load_lines,
        order_number=order_number,
        order_date=order_date,
        client_name=client_name,
    )
    content, usage = call_minimax(config, build_messages(context, media))
    payload = _extract_json(content)
    lines, warnings = validate_extraction(payload, load_lines=load_lines)

    return CaptureProposal(
        schema_version=SCHEMA_VERSION,
        order_number=str(payload.get("orden_numero") or "") or None,
        date=parse_capture_date(payload.get("fecha")),
        client=str(payload.get("cliente_principal") or "").strip() or None,
        lines=lines,
        warnings=warnings,
        provider=config.provider,
        model=config.model,
        file_sha256=file_sha256(data),
        usage=usage,
    )
