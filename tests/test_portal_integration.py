"""Independent portal contract tests with a synthetic MASTER and temporary DB.

Environment is set BEFORE loading app.py. The real gateway request method is
replaced with a failure guard. No external network, production secrets, real
customer records, or MASTER writes are used by this test suite.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import func, inspect, select

import master_gateway
from fake_master import FakeMaster


def hidden(response):
    return {node["name"]: node.get("value", "") for node in BeautifulSoup(response.text, "html.parser").select('input[type="hidden"][name]')}


def decoded_session(client):
    value = client.cookies.get("session", "")
    if not value:
        return {}
    payload = value.split(".", 1)[0]
    return json.loads(base64.b64decode(payload + "=" * (-len(payload) % 4)))


def local_core_counts(module):
    with module.SessionLocal() as db:
        return {model.__tablename__: db.scalar(select(func.count()).select_from(model)) for model in (module.Client, module.Document, module.Analysis)}


@pytest.fixture
def portal(tmp_path, monkeypatch):
    settings = {
        "APP_ENV": "test", "DATABASE_URL": "sqlite:///" + str(tmp_path / "isolated-site.sqlite"),
        "SEED_DEMO": "0", "SECRET_KEY": "synthetic-isolated-test-session-key-at-least-32-characters",
        "ADMIN_EMAIL": "local-admin@example.invalid", "ADMIN_PASSWORD": "Local-QA-admin-password-2026",
        "CONTACT_EMAIL": "contact@example.invalid", "BASE_URL": "https://financeplus.test",
        "MASTER_API_BASE_URL": "https://master.example.invalid",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)

    def never_network(*args, **kwargs):
        raise AssertionError("Real Gateway.request is forbidden in portal tests")

    monkeypatch.setattr(master_gateway.Gateway, "request", never_network)
    name = "_isolated_financeplus_portal_" + uuid.uuid4().hex
    path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    fake = FakeMaster()
    module.gateway = fake
    assert module.DATABASE_URL.startswith("sqlite:///")
    assert module.SEED_DEMO is False
    assert local_core_counts(module) == {"clients": 0, "documents": 0, "analyses": 0}
    with TestClient(module.app, base_url="https://financeplus.test", follow_redirects=False) as client:
        yield SimpleNamespace(module=module, fake=fake, client=client)
    module.engine.dispose()


def login(portal, role="admin"):
    initial = portal.client.get("/login")
    response = portal.client.post("/login", data={**hidden(initial), "email": role + "@example.invalid", "password": "QA-only-password-2026", "mode": "master"})
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/app"
    session = decoded_session(portal.client)
    assert "master_session" in session
    portal.fake.clear_calls()
    return portal.module.token_vault.get(session["master_session"])


def pdf_text(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    reader = PdfReader(io.BytesIO(response.content))
    return reader, "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.mark.parametrize("role,visible,hidden_name,visible_id,forbidden_id", [
    ("client", "Azienda Alfa QA", "Azienda Beta QA", 1001, 2002),
    ("collaborator", "Azienda Beta QA", "Azienda Alfa QA", 2002, 1001),
])
def test_client_and_collaborator_only_use_authorized_portal_routes(portal, role, visible, hidden_name, visible_id, forbidden_id):
    login(portal, role)
    for path in ("/app", "/app/clienti", "/app/pratiche", f"/app/clienti/{visible_id}", "/app/clienti/stampa?scope=all", "/app/pratiche/stampa?scope=all"):
        response = portal.client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert visible in response.text
        assert hidden_name not in response.text
    assert portal.client.get(f"/app/clienti/{forbidden_id}").status_code == 404
    reader, text = pdf_text(portal.client.get("/app/clienti/pdf?scope=all"))
    assert visible in text and hidden_name not in text and "1 righe" in text
    assert not any(call["path"].startswith("/v1/clients") or call["path"].startswith("/v1/admin/") for call in portal.fake.calls)
    assert portal.fake.writes == []


def test_admin_clients_card_and_company_links_open_distinct_records(portal):
    login(portal)
    dashboard = portal.client.get("/app")
    assert dashboard.status_code == 200
    cards = BeautifulSoup(dashboard.text, "html.parser").select("a.p-stat")
    assert any("Clienti" in node.get_text() and node.get("href") == "/app/clienti" for node in cards)
    response = portal.client.get("/app/clienti")
    links = {node.get("href") for node in BeautifulSoup(response.text, "html.parser").select("a[href]")}
    assert "/app/clienti/1001" in links and "/app/clienti/2002" in links
    alfa = portal.client.get("/app/clienti/1001")
    beta = portal.client.get("/app/clienti/2002")
    assert "Azienda Alfa QA" in alfa.text and "Azienda Beta QA" not in alfa.text
    assert "Azienda Beta QA" in beta.text and "Azienda Alfa QA" not in beta.text
    assert portal.fake.writes == []


@pytest.mark.parametrize("client_id", [0, -1, 999999, 9007199254740992])
def test_invalid_client_id_never_falls_back_to_first_company(portal, client_id):
    login(portal)
    response = portal.client.get(f"/app/clienti/{client_id}")
    assert response.status_code == 404
    assert "Azienda Alfa QA" not in response.text
    assert not any(call["path"] == "/v1/clients/1001" for call in portal.fake.calls)


def test_role_changes_are_rechecked_and_remove_admin_permissions(portal):
    token = login(portal)
    assert portal.client.get("/app/clienti").status_code == 200
    principal = portal.fake.principal(token)
    principal["role"] = "collaborator"
    principal["can_upload"] = False
    portal.fake.clear_calls()
    response = portal.client.get("/app/clienti")
    assert response.status_code == 200
    assert "Azienda Beta QA" in response.text and "Azienda Alfa QA" not in response.text
    assert portal.client.get("/app/gestione-sito").status_code == 403
    assert not any(call["path"].startswith("/v1/clients") for call in portal.fake.calls)
    assert sum(call["path"] == "/v1/me" for call in portal.fake.calls) >= 2


def test_revoked_session_is_removed_without_local_admin_fallback(portal):
    token = login(portal)
    session_id = decoded_session(portal.client)["master_session"]
    portal.fake.revoked.add(token)
    response = portal.client.get("/app/clienti")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "master_session" not in decoded_session(portal.client)
    assert portal.module.token_vault.get(session_id) is None
    assert not any(call["path"].startswith("/v1/clients") for call in portal.fake.calls)


def test_master_access_token_is_absent_from_cookie_and_html(portal):
    token = login(portal)
    response = portal.client.get("/app")
    assert response.status_code == 200
    session = decoded_session(portal.client)
    assert set(session) <= {"master_session", "csrf_token"}
    assert token not in json.dumps(session)
    assert token not in response.text
    assert token not in str(dict(response.headers))
    assert token not in portal.client.cookies.get("session")
    assert "no-store" in response.headers["cache-control"]


def test_scoring_get_and_report_reads_do_not_create_local_analysis(portal):
    login(portal)
    before = local_core_counts(portal.module)
    response = portal.client.get("/app/scoring?client=1001")
    assert response.status_code == 303 and response.headers["location"] == "/app/clienti/1001?tab=analisi"
    assert portal.client.get("/app/scoring?client=999999").status_code == 404
    assert portal.client.get("/app/scoring").headers["location"] == "/app/analisi"
    for suffix in ("anteprima", "pdf", "contenuto"):
        assert portal.client.get(f"/app/report/2002/{suffix}").status_code == 404
    reader, text = pdf_text(portal.client.get("/app/report/1001/pdf"))
    assert "Esito sintetico ricevuto dal MASTER QA" in text
    assert local_core_counts(portal.module) == before
    assert portal.fake.writes == []


@pytest.mark.parametrize("count", [0, 1, 120])
def test_complete_exports_have_exact_counts_and_multipage_support(portal, count):
    portal.fake.set_portfolio(count)
    login(portal)
    for kind in ("clienti", "pratiche"):
        print_response = portal.client.get(f"/app/{kind}/stampa?scope=all")
        assert print_response.status_code == 200
        assert f"{count} righe" in print_response.text
        reader, text = pdf_text(portal.client.get(f"/app/{kind}/pdf?scope=all"))
        assert f"{count} righe" in text
        if count > 1:
            assert len(reader.pages) > 1
            assert f"Impresa QA {count - 1:04d}" in text
        if count == 0:
            assert "Nessun risultato" in text
    assert portal.fake.writes == []


def test_filtered_export_and_all_export_have_different_complete_scopes(portal):
    login(portal)
    _, filtered = pdf_text(portal.client.get("/app/clienti/pdf?scope=filtered&client=2002"))
    _, complete = pdf_text(portal.client.get("/app/clienti/pdf?scope=all&client=2002"))
    assert "1 righe" in filtered and "Azienda Beta QA" in filtered and "Azienda Alfa QA" not in filtered
    assert "2 righe" in complete and "Azienda Alfa QA" in complete and "Azienda Beta QA" in complete
    _, zero = pdf_text(portal.client.get("/app/pratiche/pdf?scope=filtered&q=no-such-company"))
    assert "0 righe" in zero


@pytest.mark.parametrize("count", [500, 501])
def test_capped_client_responses_are_never_exported_as_complete(portal, count):
    portal.fake.set_portfolio(count)
    login(portal)
    for path in ("/app/clienti/pdf?scope=all", "/app/pratiche/stampa?scope=all", "/app/clienti/pdf?scope=filtered&client=1001"):
        response = portal.client.get(path)
        assert response.status_code == 409, path
        assert "elenco incompleto" in response.text or "esportazione" in response.text


def test_manager_filter_works_when_master_transmits_manager_name(portal):
    login(portal)
    response = portal.client.get("/app/clienti?manager=Gestore%20Beta")
    assert response.status_code == 200, response.text
    rows = BeautifulSoup(response.text, "html.parser").select("tbody tr")
    body = " ".join(node.get_text(" ") for node in rows)
    assert "Azienda Beta QA" in body and "Azienda Alfa QA" not in body


def upload_form(portal):
    page = portal.client.get("/app/carica-documenti")
    assert page.status_code == 200, page.text
    return {**hidden(page), "document_kind": "altro"}


def test_upload_forwards_signature_checked_bytes_and_stable_idempotency_key(portal):
    login(portal)
    form = upload_form(portal)
    data = b"%PDF-1.4\n% synthetic QA file\n%%EOF"
    before = local_core_counts(portal.module)
    for attempt in range(2):
        response = portal.client.post("/app/carica-documenti", data=form, files={"file": ("documento QA.pdf", data, "application/pdf")})
        assert response.status_code == 303, response.text
    calls = [call for call in portal.fake.writes if call["path"] == "/v1/intakes"]
    assert len(calls) == 2
    assert all(call["headers"]["x-idempotency-key"] == form["idempotency_key"] for call in calls)
    assert calls[0]["headers"]["x-filename"] == "documento%20QA.pdf"
    assert calls[0]["data_size"] == len(data)
    assert len(portal.fake.uploads) == 1
    assert local_core_counts(portal.module) == before


@pytest.mark.parametrize("size,expected", [(16 * 1024 * 1024, 303), (16 * 1024 * 1024 + 1, 413)])
def test_upload_sixteen_mib_boundary_is_enforced_before_master_transfer(portal, size, expected):
    login(portal)
    form = upload_form(portal)
    data = b"%PDF-" + b"X" * (size - 5)
    response = portal.client.post("/app/carica-documenti", data=form, files={"file": ("limite.pdf", data, "application/pdf")})
    assert response.status_code == expected, response.text
    transfers = [call for call in portal.fake.writes if call["path"] == "/v1/intakes"]
    assert len(transfers) == (1 if expected == 303 else 0)
    assert local_core_counts(portal.module) == {"clients": 0, "documents": 0, "analyses": 0}


@pytest.mark.parametrize("filename,content,status", [
    ("documento.pdf", b"MZ this is not a pdf", 415),
    ("image.png", b"%PDF-1.4 not png", 415),
    ("documento.exe", b"%PDF-1.4", 415),
    ("../documento.pdf", b"%PDF-1.4", 422),
])
def test_invalid_uploads_never_reach_master(portal, filename, content, status):
    login(portal)
    form = upload_form(portal)
    response = portal.client.post("/app/carica-documenti", data=form, files={"file": (filename, content, "application/octet-stream")})
    assert response.status_code == status
    assert not any(call["path"] == "/v1/intakes" for call in portal.fake.writes)


def test_upload_requires_csrf_and_actual_receipt(portal):
    login(portal)
    form = upload_form(portal)
    bad_csrf = {**form, "csrf_token": "wrong"}
    files = {"file": ("qa.pdf", b"%PDF-1.4 QA", "application/pdf")}
    assert portal.client.post("/app/carica-documenti", data=bad_csrf, files=files).status_code == 403
    assert portal.fake.writes == []
    portal.fake.receipt_missing = True
    response = portal.client.post("/app/carica-documenti", data=form, files=files)
    assert response.status_code == 502
    assert "ok=1" not in response.headers.get("location", "")
    assert local_core_counts(portal.module) == {"clients": 0, "documents": 0, "analyses": 0}


def test_new_company_is_queued_in_master_without_local_crm_or_analysis(portal):
    login(portal)
    form = hidden(portal.client.get("/app/nuovo-cliente"))
    form.update(name="Impresa sintetica QA", vat="12345678901", sector="Test", confirmed="true")
    assert portal.client.post("/app/nuovo-cliente", data={**form, "csrf_token": "wrong"}).status_code == 403
    assert portal.fake.writes == []
    response = portal.client.post("/app/nuovo-cliente", data=form)
    assert response.status_code == 303 and response.headers["location"] == "/app/richieste-clienti"
    posted = [call for call in portal.fake.writes if call["path"] == "/v1/client-requests"]
    assert len(posted) == 1 and posted[0]["payload"]["idempotency_key"] == form["idempotency_key"]
    assert local_core_counts(portal.module) == {"clients": 0, "documents": 0, "analyses": 0}


def test_contacts_preserve_existing_lead_bridge_schema_only(portal):
    columns = {col["name"] for col in inspect(portal.module.engine).get_columns("leads")}
    assert columns == {"id", "name", "company", "email", "phone", "service", "message", "created_at"}
    page = portal.client.get("/contatti")
    form = {**hidden(page), "name": "Contatto QA", "company": "Impresa sito QA", "email": "lead@example.invalid", "phone": "0000000000", "service": "Accesso al credito", "message": "Richiesta di collaudo sintetica"}
    response = portal.client.post("/contatti", data=form)
    assert response.status_code == 303
    with portal.module.SessionLocal() as db:
        leads = list(db.scalars(select(portal.module.Lead)))
        assert len(leads) == 1
        assert leads[0].company == form["company"] and leads[0].message == form["message"]
    assert portal.fake.calls == []
    assert local_core_counts(portal.module) == {"clients": 0, "documents": 0, "analyses": 0}
