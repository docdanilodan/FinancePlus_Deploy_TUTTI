"""Deterministic, in-memory MASTER contract double. Never opens a connection.

All companies, people, identifiers, credentials and documents are synthetic.
Unknown routes fail the test so production network access cannot be accidental.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import uuid

from master_gateway import Gateway, GatewayError


class FakeMaster(Gateway):
    def __init__(self):
        self.base_url = "https://master.example.invalid"
        self._lock = threading.Lock()
        self.calls = []
        self.tokens = {}
        self.revoked = set()
        self.uploads = {}
        self.client_requests = {}
        self.receipt_missing = False
        self.reported_counts = None
        self.capability_flags = {"intake": True, "client_creation": True, "approval_queue": True}
        self.accounts = {
            role + "@example.invalid": {
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "financeplus-qa-" + role)),
                "role": role, "status": "active", "name": "QA " + role,
                "email": role + "@example.invalid", "can_upload": role != "collaborator",
            }
            for role in ("admin", "professional", "client", "collaborator")
        }
        self.set_portfolio(2)

    def set_portfolio(self, count):
        self.companies = []
        self.bundles = {}
        for index in range(count):
            ident = 1001 if index == 0 else 2002 if index == 1 else 3000 + index
            name = "Azienda Alfa QA" if index == 0 else "Azienda Beta QA" if index == 1 else f"Impresa QA {index:04d}"
            company = {"id": ident, "name": name, "vat": f"{index + 1:011d}", "sector": "Settore QA"}
            practice = {
                "id": ident + 10000, "client_id": ident, "client_name": name,
                "title": f"Richiesta QA {index:04d}", "status": "IN_ANALISI" if index % 2 == 0 else "DOCUMENTI_MANCANTI",
                "purpose": "Investimenti QA", "amount": 1000 + index,
                "institution": "Istituto sintetico", "manager_name": "Gestore Alfa" if index % 2 == 0 else "Gestore Beta",
                "assigned_collaborators": [{"id": self.accounts["collaborator@example.invalid"]["id"], "name": "Collaboratore QA"}] if index == 1 else [],
                "document_requests": [],
            }
            self.companies.append(company)
            self.bundles[ident] = {
                "client": company, "requests": [practice], "documents": [], "tasks": [], "notes": [],
                "analysis": {"summary": "Esito sintetico ricevuto dal MASTER QA.", "generated_at": "2026-10-20T10:00:00Z"} if index == 0 else None,
                "source": "MASTER sintetico per collaudo",
            }

    def clear_calls(self):
        with self._lock:
            self.calls.clear()

    @property
    def writes(self):
        return [call for call in self.calls if call["method"] != "GET"]

    def principal(self, token):
        username = self.tokens.get(token)
        if not username or token in self.revoked:
            raise GatewayError(401, "SESSION_REVOKED", "Sessione QA revocata.")
        return self.accounts[username]

    def request(self, method, path, token=None, payload=None, *, data=None, headers=None, binary=False):
        call = {"method": method, "path": path, "token": token, "payload": copy.deepcopy(payload), "headers": dict(headers or {}), "binary": binary}
        if data is not None:
            call["data_size"] = len(data)
            call["data_sha256"] = hashlib.sha256(data).hexdigest()
        with self._lock:
            self.calls.append(call)
        if method == "POST" and path == "/v1/accounts/session":
            username = (payload or {}).get("username", "")
            if username not in self.accounts or (payload or {}).get("password") != "QA-only-password-2026":
                raise GatewayError(401, "INVALID_CREDENTIALS", "Credenziali QA errate.")
            generated = "MASTER_TOKEN_ONLY_IN_SERVER_MEMORY_" + username
            self.tokens[generated] = username
            return {"access_token": generated, "expires_in": 900}
        if method == "POST" and path == "/v1/accounts/register":
            return {"status": "pending", "id": str(uuid.uuid4())}
        principal = self.principal(token)
        staff = principal["role"] in {"admin", "professional"} and principal["status"] == "active"
        if method == "GET" and path == "/v1/me":
            return copy.deepcopy(principal)
        if method == "GET" and path == "/v1/portal/practices":
            permitted = {1001} if principal["role"] == "client" else {2002} if principal["role"] == "collaborator" else set(self.bundles)
            return {"items": copy.deepcopy([p for cid, bundle in self.bundles.items() if cid in permitted for p in bundle["requests"]])}
        if path == "/v1/dashboard" or path.startswith("/v1/clients") or path.startswith("/v1/admin/") or path == "/v1/capabilities":
            if not staff:
                raise GatewayError(403, "FORBIDDEN", "Endpoint interno fuori dal perimetro QA.")
        if method == "GET" and path == "/v1/dashboard":
            return copy.deepcopy(self.reported_counts or {"clients": len(self.companies), "requests": sum(len(b["requests"]) for b in self.bundles.values()), "documents": sum(len(b["documents"]) for b in self.bundles.values())})
        if method == "GET" and path == "/v1/clients":
            return {"items": copy.deepcopy(self.companies[:500])}
        if method == "GET" and path.startswith("/v1/clients/"):
            try:
                ident = int(path.rsplit("/", 1)[1])
            except ValueError:
                raise GatewayError(404, "NOT_FOUND", "Cliente QA assente.") from None
            if ident not in self.bundles:
                raise GatewayError(404, "NOT_FOUND", "Cliente QA assente.")
            return copy.deepcopy(self.bundles[ident])
        if method == "GET" and path == "/v1/admin/practices":
            if principal["role"] != "admin":
                raise GatewayError(403)
            return {"items": copy.deepcopy([p for bundle in self.bundles.values() for p in bundle["requests"]])}
        if method == "GET" and path == "/v1/capabilities":
            return copy.deepcopy(self.capability_flags)
        if method == "GET" and path == "/v1/intakes":
            return {"items": copy.deepcopy(list(self.uploads.values()))}
        if method == "POST" and path == "/v1/intakes":
            key = (headers or {}).get("x-idempotency-key")
            digest = hashlib.sha256(data or b"").hexdigest()
            if key in self.uploads and self.uploads[key]["sha256"] != digest:
                raise GatewayError(409, "IDEMPOTENCY_CONFLICT", "Chiave QA già usata con un file diverso.")
            if self.receipt_missing:
                return {}
            self.uploads.setdefault(key, {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)), "status": "UPLOADED", "filename": (headers or {}).get("x-filename"), "document_kind": (headers or {}).get("x-document-kind"), "sha256": digest, "revision": 1})
            return copy.deepcopy(self.uploads[key])
        if method == "POST" and path == "/v1/client-requests":
            key = payload["idempotency_key"]
            self.client_requests.setdefault(key, {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)), "status": "PENDING", "name": payload["name"], "master_client_id": None})
            return copy.deepcopy(self.client_requests[key])
        if method == "GET" and path == "/v1/client-requests":
            return {"items": copy.deepcopy(list(self.client_requests.values()))}
        raise AssertionError(f"Unexpected fake MASTER call: {method} {path}")
