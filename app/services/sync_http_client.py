"""Cliente HTTPS del agente de sincronizacion (#804).

Todas las conexiones salen de la fabrica. El token de maquina viaja en la
cabecera Authorization y nunca se registra en logs.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse


class SyncHttpError(RuntimeError):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Sync HTTP {status}: {body[:500]}")


class SyncHttpClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: int = 30,
        opener=None,
        allow_http: bool | None = None,
        ca_file: str | None = None,
    ):
        parsed = urlparse((base_url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("FEMAG_SYNC_BASE_URL debe ser una URL http(s) válida.")
        allow_http = (
            os.getenv("FEMAG_SYNC_ALLOW_HTTP", "").strip() == "1"
            if allow_http is None
            else allow_http
        )
        if parsed.scheme != "https" and not allow_http:
            raise ValueError(
                "FEMAG_SYNC_BASE_URL debe usar HTTPS. "
                "Para pruebas locales definí FEMAG_SYNC_ALLOW_HTTP=1."
            )
        if not (token or "").strip():
            raise ValueError("FEMAG_SYNC_API_TOKEN es obligatorio.")
        self.base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        self.token = token.strip()
        self.timeout = int(timeout)
        self._opener = opener or urllib.request.build_opener()
        self._ssl_context = None
        if ca_file:
            self._ssl_context = ssl.create_default_context(cafile=ca_file)

    def _request(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        kwargs = {"timeout": self.timeout}
        if self._ssl_context is not None:
            kwargs["context"] = self._ssl_context
        try:
            with self._opener.open(request, **kwargs) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise SyncHttpError(exc.code, body) from exc
        except urllib.error.URLError as exc:
            raise SyncHttpError(0, str(exc.reason)) from exc

    def post_snapshot(self, snapshot: dict) -> dict:
        return self._request("POST", "/api/sync/v1/snapshots/orders", snapshot)

    def post_event(self, event: dict) -> dict:
        return self._request("POST", "/api/sync/v1/events", event)

    def get_events(self, cursor: int = 0, limit: int = 50) -> dict:
        query = urllib.parse.urlencode({"cursor": int(cursor), "limit": int(limit)})
        return self._request("GET", f"/api/sync/v1/events?{query}")

    def ack_event(self, event_id: str, result: str, error: str | None = None) -> dict:
        payload = {"result": result}
        if error:
            payload["error"] = str(error)[:1000]
        return self._request(
            "POST",
            f"/api/sync/v1/events/{urllib.parse.quote(event_id)}/ack",
            payload,
        )

    def get_status(self) -> dict:
        return self._request("GET", "/api/sync/v1/status")
