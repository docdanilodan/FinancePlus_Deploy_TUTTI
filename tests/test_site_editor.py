"""Isolated CMS authorization, publication and concurrency contract tests.

No import of app.py, external services, customer tables or production data.
Run: python -m pytest tests/test_site_editor.py
"""

import html
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

from site_editor import EDITOR_PATH, register_editor


DEFAULT = {
    "hero_eyebrow": "FINANCEPLUS PER LE IMPRESE",
    "hero_title": "Decisioni migliori per la tua impresa.",
    "hero_text": "Organizza i documenti e segui le tue pratiche attraverso il sistema FinancePlus.",
    "hero_cta_label": "Scopri LELE_K_PLUS",
    "hero_cta_href": "/lele-k-plus",
    "hero_image_url": "/static/logo.png",
    "hero_image_alt": "Logo attuale FinancePlus",
}
ADMIN_HEADERS = {"x-test-role": "admin", "x-test-user-id": "11"}


def _hidden(text):
    return {
        name: html.unescape(value)
        for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', text)
    }


def build_app(create_schema=True, default_content=None, body_renderer=None):
    class TestBase(DeclarativeBase):
        pass

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="isolated-editor-test-session-key")

    def require_admin(request):
        role = request.headers.get("x-test-role")
        if not role:
            raise HTTPException(401)
        if role != "admin" or request.headers.get("x-test-approved", "yes") != "yes":
            raise HTTPException(403)
        return SimpleNamespace(id=request.headers.get("x-test-user-id", "11"), role=role, email="test-admin@example.invalid", display_name="Admin <test>")

    def csrf_token(request):
        import secrets
        if "csrf_test" not in request.session:
            request.session["csrf_test"] = secrets.token_urlsafe(24)
        return request.session["csrf_test"]

    def verify_csrf(request, token):
        import secrets
        expected = request.session.get("csrf_test")
        if not expected or not token or not secrets.compare_digest(expected, token):
            raise HTTPException(403, "CSRF")

    def home_body(content):
        return '<h2>' + html.escape(content["hero_title"]) + '</h2><p>' + html.escape(content["hero_text"]) + '</p>'

    selected_default = default_content or DEFAULT
    renderer = body_renderer or home_body
    handles = register_editor(app, {
        "Base": TestBase,
        "SessionLocal": session_factory,
        "require_admin": require_admin,
        "app_page": lambda title, subtitle, body, request, active: HTMLResponse(body),
        "public_page": lambda title, body, request: HTMLResponse(body),
        "home_body": renderer,
        "default_content": selected_default,
        "csrf_token": csrf_token,
        "verify_csrf": verify_csrf,
        "asset_choices": {"/static/logo.png": "Logo attuale"},
    })
    if create_schema:
        TestBase.metadata.create_all(engine)

    @app.get("/")
    def home():
        return HTMLResponse(renderer(handles["get_published_content"]() or selected_default))

    client = TestClient(app, headers=ADMIN_HEADERS, follow_redirects=False)
    return SimpleNamespace(app=app, client=client, Base=TestBase, engine=engine, Session=session_factory, **handles)


@pytest.fixture
def cms():
    result = build_app()
    yield result
    result.client.close()
    result.engine.dispose()


def save_draft(cms, title="Nuova home FinancePlus per le imprese.", client=None):
    client = client or cms.client
    response = client.get(EDITOR_PATH)
    assert response.status_code == 200
    form = {**DEFAULT, **_hidden(response.text), "hero_title": title}
    response = client.post(EDITOR_PATH + "/bozza", data=form)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


def publish(cms, revision_id, client=None):
    client = client or cms.client
    preview = client.get(f"{EDITOR_PATH}/anteprima/{revision_id}")
    assert preview.status_code == 200
    response = client.post(f"{EDITOR_PATH}/pubblica/{revision_id}", data=_hidden(preview.text))
    assert response.status_code == 303, response.text
    return cms.get_publication_id()


def test_registration_does_not_create_or_seed_schema():
    cms = build_app(create_schema=False)
    try:
        assert inspect(cms.engine).get_table_names() == []
        assert cms.get_published_content() is None
        assert cms.get_publication_id() == 0
        assert cms.client.get("/").status_code == 200
        assert cms.client.get(EDITOR_PATH).status_code == 503
        cms.Base.metadata.create_all(cms.engine)
        assert inspect(cms.engine).get_table_names() == ["site_content_revisions"]
        assert cms.client.get(EDITOR_PATH).status_code == 200
    finally:
        cms.client.close()
        cms.engine.dispose()


