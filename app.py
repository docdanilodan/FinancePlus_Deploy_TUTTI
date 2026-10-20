from __future__ import annotations
import base64, hashlib, hmac, html, io, json, os, secrets
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from types import SimpleNamespace
from public_site import HOME_DEFAULTS, header_html, footer_html, home_body, platform_body, services_body, service_body, SERVICE_SLUGS
from master_gateway import Gateway, GatewayError, TokenVault
from portal_ui import shell as portal_shell
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, String, Integer, Boolean, DateTime, Float, ForeignKey, Text, LargeBinary, select, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from starlette.middleware.sessions import SessionMiddleware
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

APP_VERSION = "FinancePlus Web 4.1.0"
APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./financeplus_ultimate.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me-" + secrets.token_hex(16))
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "d.dangelo@financeplus.tech").lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "FinancePlusDemo2026!")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "d.dangelo@financeplus.tech")
PHONE = os.getenv("PHONE", "+39 329 113 5692")
BASE_URL = os.getenv("BASE_URL", "https://financeplus.tech").rstrip("/")
META_DOMAIN_VERIFICATION = os.getenv("META_DOMAIN_VERIFICATION", "").strip()
SOCIAL_IMAGE_URL = os.getenv("SOCIAL_IMAGE_URL", f"{BASE_URL}/static/logo.png").strip()
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "2W9WJ8HH87").strip()
IOS_BUNDLE_ID = os.getenv("IOS_BUNDLE_ID", "tech.financeplus.smartfplus.mobile").strip()
IOS_APP_STORE_ID = os.getenv("IOS_APP_STORE_ID", "6815794369").strip()
IOS_APP_STORE_URL = os.getenv("IOS_APP_STORE_URL", "https://apps.apple.com/it/app/lele-k-plus/id6815794369").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
SEED_DEMO = False  # The public service never creates demonstration customers or scores.
gateway = Gateway()
token_vault = TokenVault()

# Fail closed in production: the app must not start with demo credentials,
# a transient secret key, or the local SQLite database.
if APP_ENV == "production":
    if not os.getenv("SECRET_KEY") or len(SECRET_KEY) < 32:
        raise RuntimeError("In produzione impostare SECRET_KEY con almeno 32 caratteri casuali.")
    if not os.getenv("ADMIN_PASSWORD") or ADMIN_PASSWORD == "FinancePlusDemo2026!":
        raise RuntimeError("In produzione impostare ADMIN_PASSWORD con una password forte e non-demo.")
    if DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("In produzione impostare DATABASE_URL su PostgreSQL/Neon; SQLite e solo per test locale.")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(30), default="client")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    company_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(80), default="")
    service: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(255), index=True)
    vat: Mapped[str] = mapped_column(String(40), default="")
    sector: Mapped[str] = mapped_column(String(120), default="")
    contact: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    revenue: Mapped[float] = mapped_column(Float, default=0)
    ebitda: Mapped[float] = mapped_column(Float, default=0)
    net_worth: Mapped[float] = mapped_column(Float, default=0)
    invoice_amount: Mapped[float] = mapped_column(Float, default=0)
    debtor: Mapped[str] = mapped_column(String(255), default="")
    due_date: Mapped[str] = mapped_column(String(40), default="")
    accorded: Mapped[float] = mapped_column(Float, default=0)
    utilized: Mapped[float] = mapped_column(Float, default=0)
    cr_risk: Mapped[str] = mapped_column(String(40), default="Basso")
    status: Mapped[str] = mapped_column(String(80), default="In attesa documenti")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(120), default="Altro")
    status: Mapped[str] = mapped_column(String(80), default="Riconosciuto")
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    seller_score: Mapped[int] = mapped_column(Integer, default=80)
    debtor_score: Mapped[int] = mapped_column(Integer, default=75)
    invoice_score: Mapped[int] = mapped_column(Integer, default=85)
    cr_score: Mapped[int] = mapped_column(Integer, default=70)
    docs_score: Mapped[int] = mapped_column(Integer, default=90)
    overall_score: Mapped[int] = mapped_column(Integer, default=80)
    completeness: Mapped[int] = mapped_column(Integer, default=90)
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

