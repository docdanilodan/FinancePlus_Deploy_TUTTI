from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient
import pytest

from master_gateway import GatewayError
from portal_special_one import register_special_one


PAGE = "/app/clienti/2/prepara-analisi"
CANONICAL = "/v1/admin/special-one/clients/2"


class GatewayDouble:
    def __init__(self):
        self.reads = []
        self.preflights = []
        self.capabilities = {"client_creation": True}
        self.canonical_error = None
        self.corrupt_response = None
        self.bundle = {
            "client": {"id": "2", "name": "Azienda <riservata>", "vat": "IT00000000000", "sector": "Servizi"},
            "documents": [
                {"id": 11, "client_id": 2, "title": "Bilancio <riservato>", "category": "Bilanci", "date": "2025-12-31"},
                {"id": "12", "client_id": "2", "title": "Situazione contabile", "category": "Contabilità", "date": None},
                {"id": -13, "client_id": 2, "title": "Documento storico", "category": "Archivio", "date": None},
            ],
            "analysis": {"source": "MASTER", "summary": "Dati già salvati"},
            "capabilities": {"saved_analysis": True, "new_analysis": False, "source": "Dati sincronizzati dal MASTER"},
        }

    def get(self, path, token):
        assert token == "test-token"
        self.reads.append(path)
        if path == "/v1/capabilities":
            return deepcopy(self.capabilities)
        assert path == CANONICAL
        if self.canonical_error:
            raise self.canonical_error
        return deepcopy(self.bundle)

    def post(self, path, token, payload):
        assert path == "/v1/admin/special-one/preflight" and token == "test-token"
        self.preflights.append(deepcopy(payload))
        result = {
            "status": "DOCUMENTS_VERIFIED", "client_id": payload["client_id"],
            "selected_documents": [
                {"id": row["id"], "title": row["title"], "category": row["category"]}
                for row in self.bundle["documents"] if int(row["id"]) in payload["document_ids"]
            ],
            "sections": list(payload["sections"]), "new_analysis": False,
            "notice": "Nessun rating o report generato.",
        }
        return self.corrupt_response(result) if self.corrupt_response else result


@pytest.fixture
def setup():
    gateway = GatewayDouble()
    user = SimpleNamespace(role="admin")
    principal = {"status": "active"}
    app = FastAPI()

    @app.exception_handler(GatewayError)
    async def gateway_error(request, error):
        return JSONResponse({"code": error.code, "detail": error.message}, status_code=error.status)

    def access(request, staff=False):
        if staff and user.role not in {"admin", "professional"}:
            raise HTTPException(403)
        return user, "test-token", principal, gateway

    def verify_csrf(request, token):
        if token != "csrf-test":
            raise HTTPException(403)

    register_special_one(app, {
        "access": access,
        "render": lambda title, subtitle, body, request, active: HTMLResponse(body),
        "field": lambda request: '<input type="hidden" name="csrf_token" value="csrf-test">',
        "verify_csrf": verify_csrf,
    })
    with TestClient(app) as client:
        yield client, gateway, user, principal


def valid_form(**changes):
    fields = {
        "csrf_token": "csrf-test", "confirmed": "yes",
        "document_ids": ["11", "12"], "sections": ["bilanci", "dscr"],
    }
    fields.update(changes)
    return fields


