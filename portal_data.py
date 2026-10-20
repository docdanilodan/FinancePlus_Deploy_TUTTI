"""Read models built from existing, individually authorized MASTER API calls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone

from master_gateway import GatewayError

STAFF_ROLES = {"admin", "professional"}
FILTER_KEYS = ("q", "client", "collaborator", "referrer", "manager", "status")


def positive_id(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise GatewayError(404, "NOT_FOUND", "Cliente non disponibile.") from None
    if number < 1 or number > 9007199254740991:
        raise GatewayError(404, "NOT_FOUND", "Cliente non disponibile.")
    return number


def items(response):
    rows = response.get("items")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise GatewayError(502, "INVALID_RESPONSE", "Il MASTER ha restituito un elenco non valido.")
    return rows


def capabilities(gateway, token, principal):
    if principal.get("role") not in STAFF_ROLES:
        return {"intake": principal.get("can_upload") is True, "client_creation": False, "owner_tools": False, "new_credit_analysis": False}
    return gateway.get("/v1/capabilities", token)


def client_bundle(gateway, token, principal, client_id):
    client_id = positive_id(client_id)
    if principal.get("role") in STAFF_ROLES and principal.get("status") == "active":
        result = gateway.get(f"/v1/clients/{client_id}", token)
        client = result.get("client")
        if not isinstance(client, dict) or client.get("id") != client_id:
            raise GatewayError(502, "INVALID_CLIENT", "La risposta non corrisponde al cliente richiesto.")
        result["restricted"] = False
        result["documents_loaded"] = len(result.get("documents", [])) < 100
        result["tasks_loaded"] = len(result.get("tasks", [])) < 100
        result["requests_loaded"] = len(result.get("requests", [])) < 100
        return result
    # A client/collaborator never calls the internal Client 360 endpoint.
    practices = items(gateway.get("/v1/portal/practices", token))
    authorized = [p for p in practices if p.get("client_id") == client_id]
    if not authorized:
        raise GatewayError(404, "NOT_FOUND", "Cliente non disponibile nel tuo perimetro.")
    return {"client": {"id": client_id, "name": authorized[0].get("client_name", ""), "vat": "", "sector": ""}, "requests": authorized, "documents": [], "tasks": [], "analysis": None, "notes": [], "restricted": True, "documents_loaded": False, "tasks_loaded": False, "source": "Pratiche autorizzate dal MASTER"}


def snapshot(gateway, token, principal):
    role = principal.get("role")
    result = {"companies": [], "practices": [], "documents": [], "tasks": [], "bundles": [], "complete": True,
              "documents_loaded": False, "tasks_loaded": False, "source": "SMART F+ · proiezione cloud autorizzata",
              "read_at": datetime.now(timezone.utc).isoformat(), "role_fields_available": [], "warnings": []}
    if principal.get("status") == "pending":
        result["pending"] = True
        return result
    if role not in STAFF_ROLES:
        practices = items(gateway.get("/v1/portal/practices", token))
        companies = {}
        for p in practices:
            cid = positive_id(p.get("client_id"))
            companies[cid] = {"id": cid, "name": p.get("client_name", ""), "vat": "", "sector": ""}
        result.update(companies=sorted(companies.values(), key=lambda c: c["name"].casefold()), practices=practices)
    else:
        # This endpoint caps clients at 500. Verify against an independent total;
        # never silently label a capped response as the full authorized portfolio.
        counts = gateway.get("/v1/dashboard", token)
        companies = items(gateway.get("/v1/clients", token))
        ids = [positive_id(c.get("id")) for c in companies]
        if len(ids) != len(set(ids)):
            raise GatewayError(502, "DUPLICATE_RESPONSE", "Elenco clienti incoerente. Aggiorna prima di esportare.")
        result["companies"] = companies
        result["server_counts"] = counts
        result["complete"] = len(companies) == counts.get("clients") and len(companies) < 500
        if not result["complete"]:
            result["warnings"].append("L'elenco restituito dal servizio è parziale. L'esportazione completa resta sospesa.")
        def read(cid):
            return client_bundle(gateway, token, principal, cid)
        # Only reads; bounded concurrency, no cache survives this HTTP request.
        with ThreadPoolExecutor(max_workers=6) as executor:
            bundles = list(executor.map(read, ids))
        assignments = {}
        if role == "admin":
            admin_practices = items(gateway.get("/v1/admin/practices", token))
            assignments = {p.get("id"): p.get("assigned_collaborators", []) for p in admin_practices}
            result["role_fields_available"].append("collaborator")
        for bundle in bundles:
            company = bundle["client"]
            for raw in bundle.get("requests", []):
                practice = dict(raw, client_id=company["id"], client_name=company.get("name", ""))
                if practice.get("id") in assignments:
                    practice["assigned_collaborators"] = assignments[practice["id"]]
                result["practices"].append(practice)
            result["documents"].extend(dict(row, client_id=company["id"], client_name=company.get("name", "")) for row in bundle.get("documents", []))
            result["tasks"].extend(dict(row, client_id=company["id"], client_name=company.get("name", "")) for row in bundle.get("tasks", []))
        result["bundles"] = bundles
        result["complete"] = result["complete"] and len(result["practices"]) == counts.get("requests")
        result["documents_loaded"] = len(result["documents"]) == counts.get("documents")
        result["tasks_loaded"] = all(len(b.get("tasks", [])) < 100 for b in bundles)
        if not result["complete"] and not result["warnings"]:
            result["warnings"].append("Le pratiche ricevute non coprono il totale del MASTER. Nessun elenco parziale verrà presentato come completo.")
    result["all_companies_count"] = len(result["companies"])
    result["all_practices_count"] = len(result["practices"])
    # A future gateway extension can expose this already projected field. It is
    # available only when explicitly present, never inferred from a contact.
    if any(isinstance(p.get("manager_name"), str) and p["manager_name"].strip() for p in result["practices"]):
        result["role_fields_available"].append("manager")
    return result


def parse_filters(query):
    return {key: str(query.get(key, ""))[:120].strip() for key in FILTER_KEYS}


def filter_snapshot(data, filters):
    result = dict(data)
    role_fields = set(data.get("role_fields_available", []))
    for field in ("collaborator", "referrer", "manager"):
        if filters.get(field) and field not in role_fields:
            raise GatewayError(422, "FILTER_UNAVAILABLE", "Questo filtro non è ancora trasmesso dal MASTER per il tuo account.")
    q = filters.get("q", "").casefold()
    company_by_id = {str(c["id"]): c for c in data["companies"]}
    selected_practices = []
    for practice in data["practices"]:
        company = company_by_id.get(str(practice.get("client_id")), {})
        if filters.get("client") and str(practice.get("client_id")) != filters["client"]:
            continue
        if filters.get("status") and str(practice.get("status", "")) != filters["status"]:
            continue
        if filters.get("collaborator") and not any(str(p.get("id")) == filters["collaborator"] for p in practice.get("assigned_collaborators", []) if isinstance(p, dict)):
            continue
        if filters.get("manager") and str(practice.get("manager_name", "")) != filters["manager"]:
            continue
        if filters.get("referrer") and str(practice.get("referrer_id", "")) != filters["referrer"]:
            continue
        haystack = " ".join(str(company.get(key, "")) for key in ("name", "vat")) + " " + " ".join(str(practice.get(key, "")) for key in ("title", "purpose", "institution"))
        if q and q not in haystack.casefold():
            continue
        selected_practices.append(practice)
    selected_ids = {p["client_id"] for p in selected_practices}
    practice_filter = any(filters.get(k) for k in ("status", "collaborator", "manager", "referrer"))
    selected_companies = []
    for company in data["companies"]:
        if filters.get("client") and str(company["id"]) != filters["client"]:
            continue
        if practice_filter and company["id"] not in selected_ids:
            continue
        match_company = not q or q in (str(company.get("name", "")) + " " + str(company.get("vat", ""))).casefold()
        if not match_company and company["id"] not in selected_ids:
            continue
        selected_companies.append(company)
    result.update(companies=selected_companies, practices=selected_practices)
    result["filter_source"] = data
    return result
