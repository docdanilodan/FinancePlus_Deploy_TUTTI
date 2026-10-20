from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
import pytest

from portal_activities import register_activities


class GatewayDouble:
    def __init__(self):
        self.reads = []
        self.writes = []
        self.activities = [{
            "id": "timeline:5", "client_id": 2, "practice_id": 91,
            "kind": "call", "description": "Confronto <riservato>",
            "status": "Programmato", "event_date": "2026-10-22 14:30:00",
            "due_date": "", "fingerprint": "a" * 64,
        }]
        self.commands = []
        self.immediate_status = "COMPLETED"
        self.persisted_status = "PENDING"

    def get(self, path, token):
        assert token == "test-token"
        self.reads.append(path)
        if path.endswith("/activity-commands"):
            return {"items": deepcopy(self.commands)}
        assert path == "/v1/portal/clients/2/activities"
        return {"items": deepcopy(self.activities)}

    def post(self, path, token, payload):
        assert path == "/v1/admin/clients/2/activities" and token == "test-token"
        self.writes.append(deepcopy(payload))
        self.commands = [{"id": payload["command_id"], "status": self.persisted_status, "result": None}]
        return {"id": payload["command_id"], "status": self.immediate_status, "result": "timeline:8"}


@pytest.fixture
def setup():
    gateway = GatewayDouble()
    user = SimpleNamespace(role="admin")
    principal = {"status": "active"}
    app = FastAPI()

    def access(request, staff=False):
        if staff and user.role not in {"admin", "professional"}:
            raise HTTPException(403)
        return user, "test-token", principal, gateway

    def verify_csrf(request, token):
        if token != "csrf-test":
            raise HTTPException(403)

    register_activities(app, {
        "access": access,
        "render": lambda title, subtitle, body, request, active: HTMLResponse(body),
        "field": lambda request: '<input type="hidden" name="csrf_token" value="csrf-test">',
        "verify_csrf": verify_csrf,
    })
    return TestClient(app), gateway, user, principal


def create_form(**changes):
    result = {
        "csrf_token": "csrf-test", "command_id": str(uuid4()),
        "confirmed": "yes", "action": "create", "kind": "call",
        "description": "Appuntamento di prova", "status": "Programmato",
        "event_date": "2026-10-22T14:30", "due_date": "",
    }
    result.update(changes)
    return result


def test_pending_receipt_is_reread_even_when_post_claims_completed(setup):
    client, gateway, _, _ = setup
    data = create_form()
    response = client.post("/app/clienti/2/attivita", data=data)
    assert response.status_code == 200
    assert "Comando in attesa" in response.text
    assert "Comando completato" not in response.text
    assert gateway.writes[0]["command_id"] == data["command_id"]
    assert gateway.writes[0]["event_date"] == "2026-10-22 14:30:00"
    assert gateway.writes[0]["confirmed"] is True
    assert gateway.reads[-1] == "/v1/admin/clients/2/activity-commands"


@pytest.mark.parametrize("role", ["professional", "client", "collaborator"])
def test_only_admin_can_prepare_or_submit_commands(setup, role):
    client, gateway, user, _ = setup
    user.role = role
    assert client.get("/app/clienti/2/attivita/nuova").status_code == 403
    assert client.post("/app/clienti/2/attivita", data=create_form()).status_code == 403
    assert gateway.writes == []
    response = client.get("/app/clienti/2/attivita")
    assert response.status_code == 200
    assert "Confronto &lt;riservato&gt;" in response.text
    assert "/modifica" not in response.text and "/nuova?" not in response.text
    assert not any(path.endswith("/activity-commands") for path in gateway.reads)


def test_csrf_and_explicit_confirmation_precede_mutation(setup):
    client, gateway, _, _ = setup
    assert client.post("/app/clienti/2/attivita", data=create_form(csrf_token="wrong")).status_code == 403
    assert client.post("/app/clienti/2/attivita", data=create_form(confirmed="")).status_code == 422
    assert gateway.writes == []


@pytest.mark.parametrize("changes", [
    {"event_date": "2026-02-30T10:30"},
    {"event_date": "2026-10-22"},
    {"status": "Evasa"},
    {"action": "delete"},
    {"description": "€" * 8000},
])
def test_invalid_dates_status_delete_or_payload_size_never_reach_gateway(setup, changes):
    client, gateway, _, _ = setup
    assert client.post("/app/clienti/2/attivita", data=create_form(**changes)).status_code == 422
    assert gateway.writes == []


def test_update_checks_current_fingerprint_and_preserves_practice(setup):
    client, gateway, _, _ = setup
    data = create_form(action="update", target_id="timeline:5", expected="b" * 64)
    assert client.post("/app/clienti/2/attivita", data=data).status_code == 409
    assert gateway.writes == []
    data["expected"] = "a" * 64
    response = client.post("/app/clienti/2/attivita", data=data)
    assert response.status_code == 200
    assert gateway.writes[0]["practice_id"] == 91
    assert gateway.writes[0]["expected"] == "a" * 64
    assert gateway.writes[0]["target_id"] == "timeline:5"


def test_completed_is_shown_only_after_durable_receipt_reports_it(setup):
    client, gateway, _, _ = setup
    data = create_form(kind="document_request", status="Non evasa", event_date="2026-10-22")
    pending = client.post("/app/clienti/2/attivita", data=data)
    assert "Comando in attesa" in pending.text
    gateway.commands[0].update(status="COMPLETED", result="crm:42")
    complete = client.get("/app/clienti/2/attivita", params={"command_id": data["command_id"]})
    assert "Comando completato" in complete.text
    assert "crm:42" in complete.text
    assert len(gateway.writes) == 1