def test_draft_and_preview_leave_public_home_unchanged(cms):
    revision = save_draft(cms)
    assert cms.get_published_content() is None
    preview = cms.client.get(f"{EDITOR_PATH}/anteprima/{revision}")
    assert preview.status_code == 200
    assert "Nuova home FinancePlus" in preview.text
    assert preview.headers["cache-control"] == "no-store"
    assert preview.headers["x-robots-tag"] == "noindex, nofollow"
    assert DEFAULT["hero_title"] in cms.client.get("/").text
    assert cms.get_published_content() is None


def test_publish_requires_preview_and_records_author_and_source(cms):
    revision = save_draft(cms)
    editor = cms.client.get(EDITOR_PATH)
    rejected = cms.client.post(f"{EDITOR_PATH}/pubblica/{revision}", data=_hidden(editor.text))
    assert rejected.status_code == 409
    publication = publish(cms, revision)
    assert publication != revision
    assert "Nuova home FinancePlus" in cms.client.get("/").text
    with cms.Session() as db:
        rows = list(db.scalars(select(cms.Revision).order_by(cms.Revision.id)))
        assert [row.kind for row in rows] == ["draft", "published"]
        assert rows[1].source_revision_id == revision
        assert rows[1].actor_user_id == "11"
        assert rows[1].created_at is not None
        assert rows[1].content_sha256 == rows[0].content_sha256
        assert rows[1].parent_revision_id == revision
    assert "Admin &lt;test&gt;" in cms.client.get(EDITOR_PATH).text


@pytest.mark.parametrize("method,path", [
    ("get", EDITOR_PATH),
    ("get", EDITOR_PATH + "/anteprima/1"),
    ("post", EDITOR_PATH + "/bozza"),
    ("post", EDITOR_PATH + "/pubblica/1"),
    ("post", EDITOR_PATH + "/ripristina/1"),
])
def test_every_editor_route_requires_administrator(cms, method, path):
    for role in ("client", "collaborator", "segnalatore", "gestore"):
        response = getattr(cms.client, method)(path, headers={"x-test-role": role})
        assert response.status_code == 403
    response = getattr(cms.client, method)(path, headers={"x-test-approved": "no"})
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/bozza", "/pubblica/1", "/ripristina/1"])
def test_every_mutation_requires_csrf(cms, path):
    cms.client.get(EDITOR_PATH)
    response = cms.client.post(EDITOR_PATH + path, data={**DEFAULT, "base_revision_id": "0", "base_publication_id": "0"})
    assert response.status_code == 403
    assert cms.get_publication_id() == 0


@pytest.mark.parametrize("field,value", [
    ("hero_title", '<script>alert("x")</script>'),
    ("hero_cta_href", "javascript:alert(1)"),
    ("hero_cta_href", "//example.invalid"),
    ("hero_cta_href", "/go/app?next=https://example.invalid"),
    ("hero_image_url", "/static/../app.py"),
    ("hero_image_url", "/static/not-approved.png"),
    ("hero_image_url", "https://example.invalid/pixel.png"),
    ("hero_text", "x" * 601),
    ("hero_title", "Bad\x00title"),
])
def test_rejects_unsafe_or_out_of_bounds_content_before_writing(cms, field, value):
    form = {**DEFAULT, **_hidden(cms.client.get(EDITOR_PATH).text), field: value}
    assert cms.client.post(EDITOR_PATH + "/bozza", data=form).status_code == 422
    with cms.Session() as db:
        assert list(db.scalars(select(cms.Revision))) == []


def test_stale_editor_form_cannot_overwrite_new_draft(cms):
    stale = {**DEFAULT, **_hidden(cms.client.get(EDITOR_PATH).text)}
    revision = save_draft(cms)
    response = cms.client.post(EDITOR_PATH + "/bozza", data=stale)
    assert response.status_code == 409
    with cms.Session() as db:
        assert [row.id for row in db.scalars(select(cms.Revision))] == [revision]


def test_new_draft_by_other_admin_invalidates_old_preview(cms):
    revision = save_draft(cms)
    form = _hidden(cms.client.get(f"{EDITOR_PATH}/anteprima/{revision}").text)
    with TestClient(cms.app, headers={"x-test-role": "admin", "x-test-user-id": "22"}, follow_redirects=False) as other:
        newer = save_draft(cms, title="Titolo aggiornato da un altro amministratore.", client=other)
    response = cms.client.post(f"{EDITOR_PATH}/pubblica/{revision}", data=form)
    assert response.status_code == 409
    assert cms.get_publication_id() == 0
    old_preview = cms.client.get(f"{EDITOR_PATH}/anteprima/{revision}")
    assert "Bozza superata" in old_preview.text
    assert "preview_token" not in _hidden(old_preview.text)
    publish(cms, newer)