def submit(client, fields=None):
    return client.post(
        PAGE, content=urlencode(fields if fields is not None else valid_form(), doseq=True),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


@pytest.mark.parametrize("blocked", ["professional", "client", "collaborator", "inactive", "capability_missing", "truthy_capability", "canonical_denied"])
def test_owner_gate_requires_role_capability_and_canonical_permission(setup, blocked):
    client, gateway, user, principal = setup
    if blocked in {"professional", "client", "collaborator"}:
        user.role = blocked
    elif blocked == "inactive":
        principal["status"] = "pending"
    elif blocked == "capability_missing":
        gateway.capabilities = {}
    elif blocked == "truthy_capability":
        gateway.capabilities["client_creation"] = "true"
    else:
        gateway.canonical_error = GatewayError(403, "SPECIAL_ONE_ADMIN_ONLY", "Account non abilitato.")
    assert client.get(PAGE).status_code == 403
    assert submit(client).status_code == 403
    assert gateway.preflights == []


def test_form_uses_saved_data_and_disables_unsupported_document_ids(setup):
    client, gateway, _, _ = setup
    response = client.get(PAGE)
    assert response.status_code == 200
    assert "Azienda &lt;riservata&gt;" in response.text
    assert "Bilancio &lt;riservato&gt;" in response.text
    assert 'name="document_ids" value="11"' in response.text
    assert 'name="document_ids" value="12"' in response.text
    assert 'value="-13"' not in response.text
    assert '<input type="checkbox" disabled>' in response.text
    assert '/app/documenti/-13/anteprima' in response.text
    assert response.text.count('name="sections"') == 8
    assert "new_analysis:false" in response.text
    assert '/app/clienti/2?tab=analisi' in response.text
    assert "DOCUMENTS_VERIFIED" not in response.text
    assert gateway.reads == ["/v1/capabilities", CANONICAL]
    gateway.bundle["documents"] = [
        {"id": index, "client_id": 2, "title": f"Documento {index}", "category": "Bilanci", "date": None}
        for index in range(1, 151)
    ]
    limited = client.get(PAGE)
    assert limited.status_code == 200 and "Limite dell’elenco raggiunto" in limited.text
    assert "L’archivio può contenerne altri" in limited.text


def test_no_selectable_documents_and_missing_saved_analysis_are_explicit(setup):
    client, gateway, _, _ = setup
    gateway.bundle["documents"] = gateway.bundle["documents"][-1:]
    gateway.bundle["analysis"] = None
    response = client.get(PAGE)
    assert response.status_code == 200
    assert 'action="' + PAGE + '"' not in response.text
    assert "La selezione non è ancora disponibile" in response.text
    assert "Nessuna analisi salvata disponibile" in response.text
    assert '/app/clienti/2?tab=analisi' not in response.text


def test_csrf_explicit_confirmation_and_singleton_fields_are_required(setup):
    client, gateway, _, _ = setup
    assert submit(client, valid_form(csrf_token="wrong")).status_code == 403
    assert submit(client, valid_form(confirmed="")).status_code == 422
    assert submit(client, valid_form(csrf_token=["csrf-test", "csrf-test"])).status_code == 400
    assert submit(client, valid_form(client_id="99")).status_code == 400
    assert gateway.preflights == []
    assert CANONICAL not in gateway.reads


@pytest.mark.parametrize("changes", [
    {"document_ids": []},
    {"document_ids": ["-13"]},
    {"document_ids": ["11", "11"]},
    {"document_ids": ["9007199254740992"]},
    {"document_ids": ["11.0"]},
    {"document_ids": [str(index) for index in range(1, 82)]},
    {"sections": []},
    {"sections": ["bilanci", "analisi_nuova"]},
    {"sections": ["bilanci", "bilanci"]},
])
def test_only_unique_positive_safe_ids_and_whitelisted_sections_reach_preflight(setup, changes):
    client, gateway, _, _ = setup
    assert submit(client, valid_form(**changes)).status_code == 422
    assert gateway.preflights == []
    assert CANONICAL not in gateway.reads


def test_submission_rechecks_membership_in_the_current_client_bundle(setup):
    client, gateway, _, _ = setup
    assert client.get(PAGE).status_code == 200
    gateway.bundle["documents"] = gateway.bundle["documents"][1:]
    removed = submit(client)
    assert removed.status_code == 422
    assert "fascicolo aggiornato" in removed.text
    assert gateway.reads.count(CANONICAL) == 2
    assert gateway.preflights == []
    assert submit(client, valid_form(document_ids=["999"])).status_code == 422
    assert gateway.preflights == []


@pytest.mark.parametrize("invalid", ["wrong_client", "foreign_document", "duplicate_document", "new_analysis_enabled"])
def test_incoherent_canonical_bundle_never_reveals_or_verifies_records(setup, invalid):
    client, gateway, _, _ = setup
    if invalid == "wrong_client":
        gateway.bundle["client"]["id"] = 9
    elif invalid == "foreign_document":
        gateway.bundle["documents"][0]["client_id"] = 9
    elif invalid == "duplicate_document":
        gateway.bundle["documents"].append(deepcopy(gateway.bundle["documents"][0]))
    else:
        gateway.bundle["capabilities"]["new_analysis"] = True
    response = client.get(PAGE)
    assert response.status_code == 502
    assert "Bilancio" not in response.text and "Azienda" not in response.text
    assert submit(client).status_code == 502
    assert gateway.preflights == []


def test_success_shows_only_the_verified_document_selection(setup):
    client, gateway, _, _ = setup
    saved = deepcopy(gateway.bundle["analysis"])
    response = submit(client)
    assert response.status_code == 200
    assert "DOCUMENTS_VERIFIED" in response.text and "new_analysis:false" in response.text
    assert "Nessuna nuova analisi, rating o report è stato generato" in response.text
    assert "Bilancio &lt;riservato&gt;" in response.text
    assert "/app/clienti/2?tab=analisi" in response.text
    assert gateway.preflights == [{
        "client_id": 2, "document_ids": [11, 12], "sections": ["bilanci", "dscr"], "confirmed": True,
    }]
    assert gateway.reads == ["/v1/capabilities", CANONICAL]
    assert gateway.bundle["analysis"] == saved


@pytest.mark.parametrize("invalid", ["wrong_status", "wrong_client", "wrong_sections", "new_analysis_true", "missing_document", "extra_document", "duplicate_document"])
def test_only_a_complete_matching_preflight_response_is_displayed_as_verified(setup, invalid):
    client, gateway, _, _ = setup

    def corrupt(result):
        if invalid == "wrong_status":
            result["status"] = "COMPLETED"
        elif invalid == "wrong_client":
            result["client_id"] = 9
        elif invalid == "wrong_sections":
            result["sections"] = ["dossier"]
        elif invalid == "new_analysis_true":
            result["new_analysis"] = True
        elif invalid == "missing_document":
            result["selected_documents"].pop()
        elif invalid == "extra_document":
            result["selected_documents"].append({"id": 99, "title": "Estraneo", "category": "Altro"})
        else:
            result["selected_documents"][1] = result["selected_documents"][0]
        return result

    gateway.corrupt_response = corrupt
    response = submit(client)
    assert response.status_code == 502
    assert response.json()["code"] == "PREFLIGHT_UNVERIFIED"
    assert "DOCUMENTS_VERIFIED" not in response.text
    assert "Bilancio" not in response.text
    assert len(gateway.preflights) == 1