def pwhash(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(dk).decode()

def pwcheck(password: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$", 2)
        salt = base64.urlsafe_b64decode(s)
        expected = base64.urlsafe_b64decode(h)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def esc(v): return html.escape(str(v or ""), quote=True)
def eur(v): return ("€ {:,.0f}".format(float(v or 0))).replace(",", ".")



def bootstrap_admin():
    """Crea l'amministratore iniziale se non esiste. In produzione usa solo le variabili ambiente."""
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if not admin:
            db.add(User(email=ADMIN_EMAIL, password_hash=pwhash(ADMIN_PASSWORD), role="admin", approved=True, display_name="Danilo D'Angelo", company_name="Financeplus S.r.l."))
            db.commit()

bootstrap_admin()

app = FastAPI(title=APP_VERSION, version="4.1.0")
from request_limits import RequestBodyLimitMiddleware
app.add_middleware(RequestBodyLimitMiddleware)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=(APP_ENV == "production"), max_age=8*3600)

@app.middleware("http")
async def production_security(request: Request, call_next):
    # Same-origin check for state-changing browser requests. This complements SameSite cookies.
    if APP_ENV == "production" and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            try:
                if urlparse(source).netloc and urlparse(source).netloc != request.url.netloc:
                    return Response("Origine richiesta non consentita", status_code=403)
            except Exception:
                return Response("Origine richiesta non valida", status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    private_prefixes = ("/app", "/admin", "/login", "/registrazione", "/logout")
    is_private = request.url.path.startswith(private_prefixes)
    if request.url.path == "/contatti":
        # The contact form contains a session-bound CSRF token.
        response.headers["Cache-Control"] = "no-store, private"
    if is_private:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN" if request.url.path.endswith("/contenuto") else "DENY")
        response.headers["Cache-Control"] = "no-store, private"
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src 'self'; object-src 'self'; form-action 'self'; frame-ancestors 'self'; base-uri 'self'")
    else:
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; form-action 'self'; base-uri 'self'")
    if APP_ENV == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

PUBLIC_NAV = [("/","Home"),("/servizi","Servizi"),("/metodo","Metodo"),("/piattaforma","Piattaforma"),("/lele-k-plus","LELE_K_PLUS"),("/insights","Insights"),("/chi-siamo","Chi siamo"),("/contatti","Contatti")]

SERVICES = [
    ("Strategia e sviluppo d'impresa","Diagnosi strategica, scenari, priorità, piani di crescita e investimenti.","Diagnosi + piano operativo"),
    ("Pianificazione e controllo","Budget, forecast, KPI, margini, costi, DSCR e analisi degli scostamenti.","Dashboard + reporting"),
    ("Accesso al credito","Pre-valutazione, dossier, selezione strumenti e accompagnamento alla pratica.","Dossier + assistenza"),
    ("Merito creditizio","Bilanci, Centrale Rischi, flussi, scoring, anomalie e piano di miglioramento.","Score + action plan"),
    ("Business plan e investimenti","Piani economico-finanziari, cash flow, stress test e sostenibilità del debito.","Business Plan bancabile"),
    ("Invoice Trading & Fintech","Pre-fattibilità AI, confronto piattaforme, checklist e dossier per cessione crediti.","Ranking + dossier")]
METHOD = [("01","Ascolto e raccolta dati","Obiettivi, problemi, documenti e vincoli."),("02","Analisi","Bilanci, CR, flussi, organizzazione e mercato."),("03","Diagnosi","Criticità, rischi, incoerenze, opportunità e priorità."),("04","Strategia","Scenari, obiettivi, azioni, responsabilità e tempi."),("05","Attuazione","Pratiche, processi, dossier e documentazione."),("06","Monitoraggio","KPI, avanzamento, variazioni e azioni correttive.")]

def current_user(request: Request):
    if hasattr(request.state, "financeplus_user"):
        return request.state.financeplus_user
    sid = request.session.get("master_session")
    if sid:
        token = token_vault.get(sid)
        if not token:
            request.session.pop("master_session", None)
            return None
        try:
            principal = gateway.get("/v1/me", token)
        except GatewayError as exc:
            if exc.status in (401, 403):
                token_vault.remove(sid)
                request.session.pop("master_session", None)
                return None
            if request.url.path.startswith("/app"):
                raise HTTPException(503, exc.message)
            return None
        if principal.get("role") not in {"admin", "professional", "client", "collaborator"} or principal.get("status") not in {"active", "pending"}:
            token_vault.remove(sid)
            request.session.pop("master_session", None)
            return None
        u = SimpleNamespace(id="master:" + str(principal["id"]), email=principal.get("email") or "", role=principal["role"], approved=(principal.get("status") == "active" or principal.get("role") == "client"), display_name=principal.get("name") or "Utente", company_name=principal.get("company_name") or "", auth_source="master", principal=principal)
        request.state.master_token = token
        request.state.financeplus_user = u
        return u
    uid = request.session.get("uid")
    if not isinstance(uid, int):
        return None
    with SessionLocal() as db:
        u = db.get(User, uid)
    request.state.financeplus_user = u
    return u

def csrf_token(request: Request):
    if not request.session.get("csrf_token"):
        request.session["csrf_token"] = secrets.token_urlsafe(32)
    return request.session["csrf_token"]

def verify_csrf(request: Request, value: str):
    expected = request.session.get("csrf_token")
    if not isinstance(value, str) or not expected or not hmac.compare_digest(value, expected):
        raise HTTPException(403, "La pagina è scaduta. Riaprila e riprova.")

def csrf_field(request: Request):
    return f'<input type="hidden" name="csrf_token" value="{esc(csrf_token(request))}">'


def require_user(request: Request) -> User:
    u = current_user(request)
    if not u: raise HTTPException(401)
    if not u.approved: raise HTTPException(403, "Account non approvato")
    return u

def require_admin(request: Request) -> User:
    u = require_user(request)
    if u.role != "admin" or (getattr(u, "auth_source", "") == "master" and u.principal.get("status") != "active"): raise HTTPException(403)
    return u

def page(title: str, body: str, request: Request, description: str = "FinancePlus.tech - Advisory d'impresa") -> HTMLResponse:
    u = current_user(request)
    page_title = f"{title} | FinancePlus.tech"
    canonical_path = request.url.path if request.url.path else "/"
    canonical_url = f"{BASE_URL}{canonical_path}"
    meta_verification = (
        f'<meta name="facebook-domain-verification" content="{esc(META_DOMAIN_VERIFICATION)}">'
        if META_DOMAIN_VERIFICATION else ""
    )
    return HTMLResponse(f'''<!doctype html><html lang="it"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{esc(description)}">\n<meta name="apple-itunes-app" content="app-id={esc(IOS_APP_STORE_ID)}, app-argument={esc(BASE_URL + '/go/app')}">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{esc(canonical_url)}">
<meta property="og:locale" content="it_IT">
<meta property="og:type" content="website">
<meta property="og:site_name" content="FinancePlus.tech">
<meta property="og:title" content="{esc(page_title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical_url)}">
<meta property="og:image" content="{esc(SOCIAL_IMAGE_URL)}">
<meta property="og:image:alt" content="FinancePlus.tech - Data Strategy Results">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(page_title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{esc(SOCIAL_IMAGE_URL)}">
{meta_verification}
<title>{esc(page_title)}</title>
<link rel="icon" href="/static/logo.png">
<link rel="stylesheet" href="/static/app.css"><link rel="stylesheet" href="/static/public-site.css"><script src="/static/public-site.js" defer></script></head><body>
{header_html(request.url.path, authenticated=bool(u))}<main id="main-content">{body}</main>{footer_html(CONTACT_EMAIL, PHONE)}</body></html>''')

def app_page(title: str, subtitle: str, content: str, request: Request, active: str) -> HTMLResponse:
    user = require_user(request)
    source = "Dati autorizzati dal MASTER" if getattr(user, "auth_source", "") == "master" else "Gestione del sito · collega l'account MASTER per i dati operativi"
    return HTMLResponse(portal_shell(user, title, subtitle, content, active, source, csrf_token(request), public_admin=user.role == "admin"))


@app.get("/health")
def health(): return {"status":"ok","version":APP_VERSION}

@app.get("/meta-business", include_in_schema=False)
def meta_business(request: Request):
    origin = str(request.base_url).rstrip("/")
    page_url = f"{origin}/meta-business"
    html_doc = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="index,follow">
<title>FinancePlus.tech - Business Website</title>
<meta name="description" content="FinancePlus.tech - Advisory d'impresa, strategia, gestione e credito.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="FinancePlus.tech">
<meta property="og:title" content="FinancePlus.tech - Business Website">
<meta property="og:description" content="Advisory d'impresa, strategia, gestione e credito.">
<meta property="og:url" content="{esc(page_url)}">
<link rel="canonical" href="{esc(page_url)}">
</head>
<body>
<main>
<h1>FinancePlus.tech</h1>
<h2>Advisory d'impresa</h2>
<p>Consulenza integrata per la strategia, la gestione e il credito.</p>
<p>Financeplus S.r.l. - P.IVA 04825280615</p>
<p><a href="mailto:d.dangelo@financeplus.tech">d.dangelo@financeplus.tech</a></p>
</main>
</body>
</html>"""
    return HTMLResponse(
        html_doc,
        status_code=200,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(str(Path(__file__).parent / "static" / "logo.png"), media_type="image/png")

@app.get("/.well-known/apple-app-site-association", include_in_schema=False)
def apple_app_site_association():
    app_id = f"{APPLE_TEAM_ID}.{IOS_BUNDLE_ID}"
    payload = {
        "applinks": {
            "apps": [],
            "details": [
                {
                    "appID": app_id,
                    "paths": ["/go/app", "/go/app/*", "/open/*"],
                }
            ],
        }
    }
    return Response(
        json.dumps(payload, separators=(",", ":")),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=3600"},
    )

@app.get("/go/app", include_in_schema=False)
@app.get("/go/app/{target:path}", include_in_schema=False)
def go_app(target: str = ""):
    if IOS_APP_STORE_URL:
        return RedirectResponse(IOS_APP_STORE_URL, status_code=307)
    return RedirectResponse("/lele-k-plus?store=pending", status_code=307)

@app.get("/open/{target:path}", include_in_schema=False)
def open_app_fallback(target: str):
    suffix = quote(target.strip("/"), safe="/")
    return RedirectResponse(f"/go/app/{suffix}" if suffix else "/go/app", status_code=307)

@app.get("/lele-k-plus")
def lele_k_plus(request: Request, store: str = ""):
    store_note = (
        '<div class="notice ok">App Store configurato: il pulsante apre l\'app se installata oppure porta allo store.</div>'
        if IOS_APP_STORE_URL
        else '<div class="notice">Il collegamento con LELE_K_PLUS e pronto. La pubblicazione App Store resta separata e verra attivata solo con URL ufficiale verificato.</div>'
    )
    store_action = (
        '<a class="btn primary" href="/go/app">Apri / Scarica LELE_K_PLUS</a>'
        if IOS_APP_STORE_URL
        else '<a class="btn primary" href="/go/app">Apri LELE_K_PLUS</a><a class="btn light" href="/registrazione">Richiedi accesso</a>'
    )
    body = f'''<section class="hero"><div class="wrap grid"><div>
    <span class="eyebrow">LELE_K_PLUS · FINANCEPLUS MOBILE</span>
    <h1>FinancePlus sempre con la tua impresa.</h1>
    <p>Cliente 360, pratiche, documenti e SERAFINO collegati al sistema FinancePlus, con accessi e permessi controllati.</p>
    <div class="actions">{store_action}<a class="btn light" href="/piattaforma">Scopri la piattaforma</a></div>
    {store_note}
    </div><div class="hero-card">
    <span class="eyebrow">COLLEGAMENTO SICURO</span>
    <h3>Sito, app e FF+ Analysis nello stesso ecosistema</h3>
    <p>LELE_K_PLUS non crea un archivio parallelo: usa i flussi autorizzati del sistema FinancePlus e del Cliente 360.</p>
    <div class="trust"><div><b>Cliente 360</b>Dati e pratiche</div><div><b>SERAFINO</b>Assistenza operativa</div><div><b>Cloud</b>Accesso controllato</div></div>
    </div></div></section>'''
    return page(
        "LELE_K_PLUS",
        body,
        request,
        "LELE_K_PLUS - l'app FinancePlus collegata a Cliente 360, pratiche, documenti e SERAFINO.",
    )

@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    meta_bot = "facebook" + "externalhit"
    body = f"""User-agent: {meta_bot}
Allow: /

User-agent: Facebot
Allow: /

User-agent: *
Allow: /
Disallow: /app
Disallow: /admin
Sitemap: {BASE_URL}/sitemap.xml
"""
    return Response(body, media_type="text/plain; charset=utf-8")

@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    urls = [href for href, _ in PUBLIC_NAV] + ["/servizi/" + slug for slug in SERVICE_SLUGS]
    items = "".join(
        f"<url><loc>{esc(BASE_URL + ('/' if href == '/' else href))}</loc></url>"
        for href in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    return Response(xml, media_type="application/xml; charset=utf-8")
@app.head("/", include_in_schema=False)
@app.get("/")
def home(request: Request):
    content = editor["get_published_content"]() if "editor" in globals() else None
    return page("La finanza della tua impresa, sotto controllo", home_body(content), request)


@app.get("/servizi")
def servizi(request: Request):
    return page("Servizi", services_body(SERVICES), request)

@app.get("/servizi/{slug}")
def servizio_dettaglio(slug: str, request: Request):
    result = service_body(slug, SERVICES)
    if result is None:
        raise HTTPException(404, "Servizio non trovato.")
    title, body = result
    return page(title, body, request)


@app.get("/metodo")
def metodo(request: Request):
    steps = "".join(f'<article class="card"><div class="num">{n}</div><h3>{esc(t)}</h3><p>{esc(d)}</p></article>' for n,t,d in METHOD)
    return page("Metodo", f'<section class="pagehero"><div class="wrap"><span class="eyebrow">METODO</span><h1>Sei fasi, un unico processo</h1><p>Ascolto, analisi, diagnosi, strategia, attuazione e monitoraggio. Il cliente vede sempre stato, responsabilità e prossima azione.</p></div></section><section><div class="wrap grid3">{steps}</div></section>', request)

@app.get("/piattaforma")
def piattaforma(request: Request):
    return page("Piattaforma", platform_body(), request)


@app.get("/insights")
def insights(request: Request):
    cards=[("Centrale Rischi","Come leggere utilizzi, sconfinamenti e anomalie prima di una richiesta bancaria."),("DSCR e sostenibilità","Il rapporto tra flussi di cassa, debito e capacità prospettica di rimborso."),("Invoice Trading","Come preparare una cessione crediti riducendo attriti documentali e tempi di istruttoria."),("KPI e controllo","Margini, PFN, circolante e indicatori da monitorare per migliorare la finanziabilità."),("Business Plan banca","Dati storici, previsioni e stress test per un dossier credibile."),("Document Intelligence","Automazione documentale con validazione umana e tracciabilità.")]
    return page("Insights", '<section class="pagehero"><div class="wrap"><span class="eyebrow">INSIGHTS</span><h1>Numeri spiegati per decidere meglio</h1><p>Approfondimenti operativi su credito, Centrale Rischi, DSCR, business plan e analisi finanziaria.</p></div></section><section><div class="wrap grid3">'+''.join(f'<article class="card"><h3>{t}</h3><p>{d}</p></article>' for t,d in cards)+'</div></section>', request)

@app.get("/chi-siamo")
def chi_siamo(request: Request):
    body='''<section class="pagehero"><div class="wrap"><span class="eyebrow">CHI SIAMO</span><h1>FinancePlus.tech</h1><p>Advisory d'impresa di Financeplus S.r.l. Un approccio che integra persone, finanza, credito, organizzazione e tecnologia.</p></div></section><section><div class="wrap grid3"><article class="card"><h3>Missione</h3><p>Trasformare dati, obiettivi e criticità in decisioni operative, sostenibili e misurabili.</p></article><article class="card"><h3>Metodo</h3><p>Analisi rigorosa, tracciabilità, personalizzazione e controllo dell'esecuzione.</p></article><article class="card"><h3>Tecnologia</h3><p>Automazione documentale, scoring, reportistica e strumenti AI con supervisione professionale.</p></article></div></section>'''
    return page("Chi siamo", body, request)

@app.get("/contatti")
def contatti(request: Request, ok: int = 0, service: str = ""):
    selected_service = SERVICES[SERVICE_SLUGS.index(service)][0] if service in SERVICE_SLUGS else "Advisory d\'impresa"
    service_labels = ["Advisory d'impresa"] + [row[0] for row in SERVICES] + ["FinancePlus Platform"]
    service_options = "".join(f'<option value="{esc(label)}"' + (' selected' if label == selected_service else '') + f'>{esc(label)}</option>' for label in service_labels)
    note = '<div class="notice ok">Richiesta acquisita. Ti ricontatteremo sui recapiti indicati.</div>' if ok else ''
    body=f'''<section class="pagehero"><div class="wrap"><span class="eyebrow">CONTATTI</span><h1>Parliamo della tua impresa</h1><p>Descrivi l'esigenza, il fabbisogno o la criticità. Il contatto viene registrato nella pipeline FinancePlus.</p></div></section><section><div class="wrap grid2"><div class="card"><h3>Contatto diretto</h3><p><b>{esc(PHONE)}</b><br>{esc(CONTACT_EMAIL)}</p><div class="actions"><a class="btn primary" href="https://wa.me/393291135692">Apri WhatsApp</a><a class="btn light" href="mailto:{esc(CONTACT_EMAIL)}">Scrivi email</a></div></div><form class="card" method="post">{note}{csrf_field(request)}<div class="field"><label for="contact-name">Nome e cognome</label><input id="contact-name" autocomplete="name" maxlength="255" name="name" required></div><div class="field"><label for="contact-company">Azienda</label><input id="contact-company" autocomplete="organization" maxlength="255" name="company"></div><div class="field"><label for="contact-email">Email</label><input id="contact-email" autocomplete="email" maxlength="255" name="email" type="email" required></div><div class="field"><label for="contact-phone">Telefono</label><input id="contact-phone" autocomplete="tel" maxlength="80" type="tel" name="phone"></div><div class="field"><label for="contact-service">Servizio</label><select id="contact-service" name="service">{service_options}</select></div><div class="field"><label for="contact-message">Messaggio</label><textarea id="contact-message" maxlength="4000" name="message" rows="5"></textarea></div><button class="btn primary">Invia richiesta</button></form></div></section>'''
    return page("Contatti", body, request)

@app.post("/contatti")
def contatti_post(request: Request, csrf_token: str=Form(""), name: str=Form(...), company: str=Form(""), email: str=Form(...), phone: str=Form(""), service: str=Form(""), message: str=Form("")):
    verify_csrf(request, csrf_token)
    if not name.strip() or len(name) > 255 or len(company) > 255 or len(email) > 255 or len(phone) > 80 or len(service) > 255 or len(message) > 4000 or "@" not in email:
        raise HTTPException(422, "Controlla i recapiti e la lunghezza del messaggio.")
    with SessionLocal() as db:
        db.add(Lead(name=name, company=company, email=email, phone=phone, service=service, message=message)); db.commit()
    return RedirectResponse("/contatti?ok=1", status_code=303)

@app.get("/registrazione")
def registrazione(request: Request, ok: int = 0):
    note = '<div class="notice ok" role="status">Registrazione ricevuta. Accedi alla tua area personale; le pratiche richiedono verifica e assegnazione dello studio.</div>' if ok else ''
    return page("Registrazione", f"""<section class="authwrap"><form class="authcard" method="post"><h1>Crea il tuo account</h1><p>Un account per il sito e LELE_K_PLUS.</p>{note}{csrf_field(request)}<div class="field"><label for="register-name">Nome e cognome</label><input id="register-name" name="name" minlength="2" maxlength="120" autocomplete="name" required></div><div class="field"><label for="register-email">Email</label><input id="register-email" type="email" name="email" maxlength="120" autocomplete="username" required></div><div class="field"><label for="register-password">Password</label><input id="register-password" type="password" name="password" minlength="12" maxlength="128" autocomplete="new-password" aria-describedby="password-policy" required><small id="password-policy">Da 12 a 128 caratteri.</small></div><button class="btn primary">Crea account</button><p><a href="/login">Hai già un account? Accedi</a></p></form></section>""", request)


@app.post("/registrazione")
def registrazione_post(request: Request, name: str=Form(...), email: str=Form(...), password: str=Form(...), csrf_token: str=Form("")):
    verify_csrf(request, csrf_token)
    if not 12 <= len(password) <= 128 or not 2 <= len(name.strip()) <= 120 or len(email) > 120:
        raise HTTPException(422, "Controlla nome, email e password (da 12 a 128 caratteri).")
    try:
        gateway.post("/v1/accounts/register", payload={"name": name.strip(), "username": email.strip().lower(), "password": password})
    except GatewayError as exc:
        raise HTTPException(exc.status, exc.message)
    return RedirectResponse("/registrazione?ok=1", 303)


@app.get("/login")
def login(request: Request, err: str = "", mode: str = "master"):
    local = mode == "site"
    msg = '<div class="notice err" role="alert">Accesso non riuscito. Verifica le credenziali e riprova.</div>' if err else ''
    info = "Gestione editoriale e richieste dal sito." if local else "Usa lo stesso account di LELE_K_PLUS per accedere ai dati autorizzati del MASTER."
    alternate = '<a href="/login">Accedi con il tuo account LELE_K_PLUS</a>' if local else '<a href="/login?mode=site">Amministrazione del sito</a>'
    title = "Amministra il sito" if local else "Accedi al tuo spazio FinancePlus"
    return page("Accesso", f"""<section class="authwrap"><form class="authcard" method="post"><h1>{title}</h1><p>{info}</p>{msg}{csrf_field(request)}<input type="hidden" name="mode" value="{'site' if local else 'master'}"><div class="field"><label for="login-email">Email o nome utente</label><input id="login-email" type="text" name="email" autocomplete="username" maxlength="120" required></div><div class="field"><label for="login-password">Password</label><input id="login-password" type="password" name="password" autocomplete="current-password" maxlength="128" required></div><button class="btn primary">Accedi</button><div class="actions"><a href="/registrazione">Crea un account</a>{alternate}</div></form></section>""", request)


@app.post("/login")
def login_post(request: Request, email: str=Form(...), password: str=Form(...), mode: str=Form("master"), csrf_token: str=Form("")):
    verify_csrf(request, csrf_token)
    if not 3 <= len(email.strip()) <= 120 or len(password) > 128:
        raise HTTPException(422, "Credenziali non valide.")
    from auth_limits import throttle_login
    throttle_login(request, email, mode)
    if mode == "site":
        with SessionLocal() as db:
            u = db.scalar(select(User).where(User.email == email.strip().lower()))
            if not u or not u.approved or u.role != "admin" or not pwcheck(password, u.password_hash):
                return RedirectResponse("/login?mode=site&err=1", 303)
            token_vault.remove(request.session.get("master_session"))
            request.session.clear()
            request.session["uid"] = u.id
        return RedirectResponse("/app", 303)
    try:
        token, ttl, principal = gateway.login(email, password)
        sid = token_vault.put(token, ttl)
    except GatewayError as exc:
        if exc.status in (400, 401, 403, 422):
            return RedirectResponse("/login?err=1", 303)
        raise HTTPException(exc.status if exc.status in (429, 503) else 503, exc.message)
    token_vault.remove(request.session.get("master_session"))
    request.session.clear()
    request.session["master_session"] = sid
    return RedirectResponse("/app", 303)


@app.get("/logout")
def logout(request: Request):
    return page("Esci", f'<section class="authwrap"><form class="authcard" action="/logout" method="post"><h1>Esci dal tuo account</h1>{csrf_field(request)}<button class="btn primary" type="submit">Conferma uscita</button></form></section>', request)

@app.post("/logout")
def logout_post(request: Request, csrf_token: str=Form("")):
    verify_csrf(request, csrf_token)
    token_vault.remove(request.session.get("master_session"))
    request.session.clear()
    return RedirectResponse("/", 303)



# Private portal and editorial routes are registered below from verified adapters.

from site_editor import register_editor
from portal_routes import register_portal

editor = register_editor(app, {
    "Base": Base, "SessionLocal": SessionLocal, "require_admin": require_admin,
    "app_page": app_page, "public_page": page, "home_body": home_body,
    "default_content": HOME_DEFAULTS, "csrf_token": csrf_token, "verify_csrf": verify_csrf,
    "asset_choices": {"/static/logo.png": "Logo FinancePlus attuale"},
})
# Additive table only: existing users, leads, clients and documents are preserved.
Base.metadata.create_all(engine, tables=[editor["Revision"].__table__])
register_portal(app, globals())

@app.exception_handler(401)
async def unauthorized(request: Request, exc):
    return RedirectResponse("/login", 303)

@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return HTMLResponse("<html lang='it'><head><meta charset='utf-8'><title>Accesso non consentito</title><link rel='stylesheet' href='/static/public-site.css'></head><body><main class='wrap'><h1>Accesso non consentito</h1><p>Questa operazione non è disponibile per il tuo account oppure la pagina è scaduta.</p><a href='/app'>Torna alla tua area</a></main></body></html>", status_code=403)
