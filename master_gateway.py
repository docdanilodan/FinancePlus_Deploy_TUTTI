"""Server-side client of the existing SMART F+ / LELE_K_PLUS API.

No financial database, scoring or credential replication. Access tokens stay in
server memory; every data request is authorized again by the canonical gateway.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_API = "https://br-quiet-wildflower-b2ltifhj-smartfmobile.compute.c-6.eu-central-1.aws.neon.tech"
MAX_FILE_BYTES = 16 * 1024 * 1024


class GatewayError(Exception):
    def __init__(self, status=503, code="SERVICE_UNAVAILABLE", message="Il collegamento al MASTER non è disponibile. Riprova tra poco."):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Gateway:
    def __init__(self, base_url=None, timeout=20):
        self.base_url = (base_url or os.getenv("MASTER_API_BASE_URL", DEFAULT_API)).rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("MASTER_API_BASE_URL must be an HTTPS origin without credentials")
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, token=None, payload=None, *, data=None, headers=None, binary=False):
        if not path.startswith("/v1/") or any(c in path for c in ("\r", "\n", "#")):
            raise ValueError("Only explicit v1 API paths are allowed")
        request_headers = {"Accept": "application/json", "User-Agent": "FinancePlus-Web/4.1"}
        if token:
            request_headers["Authorization"] = "Bearer " + token
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        request = Request(self.base_url + path, data=data, method=method, headers=request_headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                limit = 32 * 1024 * 1024 if binary else 8 * 1024 * 1024
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise GatewayError(502, "RESPONSE_TOO_LARGE", "La risposta supera il limite previsto. Nessun dato è stato modificato.")
                if binary:
                    return body, response.headers.get("Content-Type", "application/octet-stream")
                result = json.loads(body.decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("Invalid API response")
                return result
        except HTTPError as exc:
            try:
                result = json.loads(exc.read(8192).decode("utf-8"))
                code = str(result.get("code", "GATEWAY_ERROR"))[:80]
                message = str(result.get("message", "Operazione non disponibile."))[:500]
            except (ValueError, UnicodeError):
                code, message = "GATEWAY_ERROR", "Operazione non disponibile. Riprova o verifica l'accesso."
            raise GatewayError(exc.code, code, message) from None
        except (URLError, TimeoutError, OSError, ValueError, UnicodeError):
            raise GatewayError() from None

    def get(self, path, token):
        return self.request("GET", path, token)

    def post(self, path, token=None, payload=None, **kwargs):
        return self.request("POST", path, token, payload, **kwargs)

    def login(self, username, password):
        result = self.post("/v1/accounts/session", payload={"username": username.strip().lower(), "password": password})
        token = result.get("access_token")
        ttl = result.get("expires_in")
        if not isinstance(token, str) or not 20 <= len(token) <= 512 or not isinstance(ttl, (int, float)) or ttl <= 0:
            raise GatewayError(502, "INVALID_SESSION", "Il servizio non ha restituito una sessione valida.")
        principal = self.get("/v1/me", token)
        if principal.get("role") not in {"admin", "professional", "client", "collaborator"} or principal.get("status") not in {"active", "pending"}:
            raise GatewayError(403, "FORBIDDEN", "Account non autorizzato.")
        return token, min(int(ttl), 900), principal


@dataclass
class SessionEntry:
    token: str
    expires: float


class TokenVault:
    """Ephemeral auth cache for the single-worker Uvicorn deployment.

    Losing an entry only requires logging in again. It never grants fallback
    permissions. No password, token, client record or analysis is serialized.
    """
    def __init__(self, max_sessions=2000):
        self._entries = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions

    def put(self, token, ttl):
        with self._lock:
            now = time.monotonic()
            self._entries = {k: v for k, v in self._entries.items() if v.expires > now}
            if len(self._entries) >= self.max_sessions:
                raise GatewayError(503, "SESSION_CAPACITY", "Accesso temporaneamente occupato. Riprova tra poco.")
            key = secrets.token_urlsafe(32)
            self._entries[key] = SessionEntry(token, now + min(ttl, 900))
            return key

    def get(self, key):
        if not isinstance(key, str):
            return None
        with self._lock:
            value = self._entries.get(key)
            if value and value.expires > time.monotonic():
                return value.token
            self._entries.pop(key, None)
            return None

    def remove(self, key):
        if isinstance(key, str):
            with self._lock:
                self._entries.pop(key, None)
