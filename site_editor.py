"""Small, append-only home-page editor using the site's existing SQLAlchemy DB.

Integration contract
--------------------
``register_editor(app, context)`` needs ``Base``, ``SessionLocal``,
``require_admin(request)``, ``app_page(title, subtitle, body, request, active)``,
``public_page(title, body, request)``, ``home_body(content_dict)``,
``default_content``, ``csrf_token(request)``, ``verify_csrf(request, token)``
and ``asset_choices`` (a trusted URL -> label dictionary of existing /static
assets). The CSRF verifier raises HTTPException(403) on failure.

The returned dictionary exposes ``Revision``, ``get_published_content`` and
``get_publication_id``. Register before the application's explicit additive
schema creation/migration; this module never creates a table, seeds data,
modifies customer tables, or publishes content during import/registration.

Drafts, publications and restorations are immutable new rows. The unique
parent_revision_id is a database-enforced compare-and-swap: two concurrent
edits/publications cannot both extend the same history. Publication also
requires a one-use preview receipt in the signed session, bound to the user,
revision, content hash, current history head and published predecessor.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column


EDITOR_PATH = "/app/gestione-sito"
PREVIEW_SESSION_KEY = "site_editor_preview"
PREVIEW_TTL_SECONDS = 30 * 60
MAX_FORM_BYTES = 32 * 1024
FIELDS = {
    "hero_eyebrow": ("Sopratitolo", 2, 80),
    "hero_title": ("Titolo principale", 5, 130),
    "hero_text": ("Testo introduttivo", 20, 600),
    "hero_cta_label": ("Testo del pulsante", 2, 50),
    "hero_cta_href": ("Destinazione del pulsante", 1, 150),
    "hero_image_url": ("Immagine attuale", 0, 200),
    "hero_image_alt": ("Descrizione accessibile dell'immagine", 0, 180),
}
ALLOWED_CTA_PATHS = {
    "/go/app": "Apri o scarica LELE_K_PLUS",
    "/lele-k-plus": "Pagina LELE_K_PLUS",
    "/registrazione": "Richiedi un account",
    "/login": "Accedi all'area riservata",
    "/contatti": "Contatti",
    "/servizi": "Servizi",
    "/piattaforma": "Piattaforma",
}


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _canonical_content(content):
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_content(values, asset_choices):
    """Accept plain text and exact, server-defined local URL choices only."""
    if not isinstance(values, dict):
        raise HTTPException(422, "Contenuto editoriale non valido.")
    output = {}
    for name, (label, minimum, maximum) in FIELDS.items():
        raw = values.get(name, "")
        if not isinstance(raw, str):
            raise HTTPException(422, f"{label}: valore non valido.")
        value = unicodedata.normalize("NFC", raw).strip()
        if not minimum <= len(value) <= maximum:
            raise HTTPException(422, f"{label}: inserire da {minimum} a {maximum} caratteri.")
        if any(ord(ch) < 32 and ch not in "\n\t" for ch in value) or "\x7f" in value:
            raise HTTPException(422, f"{label}: caratteri di controllo non consentiti.")
        if "<" in value or ">" in value:
            raise HTTPException(422, f"{label}: usare testo semplice, senza codice HTML.")
        if name != "hero_text" and ("\n" in value or "\t" in value):
            raise HTTPException(422, f"{label}: usare una sola riga.")
        output[name] = value
    if output["hero_cta_href"] not in ALLOWED_CTA_PATHS:
        raise HTTPException(422, "Destinazione del pulsante non consentita.")
    if output["hero_image_url"] not in asset_choices:
        raise HTTPException(422, "Selezionare un'immagine presente nell'elenco autorizzato.")
    if output["hero_image_url"] and len(output["hero_image_alt"]) < 3:
        raise HTTPException(422, "Descrivere l'immagine selezionata con almeno 3 caratteri.")
    return output


def _missing_editor_table(exc):
    original = getattr(exc, "orig", exc)
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if code == "42P01":
        return True
    return "no such table: site_content_revisions" in str(original).lower()


async def _read_form(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Formato del modulo non supportato.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_FORM_BYTES:
            raise HTTPException(413, "Modulo troppo grande.")
    try:
        parsed = parse_qs(data.decode("utf-8"), keep_blank_values=True, max_num_fields=20, errors="strict")
    except (UnicodeError, ValueError):
        raise HTTPException(400, "Modulo non valido.") from None
    if any(len(values) != 1 for values in parsed.values()):
        raise HTTPException(400, "Campi duplicati nel modulo.")
    return {name: values[0] for name, values in parsed.items()}


def _form_id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,18}", value):
        raise HTTPException(422, f"{label} non valida: ricaricare la pagina.")
    return int(value)


def register_editor(app, context):
    """Register routes and return ORM/getter handles; never mutate a database."""
    Base = context["Base"]
    SessionLocal = context["SessionLocal"]
    require_admin = context["require_admin"]
    app_page = context["app_page"]
    public_page = context["public_page"]
    home_body = context["home_body"]
    csrf_token = context["csrf_token"]
    verify_csrf = context["verify_csrf"]
    asset_choices = dict(context["asset_choices"])
    if any(
        not isinstance(url, str)
        or (url and (not re.fullmatch(r"/static/[A-Za-z0-9_./-]+", url)
        or any(part in {".", "..", ""} for part in url.split("/")[2:])))
        for url in asset_choices
    ):
        raise ValueError("asset_choices deve contenere URL /static di file esistenti definiti dal server.")
    asset_choices = {"": "Composizione grafica del percorso", **asset_choices}
    default_content = validate_content(dict(context["default_content"]), asset_choices)

    class SiteContentRevision(Base):
        __tablename__ = "site_content_revisions"
        __table_args__ = (
            CheckConstraint("kind IN ('draft', 'published')", name="ck_site_revision_kind"),
            CheckConstraint("parent_revision_id >= 0", name="ck_site_revision_parent"),
        )

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        parent_revision_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
        kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
        source_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
        base_publication_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
        publication_parent_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
        content_json: Mapped[str] = mapped_column(Text, nullable=False)
        content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
        actor_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
        actor_label: Mapped[str] = mapped_column(String(255), nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    Revision = SiteContentRevision

    def _head(db):
        return db.scalar(select(Revision).order_by(Revision.id.desc()).limit(1))

    def _published(db):
        return db.scalar(select(Revision).where(Revision.kind == "published").order_by(Revision.id.desc()).limit(1))

    def _content(row):
        try:
            value = json.loads(row.content_json)
        except (TypeError, ValueError):
            raise HTTPException(503, "Revisione editoriale non leggibile.") from None
        raw = _canonical_content(value)
        if not secrets.compare_digest(hashlib.sha256(raw.encode("utf-8")).hexdigest(), row.content_sha256):
            raise HTTPException(503, "Integrità della revisione editoriale non verificata.")
        # Revalidate previously stored URLs against the current trusted asset/route choices.
        return validate_content(value, asset_choices)

    def get_published_content():
        """Return published content or None; an unmigrated schema falls back safely."""
        try:
            with SessionLocal() as db:
                row = _published(db)
                return _content(row) if row else None
        except SQLAlchemyError as exc:
            if _missing_editor_table(exc):
                return None
            raise

    def get_publication_id():
        try:
            with SessionLocal() as db:
                row = _published(db)
                return row.id if row else 0
        except SQLAlchemyError as exc:
            if _missing_editor_table(exc):
                return 0
            raise

    def _require_schema(db):
        try:
            head = _head(db)
            pub = _published(db)
            return head, pub
        except SQLAlchemyError as exc:
            if _missing_editor_table(exc):
                raise HTTPException(503, "Gestione contenuti in preparazione: lo schema editoriale non è ancora inizializzato.") from None
            raise

    def _private(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def _hidden(name, value):
        return f'<input type="hidden" name="{_esc(name)}" value="{_esc(value)}">'

    def _csrf(request):
        return _hidden("csrf_token", csrf_token(request))

    def _date(value):
        return value.strftime("%d/%m/%Y %H:%M UTC")

    def _select(name, values, current):
        options = "".join(
            f'<option value="{_esc(url)}"{" selected" if url == current else ""}>{_esc(label)}</option>'
            for url, label in values.items()
        )
        required = " required" if name != "hero_image_url" else ""
        return f'<select name="{name}" id="editor-{name}"{required}>{options}</select>'

    def _append(db, *, actor, kind, content, parent_id, publication_id, source_id=None):
        canonical = _canonical_content(content)
        row = Revision(
            parent_revision_id=parent_id,
            kind=kind,
            source_revision_id=source_id,
            base_publication_id=publication_id,
            publication_parent_id=publication_id if kind == "published" else None,
            content_json=canonical,
            content_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            actor_user_id=str(actor.id),
            actor_label=str(getattr(actor, "display_name", "") or actor.email)[:255],
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Un'altra modifica è stata salvata. Ricaricare la gestione sito e verificare la revisione aggiornata.") from None
        return row

    @app.get(EDITOR_PATH, include_in_schema=False)
    def editor_home(request: Request):
        require_admin(request)
        with SessionLocal() as db:
            head, pub = _require_schema(db)
            rows = list(db.scalars(select(Revision).order_by(Revision.id.desc()).limit(15)))
            content = _content(head) if head else dict(default_content)
            head_id, pub_id = head.id if head else 0, pub.id if pub else 0
            status = (
                f'Contenuto pubblicato: revisione <strong>#{pub.id}</strong> del {_date(pub.created_at)}.'
                if pub else 'La home usa i contenuti della versione software. Nessuna revisione editoriale è stata ancora pubblicata.'
            )
            pending = (
                f'<div class="notice">Bozza <strong>#{head.id}</strong> salvata. '
                f'<a href="{EDITOR_PATH}/anteprima/{head.id}">Apri anteprima e verifica la pubblicazione</a>.</div>'
                if head and head.kind == "draft" else ""
            )
            controls = []
            for name, (label, minimum, maximum) in FIELDS.items():
                if name == "hero_cta_href":
                    control = _select(name, ALLOWED_CTA_PATHS, content[name])
                elif name == "hero_image_url":
                    control = _select(name, asset_choices, content[name])
                elif name == "hero_text":
                    control = f'<textarea name="{name}" id="editor-{name}" rows="5" minlength="{minimum}" maxlength="{maximum}" required>{_esc(content[name])}</textarea>'
                else:
                    required = " required" if minimum else ""
                    control = f'<input type="text" name="{name}" id="editor-{name}" value="{_esc(content[name])}" minlength="{minimum}" maxlength="{maximum}"{required}>'
                controls.append(f'<div class="field"><label for="editor-{name}">{_esc(label)}</label>{control}</div>')
            history = "".join(
                f'<tr><td>#{row.id}</td><td>{"Pubblicata" if row.kind == "published" else "Bozza"}</td>'
                f'<td>{_esc(row.actor_label)}</td><td>{_date(row.created_at)}</td>'
                f'<td>{("Da revisione #" + str(row.source_revision_id)) if row.source_revision_id else "Nuova bozza"}</td>'
                f'<td><a href="{EDITOR_PATH}/anteprima/{row.id}">{"Anteprima ripristino" if row.kind == "published" and row.id != pub_id else "Anteprima"}</a></td></tr>'
                for row in rows
            ) or '<tr><td colspan="6">Nessuna revisione editoriale.</td></tr>'
            body = f'''<div class="notice ok">{status}</div>{pending}
<section class="card"><h2>Contenuti della home</h2>
<p>Salva una bozza, controlla l'anteprima e pubblica con un'azione distinta. Ogni salvataggio conserva autore, data e versione.</p>
<form method="post" action="{EDITOR_PATH}/bozza" class="editor-form">
{_csrf(request)}{_hidden("base_revision_id", head_id)}{_hidden("base_publication_id", pub_id)}
<div class="form-grid">{"".join(controls)}</div>
<div class="actions"><button type="submit" class="btn primary">Salva bozza</button><a class="btn light" href="/">Vedi sito pubblico</a></div>
</form></section>
<section class="card"><h2>Storico delle revisioni</h2><p>Il ripristino crea una nuova pubblicazione dopo l'anteprima; lo storico resta disponibile. Mostrate le ultime 15 revisioni.</p>
<div class="table-wrap"><table><thead><tr><th>Revisione</th><th>Tipo</th><th>Autore</th><th>Data</th><th>Origine</th><th>Azione</th></tr></thead><tbody>{history}</tbody></table></div></section>'''
        return _private(app_page("Gestione sito", "Bozze, anteprima e pubblicazione della home", body, request, EDITOR_PATH))

    @app.post(EDITOR_PATH + "/bozza", include_in_schema=False)
    async def save_draft(request: Request):
        actor = await run_in_threadpool(require_admin, request)
        form = await _read_form(request)
        verify_csrf(request, form.get("csrf_token", ""))
        content = validate_content(form, asset_choices)
        base_head = _form_id(form.get("base_revision_id"), "Versione di partenza")
        base_pub = _form_id(form.get("base_publication_id"), "Pubblicazione di partenza")
        with SessionLocal() as db:
            head, pub = _require_schema(db)
            if base_head != (head.id if head else 0) or base_pub != (pub.id if pub else 0):
                raise HTTPException(409, "La pagina è stata modificata da un'altra sessione. Ricaricare prima di salvare la bozza.")
            row = _append(db, actor=actor, kind="draft", content=content, parent_id=base_head, publication_id=base_pub)
        request.session.pop(PREVIEW_SESSION_KEY, None)
        return _private(RedirectResponse(f"{EDITOR_PATH}/anteprima/{row.id}", status_code=303))

    @app.get(EDITOR_PATH + "/anteprima/{revision_id}", include_in_schema=False)
    def preview_revision(request: Request, revision_id: int):
        actor = require_admin(request)
        with SessionLocal() as db:
            head, pub = _require_schema(db)
            row = db.get(Revision, revision_id)
            if row is None:
                raise HTTPException(404, "Revisione non trovata.")
            content = _content(row)
            head_id, pub_id = head.id if head else 0, pub.id if pub else 0
            action = "pubblica" if row.kind == "draft" else "ripristina"
            can_publish = row.kind == "draft" and row.id == head_id and row.base_publication_id == pub_id
            can_restore = row.kind == "published" and row.id != pub_id
            # Opening any other preview invalidates the previous preview receipt.
            request.session.pop(PREVIEW_SESSION_KEY, None)
            if can_publish or can_restore:
                token = secrets.token_urlsafe(32)
                request.session[PREVIEW_SESSION_KEY] = {
                    "token": token, "revision_id": row.id, "hash": row.content_sha256,
                    "head_id": head_id, "publication_id": pub_id,
                    "actor_id": str(actor.id), "action": action, "at": int(time.time()),
                }
                button = "Pubblica questa bozza" if can_publish else f"Ripristina il contenuto della revisione #{row.id}"
                action_html = f'''<form method="post" action="{EDITOR_PATH}/{action}/{row.id}">
{_csrf(request)}{_hidden("preview_token", token)}{_hidden("base_revision_id", head_id)}{_hidden("base_publication_id", pub_id)}
<button class="btn primary" type="submit">{_esc(button)}</button></form>'''
                notice = "La pubblicazione aggiornerà la home del sito." if can_publish else "Il ripristino creerà una nuova revisione pubblicata con questi contenuti."
            else:
                action_html = ""
                notice = "Questa è la revisione attualmente pubblicata." if row.kind == "published" else "Bozza superata da una modifica successiva: torna alla gestione sito per salvare e verificare una nuova versione."
            banner = f'''<section class="wrap"><div class="notice editor-preview"><h1>Anteprima riservata · revisione #{row.id}</h1>
<p>{notice} Autore: {_esc(row.actor_label)} · {_date(row.created_at)}.</p>
<div class="actions">{action_html}<a class="btn light" href="{EDITOR_PATH}">Torna alla gestione sito</a></div></div></section>'''
        return _private(public_page("Anteprima home", banner + home_body(content), request))

    async def _publish(request, revision_id, action):
        actor = await run_in_threadpool(require_admin, request)
        form = await _read_form(request)
        verify_csrf(request, form.get("csrf_token", ""))
        receipt = request.session.get(PREVIEW_SESSION_KEY)
        token = form.get("preview_token", "")
        if (
            not isinstance(receipt, dict)
            or not token
            or not secrets.compare_digest(str(receipt.get("token", "")), token)
            or receipt.get("revision_id") != revision_id
            or receipt.get("actor_id") != str(actor.id)
            or receipt.get("action") != action
            or not 0 <= int(time.time()) - int(receipt.get("at", 0)) <= PREVIEW_TTL_SECONDS
        ):
            raise HTTPException(409, "Aprire nuovamente l'anteprima della revisione prima di pubblicare.")
        base_head = _form_id(form.get("base_revision_id"), "Versione di partenza")
        base_pub = _form_id(form.get("base_publication_id"), "Pubblicazione di partenza")
        if base_head != receipt.get("head_id") or base_pub != receipt.get("publication_id"):
            raise HTTPException(409, "Conferma non coerente con l'anteprima. Aprire nuovamente la revisione.")
        with SessionLocal() as db:
            head, pub = _require_schema(db)
            row = db.get(Revision, revision_id)
            if row is None:
                raise HTTPException(404, "Revisione non trovata.")
            if base_head != (head.id if head else 0) or base_pub != (pub.id if pub else 0):
                raise HTTPException(409, "È presente una modifica più recente. Riaprire l'anteprima prima della pubblicazione.")
            if not secrets.compare_digest(str(receipt.get("hash", "")), row.content_sha256):
                raise HTTPException(409, "Il contenuto non corrisponde all'anteprima verificata.")
            if action == "pubblica" and (row.kind != "draft" or row.id != base_head or row.base_publication_id != base_pub):
                raise HTTPException(409, "La bozza non è più la versione corrente.")
            if action == "ripristina" and (row.kind != "published" or row.id == base_pub):
                raise HTTPException(409, "Scegliere una precedente revisione pubblicata da ripristinare.")
            content = _content(row)
            _append(db, actor=actor, kind="published", content=content, parent_id=base_head, publication_id=base_pub, source_id=row.id)
        request.session.pop(PREVIEW_SESSION_KEY, None)
        return _private(RedirectResponse(EDITOR_PATH, status_code=303))

    @app.post(EDITOR_PATH + "/pubblica/{revision_id}", include_in_schema=False)
    async def publish_revision(request: Request, revision_id: int):
        return await _publish(request, revision_id, "pubblica")

    @app.post(EDITOR_PATH + "/ripristina/{revision_id}", include_in_schema=False)
    async def restore_revision(request: Request, revision_id: int):
        return await _publish(request, revision_id, "ripristina")

    return {"Revision": Revision, "get_published_content": get_published_content, "get_publication_id": get_publication_id}