def test_preview_receipt_bound_to_admin_and_one_use(cms):
    revision = save_draft(cms)
    form = _hidden(cms.client.get(f"{EDITOR_PATH}/anteprima/{revision}").text)
    cross_user = cms.client.post(f"{EDITOR_PATH}/pubblica/{revision}", data=form, headers={"x-test-user-id": "22"})
    assert cross_user.status_code == 409
    response = cms.client.post(f"{EDITOR_PATH}/pubblica/{revision}", data=form)
    assert response.status_code == 303
    assert cms.client.post(f"{EDITOR_PATH}/pubblica/{revision}", data=form).status_code == 409


def test_rollback_creates_new_publication_and_preserves_history(cms):
    first = save_draft(cms, title="Prima home da conservare nello storico.")
    publication1 = publish(cms, first)
    second = save_draft(cms, title="Seconda home con contenuti aggiornati.")
    publication2 = publish(cms, second)
    preview = cms.client.get(f"{EDITOR_PATH}/anteprima/{publication1}")
    assert "Ripristina il contenuto" in preview.text
    response = cms.client.post(f"{EDITOR_PATH}/ripristina/{publication1}", data=_hidden(preview.text))
    assert response.status_code == 303
    restored = cms.get_publication_id()
    assert restored > publication2
    assert cms.get_published_content()["hero_title"] == "Prima home da conservare nello storico."
    with cms.Session() as db:
        rows = list(db.scalars(select(cms.Revision).order_by(cms.Revision.id)))
        assert len(rows) == 5
        assert rows[-1].source_revision_id == publication1
        assert rows[-1].publication_parent_id == publication2
        assert rows[-1].content_sha256 == rows[1].content_sha256
        assert rows[3].content_json != rows[-1].content_json


def test_database_unique_parent_is_atomic_concurrency_gate(cms):
    revision = save_draft(cms)
    with cms.Session() as db:
        original = db.get(cms.Revision, revision)
        competing = cms.Revision(
            parent_revision_id=original.parent_revision_id,
            kind="draft", source_revision_id=None, base_publication_id=0,
            publication_parent_id=None, content_json=original.content_json,
            content_sha256=original.content_sha256, actor_user_id="22",
            actor_label="Concurrent test", created_at=datetime.now(timezone.utc),
        )
        db.add(competing)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert len(list(db.scalars(select(cms.Revision)))) == 1


def test_oversize_and_duplicate_form_fields_are_rejected(cms):
    cms.client.get(EDITOR_PATH)
    response = cms.client.post(EDITOR_PATH + "/bozza", content="text=" + "x" * 33000, headers={"content-type": "application/x-www-form-urlencoded"})
    assert response.status_code == 413
    duplicate = cms.client.post(EDITOR_PATH + "/bozza", content="title=one&title=two", headers={"content-type": "application/x-www-form-urlencoded"})
    assert duplicate.status_code == 400


def test_real_public_home_contract_supports_default_graphic_without_photo():
    from public_site import HOME_DEFAULTS, home_body
    cms = build_app(default_content=HOME_DEFAULTS, body_renderer=home_body)
    try:
        response = cms.client.get(EDITOR_PATH)
        assert response.status_code == 200
        assert "Composizione grafica del percorso" in response.text
        form = {**HOME_DEFAULTS, **_hidden(response.text)}
        saved = cms.client.post(EDITOR_PATH + "/bozza", data=form)
        assert saved.status_code == 303
        revision = int(saved.headers["location"].rsplit("/", 1)[1])
        publish(cms, revision)
        assert cms.get_published_content()["hero_image_url"] == ""
        assert cms.get_published_content()["hero_image_alt"] == ""
        assert HOME_DEFAULTS["hero_title"] in cms.client.get("/").text
    finally:
        cms.client.close()
        cms.engine.dispose()


def test_master_uuid_actor_is_preserved_in_audit(cms):
    master_id = "master:779ff014-49e9-4fb0-b603-d449f97596e0"
    cms.client.headers["x-test-user-id"] = master_id
    revision = save_draft(cms)
    publication = publish(cms, revision)
    with cms.Session() as db:
        assert db.get(cms.Revision, revision).actor_user_id == master_id
        assert db.get(cms.Revision, publication).actor_user_id == master_id


def test_preview_receipt_expires(cms, monkeypatch):
    import site_editor
    now = 1900000000
    monkeypatch.setattr(site_editor.time, "time", lambda: now)
    revision = save_draft(cms)
    form = _hidden(cms.client.get(f"{EDITOR_PATH}/anteprima/{revision}").text)
    now += site_editor.PREVIEW_TTL_SECONDS + 1
    rejected = cms.client.post(f"{EDITOR_PATH}/pubblica/{revision}", data=form)
    assert rejected.status_code == 409
    assert cms.get_publication_id() == 0
