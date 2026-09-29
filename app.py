from __future__ import annotations
import base64, hashlib, hmac, html, io, os, secrets
from datetime import datetime, date
from pathlib import Path
from typing import Optional
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

APP_VERSION = "FinancePlus Platform ULTIMATE 4.0"
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
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
SEED_DEMO = os.getenv("SEED_DEMO", "1" if APP_ENV != "production" else "0") == "1"

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

def category_from_name(name: str) -> str:
    n = name.lower()
    if "visura" in n: return "Visura camerale"
    if "bilancio" in n or n.endswith(".xbrl"): return "Bilancio"
    if "centrale" in n or "cr" in n: return "Centrale Rischi"
    if "fattura" in n or "invoice" in n: return "Fattura"
    if "estratt" in n or "conto" in n: return "Estratti conto"
    if "ddt" in n: return "DDT"
    return "Altro"

def status_for_category(cat: str) -> str:
    return "In analisi" if cat == "Centrale Rischi" else ("Da verificare" if cat == "Estratti conto" else "Riconosciuto")

def bootstrap_admin():
    """Crea l'amministratore iniziale se non esiste. In produzione usa solo le variabili ambiente."""
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if not admin:
            db.add(User(email=ADMIN_EMAIL, password_hash=pwhash(ADMIN_PASSWORD), role="admin", approved=True, display_name="Danilo D'Angelo", company_name="Financeplus S.r.l."))
            db.commit()

def seed_demo():
    if not SEED_DEMO: return
    with SessionLocal() as db:
        if (db.scalar(select(func.count(Client.id))) or 0) == 0:
            clients = [
                Client(company="Metalmeccanica Lombarda S.r.l.", vat="12345678901", sector="Metalmeccanica", contact="Luca Bianchi", phone="+39 02 1234567", email="l.bianchi@metalmeccanica.it", revenue=12450000, ebitda=1320000, net_worth=4850000, invoice_amount=285000, debtor="Alfa Retail S.p.A.", due_date="30/06/2026", accorded=2000000, utilized=1350000, cr_risk="Basso", status="Report generato"),
                Client(company="Edilizia San Marco S.p.A.", vat="02110022033", sector="Edilizia", contact="Marco Sala", phone="+39 02 991100", email="amministrazione@sanmarco.it", revenue=8900000, ebitda=730000, net_worth=3100000, invoice_amount=190000, debtor="Gamma Infrastrutture", due_date="15/07/2026", accorded=1400000, utilized=920000, cr_risk="Medio", status="Analisi in corso"),
                Client(company="Alimenti Mediterranei S.r.l.", vat="05432210987", sector="Alimentare", contact="Anna Russo", phone="+39 081 445566", email="a.russo@alimenti.it", revenue=6700000, ebitda=620000, net_worth=2500000, invoice_amount=140000, debtor="Retail Sud S.p.A.", due_date="31/07/2026", accorded=900000, utilized=610000, cr_risk="Basso", status="In attesa documenti"),
                Client(company="Trasporti Adriatici S.p.A.", vat="03099887766", sector="Trasporti", contact="Paolo Greco", phone="+39 071 556677", email="p.greco@trasportiadriatici.it", revenue=15300000, ebitda=1610000, net_worth=5900000, invoice_amount=360000, debtor="Logistica Italia", due_date="20/07/2026", accorded=2600000, utilized=1700000, cr_risk="Basso", status="Report generato"),
                Client(company="Biofarma Italia S.r.l.", vat="08877665544", sector="Farmaceutico", contact="Elisa Verde", phone="+39 06 221100", email="e.verde@biofarma.it", revenue=9900000, ebitda=940000, net_worth=4200000, invoice_amount=220000, debtor="Health Group", due_date="10/08/2026", accorded=1600000, utilized=1200000, cr_risk="Medio", status="Analisi completata"),
            ]
            db.add_all(clients); db.commit()
            for c in clients: db.refresh(c)
            a = clients[0]
            db.add(Analysis(client_id=a.id, seller_score=85, debtor_score=72, invoice_score=90, cr_score=68, docs_score=92, overall_score=78, completeness=92,
                ai_reason="Ottime prospettive di cessione. Profilo economico solido, documentazione completa e importo coerente. Opportuno monitorare concentrazione del debitore e condizioni economiche delle piattaforme."))
            demo_docs = [("Visura camerale.pdf","Visura camerale"),("Bilancio 2025.xbrl","Bilancio"),("Centrale Rischi.pdf","Centrale Rischi"),("Fattura_34.pdf","Fattura"),("Estratti_Conto_Q2.pdf","Estratti conto"),("DDT.pdf","DDT")]
            for fn,cat in demo_docs:
                db.add(Document(client_id=a.id, filename=fn, category=cat, status=status_for_category(cat), size=700_000, data=(f"Demo file {fn}").encode()))
            db.commit()
bootstrap_admin()
seed_demo()

app = FastAPI(title=APP_VERSION, version="4.0")
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
    if is_private:
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
    else:
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; form-action 'self'; base-uri 'self'")
    if APP_ENV == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

PUBLIC_NAV = [("/","Home"),("/servizi","Servizi"),("/metodo","Metodo"),("/piattaforma","Piattaforma"),("/insights","Insights"),("/chi-siamo","Chi siamo"),("/contatti","Contatti")]
APP_NAV = [("/app","⌂","Dashboard"),("/app/nuovo-cliente","＋","Nuovo Cliente"),("/app/clienti","♙","Clienti Salvati"),("/app/documenti","▤","Documenti"),("/app/analisi","✥","Analisi AI"),("/app/scoring","▥","Scoring Piattaforme"),("/app/report","▧","Report"),("/app/impostazioni","⚙","Impostazioni")]
PLATFORMS = [
    ("Workinvoice",92,"Molto alta","Operativa",0,"Consigliata"),("CrescItalia",88,"Molto alta","Operativa",1,"Consigliata"),("Jacash",85,"Alta","Operativa",1,"Consigliata"),("Borsa Fatture",78,"Alta","Operativa",2,"Valida"),("PlusAdvance",72,"Media","Manutenzione",2,"Da valutare"),("Finanza.tech",68,"Media","Operativa",3,"Da valutare"),("TeamSystem Incassa Subito",61,"Media","Operativa",3,"Da valutare"),("SFIRS",54,"Bassa","Operativa",4,"Meno adatta")]

SERVICES = [
    ("Strategia e sviluppo d'impresa","Diagnosi strategica, scenari, priorità, piani di crescita e investimenti.","Diagnosi + piano operativo"),
    ("Pianificazione e controllo","Budget, forecast, KPI, margini, costi, DSCR e analisi degli scostamenti.","Dashboard + reporting"),
    ("Accesso al credito","Pre-valutazione, dossier, selezione strumenti e accompagnamento alla pratica.","Dossier + assistenza"),
    ("Merito creditizio","Bilanci, Centrale Rischi, flussi, scoring, anomalie e piano di miglioramento.","Score + action plan"),
    ("Business plan e investimenti","Piani economico-finanziari, cash flow, stress test e sostenibilità del debito.","Business Plan bancabile"),
    ("Invoice Trading & Fintech","Pre-fattibilità AI, confronto piattaforme, checklist e dossier per cessione crediti.","Ranking + dossier")]
METHOD = [("01","Ascolto e raccolta dati","Obiettivi, problemi, documenti e vincoli."),("02","Analisi","Bilanci, CR, flussi, organizzazione e mercato."),("03","Diagnosi","Criticità, rischi, incoerenze, opportunità e priorità."),("04","Strategia","Scenari, obiettivi, azioni, responsabilità e tempi."),("05","Attuazione","Pratiche, processi, dossier e documentazione."),("06","Monitoraggio","KPI, avanzamento, variazioni e azioni correttive.")]

def current_user(request: Request) -> Optional[User]:
    uid = request.session.get("uid")
    if not uid: return None
    with SessionLocal() as db: return db.get(User, uid)

def require_user(request: Request) -> User:
    u = current_user(request)
    if not u: raise HTTPException(401)
    if not u.approved: raise HTTPException(403, "Account non approvato")
    return u

def require_admin(request: Request) -> User:
    u = require_user(request)
    if u.role != "admin": raise HTTPException(403)
    return u

def page(title: str, body: str, request: Request, description: str = "FinancePlus.tech - Advisory d'impresa") -> HTMLResponse:
    u = current_user(request)
    nav = "".join(f'<a href="{href}">{label}</a>' for href,label in PUBLIC_NAV)
    auth = f'<a href="/app">Area Privata</a><a href="/logout">Esci</a>' if u else '<a href="/login">Area Clienti</a>'
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
<meta name="description" content="{esc(description)}">
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
<link rel="stylesheet" href="/static/app.css"></head><body>
<div class="topstrip"><div class="wrap"><span>Financeplus S.r.l. · Advisory d'impresa</span><span>{esc(PHONE)} &nbsp; | &nbsp; {esc(CONTACT_EMAIL)}</span></div></div>
<header class="sitehead"><div class="wrap nav"><a class="brand" href="/"><img src="/static/logo.png"><span class="brandtext"><span class="name">FinancePlus.tech</span><span class="pay">DATA · STRATEGY · RESULTS</span></span></a><nav>{nav}{auth}<a class="btn primary" href="/contatti">Richiedi consulenza</a></nav></div></header>
<main>{body}</main>
<footer class="footer"><div class="wrap footergrid"><div><h4>FinancePlus.tech</h4><p>Advisory d'impresa. Consulenza integrata per la strategia, la gestione e il credito.</p><p>Data · Strategy · Results</p></div><div><h4>Piattaforma</h4><a href="/login">Area Clienti</a><a href="/registrazione">Richiedi account</a><a href="/piattaforma">FinancePlus Platform</a></div><div><h4>Contatti</h4><a href="mailto:{esc(CONTACT_EMAIL)}">{esc(CONTACT_EMAIL)}</a><a href="tel:+393291135692">{esc(PHONE)}</a><a href="https://wa.me/393291135692">WhatsApp</a></div></div><div class="wrap fine">© {datetime.now().year} Financeplus S.r.l. · P.IVA 04825280615 · {APP_VERSION}</div></footer><a class="wa" href="https://wa.me/393291135692">WA</a></body></html>''')

def app_page(title: str, subtitle: str, content: str, request: Request, active: str) -> HTMLResponse:
    u = require_user(request)
    nav = "".join(f'<a class="{"active" if href==active else ""}" href="{href}"><b class="navico">{ico}</b><span>{label}</span></a>' for href,ico,label in APP_NAV)
    return HTMLResponse(f'''<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{esc(title)} | FinancePlus Platform</title><link rel="icon" href="/static/logo.png"><link rel="stylesheet" href="/static/app.css"></head><body class="app-shell"><div class="app-topline">FinancePlus Platform ULTIMATE 4.0 · Private Workspace</div><div class="app-layout"><aside class="sidebar"><div class="sidebrand"><img src="/static/logo.png"><span><strong>FinancePlus AI</strong><small>Advisory & Credit Intelligence</small></span></div><nav class="sidenav">{nav}</nav><div class="sidefoot">Dati, analisi, opportunità.<br>Più valore al tuo business.</div></aside><main class="app-main"><header class="app-header"><div class="app-title"><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div><input class="searchbox" placeholder="⌕ Cerca clienti, documenti, report..."><div class="userbox"><div class="avatar">DD</div><div><b>{esc(u.display_name or u.email)}</b><small>{'Amministratore' if u.role=='admin' else 'Cliente'}</small></div><a href="/logout">⌄</a></div></header><section class="app-content">{content}</section></main></div></body></html>''')

@app.get("/health")
def health(): return {"status":"ok","version":APP_VERSION}

@app.get("/meta-business", include_in_schema=False)
def meta_business():
    html_doc = """<!doctype html>
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
<meta property="og:url" content="https://financeplus.tech/meta-business">
<link rel="canonical" href="https://financeplus.tech/meta-business">
</head>
<body>
<main>
<h1>FinancePlus.tech</h1>
<h2>Advisory d'impresa</h2>
<p>Consulenza integrata per la strategia, la gestione e il credito.</p>
<p>Financeplus S.r.l. - P.IVA 04825280615</p>
<p><a href="mailto:d.dangelo@financeplus.tech">d.dangelo@financeplus.tech</a></p>
<p><a href="https://financeplus.tech/">Vai al sito principale</a></p>
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

@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    body = f"""User-agent: *
Allow: /
Disallow: /app
Disallow: /admin
Sitemap: {BASE_URL}/sitemap.xml
"""
    return Response(body, media_type="text/plain; charset=utf-8")

@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    urls = [href for href, _ in PUBLIC_NAV]
    items = "".join(
        f"<url><loc>{esc(BASE_URL + ('/' if href == '/' else href))}</loc></url>"
        for href in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    return Response(xml, media_type="application/xml; charset=utf-8")
@app.head("/", include_in_schema=False)
@app.get("/")
def home(request: Request):
    cards = "".join(f'<article class="card"><span class="mini-badge">AREA DI INTERVENTO</span><h3>{esc(t)}</h3><p>{esc(d)}</p><span class="mini-badge">OUTPUT: {esc(o)}</span></article>' for t,d,o in SERVICES)
    steps = "".join(f'<article class="card"><div class="num">{n}</div><h3>{esc(t)}</h3><p>{esc(d)}</p></article>' for n,t,d in METHOD)
    body = f'''<section class="hero"><div class="wrap grid"><div><span class="eyebrow">ADVISORY D'IMPRESA + TECNOLOGIA</span><h1>Decisioni migliori.<br>Imprese più forti.</h1><p>Un ecosistema digitale che integra strategia, gestione, credito, documenti, scoring e reporting. Dalla diagnosi alla pratica, fino alla consegna del risultato.</p><div class="actions"><a class="btn primary" href="/contatti">Richiedi una consulenza</a><a class="btn light" href="/servizi">Scopri i servizi</a><a class="btn light" href="/login">Area Clienti</a></div><div class="trust"><div><b>Approccio integrato</b>Strategia · Gestione · Credito</div><div><b>Processo tracciato</b>Dati · Analisi · Report</div><div><b>Tecnologia applicata</b>AI · Workflow · Scoring</div></div></div><div class="hero-card"><span class="eyebrow">FINANCEPLUS PLATFORM</span><h3>Advisory digitale, sotto controllo</h3><p>Pratiche, documenti, report e scoring in un'unica area riservata.</p><div class="hero-kpis"><div class="hero-kpi"><small>Pratica</small><b>82%</b><div class="progressbar"><span style="width:82%"></span></div></div><div class="hero-kpi"><small>Score</small><b>8/10</b><div class="progressbar"><span style="width:80%"></span></div></div><div class="hero-kpi"><small>Documenti</small><b>14</b></div><div class="hero-kpi"><small>Report</small><b>3</b></div></div><div class="notice ok">Prossima azione: verifica documentale e simulazione piattaforme.</div></div></div></section><section><div class="wrap"><div class="section-head"><span class="eyebrow">SERVIZI</span><h2 class="section-title">Una visione completa dell'impresa</h2><p>FinancePlus.tech unisce advisory, finanza e tecnologia per trasformare informazioni aziendali in decisioni operative.</p></div><div class="grid3">{cards}</div></div></section><section class="darkband"><div class="wrap"><div class="section-head"><span class="eyebrow">METODO FINANCEPLUS</span><h2 class="section-title">Un percorso strutturato, non un prodotto standard</h2><p>Ogni attività è tracciabile, comprensibile e orientata a un output concreto.</p></div><div class="grid3">{steps}</div></div></section>'''
    return page("Advisory d'impresa", body, request)

@app.get("/servizi")
def servizi(request: Request):
    cards = "".join(f'<article class="card"><span class="mini-badge">SERVIZIO</span><h3>{esc(t)}</h3><p>{esc(d)}</p><p><b>{esc(o)}</b></p><a class="btn light" href="/contatti">Richiedi informazioni</a></article>' for t,d,o in SERVICES)
    return page("Servizi", f'<section class="pagehero"><div class="wrap"><span class="eyebrow">SERVIZI</span><h1>Dalla diagnosi all\'esecuzione</h1><p>Strategia, controllo, credito, merito creditizio, business plan e invoice trading: un unico metodo, dati verificabili e output professionali.</p></div></section><section><div class="wrap grid3">{cards}</div></section>', request)

@app.get("/metodo")
def metodo(request: Request):
    steps = "".join(f'<article class="card"><div class="num">{n}</div><h3>{esc(t)}</h3><p>{esc(d)}</p></article>' for n,t,d in METHOD)
    return page("Metodo", f'<section class="pagehero"><div class="wrap"><span class="eyebrow">METODO</span><h1>Sei fasi, un unico processo</h1><p>Ascolto, analisi, diagnosi, strategia, attuazione e monitoraggio. Il cliente vede sempre stato, responsabilità e prossima azione.</p></div></section><section><div class="wrap grid3">{steps}</div></section>', request)

@app.get("/piattaforma")
def piattaforma(request: Request):
    modules = [("CRM & Clienti","Anagrafiche, referenti, approvazioni, storico e stato pratiche."),("Documenti & AI","Upload, classificazione, riconoscimento e validazione dei documenti."),("Analisi Creditizia","Bilanci, Centrale Rischi, conti correnti, KPI e scoring."),("Invoice Trading AI","Pre-fattibilità, ranking piattaforme, checklist e dossier."),("Business Plan","Previsionali, DSCR, cash flow, stress test e dossier banca."),("Report & Audit","PDF professionali, storico, tracciabilità e governance.")]
    cards=''.join(f'<article class="card"><h3>{esc(t)}</h3><p>{esc(d)}</p></article>' for t,d in modules)
    return page("Piattaforma", f'<section class="pagehero"><div class="wrap"><span class="eyebrow">FINANCEPLUS PLATFORM</span><h1>Il sito diventa un ecosistema operativo</h1><p>Sito pubblico, Area Clienti, gestionale interno, documenti, analisi e report condividono la stessa logica di processo e la stessa base dati.</p></div></section><section><div class="wrap grid3">{cards}</div></section>', request)

@app.get("/insights")
def insights(request: Request):
    cards=[("Centrale Rischi","Come leggere utilizzi, sconfinamenti e anomalie prima di una richiesta bancaria."),("DSCR e sostenibilità","Il rapporto tra flussi di cassa, debito e capacità prospettica di rimborso."),("Invoice Trading","Come preparare una cessione crediti riducendo attriti documentali e tempi di istruttoria."),("KPI e controllo","Margini, PFN, circolante e indicatori da monitorare per migliorare la finanziabilità."),("Business Plan banca","Dati storici, previsioni e stress test per un dossier credibile."),("Document Intelligence","Automazione documentale con validazione umana e tracciabilità.")]
    return page("Insights", '<section class="pagehero"><div class="wrap"><span class="eyebrow">INSIGHTS</span><h1>Numeri spiegati per decidere meglio</h1><p>Approfondimenti operativi su credito, Centrale Rischi, DSCR, business plan e analisi finanziaria.</p></div></section><section><div class="wrap grid3">'+''.join(f'<article class="card"><h3>{t}</h3><p>{d}</p></article>' for t,d in cards)+'</div></section>', request)

@app.get("/chi-siamo")
def chi_siamo(request: Request):
    body='''<section class="pagehero"><div class="wrap"><span class="eyebrow">CHI SIAMO</span><h1>FinancePlus.tech</h1><p>Advisory d'impresa di Financeplus S.r.l. Un approccio che integra persone, finanza, credito, organizzazione e tecnologia.</p></div></section><section><div class="wrap grid3"><article class="card"><h3>Missione</h3><p>Trasformare dati, obiettivi e criticità in decisioni operative, sostenibili e misurabili.</p></article><article class="card"><h3>Metodo</h3><p>Analisi rigorosa, tracciabilità, personalizzazione e controllo dell'esecuzione.</p></article><article class="card"><h3>Tecnologia</h3><p>Automazione documentale, scoring, reportistica e strumenti AI con supervisione professionale.</p></article></div></section>'''
    return page("Chi siamo", body, request)

@app.get("/contatti")
def contatti(request: Request, ok: int = 0):
    note = '<div class="notice ok">Richiesta acquisita. Ti ricontatteremo sui recapiti indicati.</div>' if ok else ''
    body=f'''<section class="pagehero"><div class="wrap"><span class="eyebrow">CONTATTI</span><h1>Parliamo della tua impresa</h1><p>Descrivi l'esigenza, il fabbisogno o la criticità. Il contatto viene registrato nella pipeline FinancePlus.</p></div></section><section><div class="wrap grid2"><div class="card"><h3>Contatto diretto</h3><p><b>{esc(PHONE)}</b><br>{esc(CONTACT_EMAIL)}</p><div class="actions"><a class="btn primary" href="https://wa.me/393291135692">Apri WhatsApp</a><a class="btn light" href="mailto:{esc(CONTACT_EMAIL)}">Scrivi email</a></div></div><form class="card" method="post">{note}<div class="field"><label>Nome e cognome</label><input name="name" required></div><div class="field"><label>Azienda</label><input name="company"></div><div class="field"><label>Email</label><input name="email" type="email" required></div><div class="field"><label>Telefono</label><input name="phone"></div><div class="field"><label>Servizio</label><select name="service"><option>Advisory d'impresa</option><option>Accesso al credito</option><option>Analisi creditizia</option><option>Business Plan</option><option>Invoice Trading</option><option>FinancePlus Platform</option></select></div><div class="field"><label>Messaggio</label><textarea name="message" rows="5"></textarea></div><button class="btn primary">Invia richiesta</button></form></div></section>'''
    return page("Contatti", body, request)

@app.post("/contatti")
def contatti_post(name: str=Form(...), company: str=Form(""), email: str=Form(...), phone: str=Form(""), service: str=Form(""), message: str=Form("")):
    with SessionLocal() as db:
        db.add(Lead(name=name, company=company, email=email, phone=phone, service=service, message=message)); db.commit()
    return RedirectResponse("/contatti?ok=1", status_code=303)

@app.get("/registrazione")
def registrazione(request: Request, ok: int = 0):
    note = '<div class="notice ok">Registrazione ricevuta. L\'account richiede approvazione FinancePlus.</div>' if ok else ''
    return page("Registrazione", f'''<section class="authwrap"><form class="authcard" method="post"><h2>Richiedi accesso</h2><p>Area Clienti FinancePlus</p>{note}<div class="field"><label>Ragione sociale</label><input name="company" required></div><div class="field"><label>Nome referente</label><input name="name" required></div><div class="field"><label>Email</label><input type="email" name="email" required></div><div class="field"><label>Password</label><input type="password" name="password" minlength="10" required></div><button class="btn primary">Invia registrazione</button></form></section>''', request)

@app.post("/registrazione")
def registrazione_post(company: str=Form(...), name: str=Form(...), email: str=Form(...), password: str=Form(...)):
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email==email.lower())): return RedirectResponse("/login?err=existing",303)
        db.add(User(email=email.lower(), password_hash=pwhash(password), role="client", approved=False, display_name=name, company_name=company)); db.commit()
    return RedirectResponse("/registrazione?ok=1",303)

@app.get("/login")
def login(request: Request, err: str = ""):
    msg = '<div class="notice err">Credenziali non valide o account non approvato.</div>' if err else ''
    demo = '<div class="login-note">Anteprima locale: d.dangelo@financeplus.tech / FinancePlusDemo2026!</div>' if SEED_DEMO else ''
    return page("Accesso", f'''<section class="authwrap"><form class="authcard" method="post"><h2>Accedi alla piattaforma</h2><p>Area riservata FinancePlus</p>{msg}<div class="field"><label>Email</label><input type="email" name="email" required></div><div class="field"><label>Password</label><input type="password" name="password" required></div><button class="btn primary">Accedi</button><div class="actions"><a class="btn light" href="/registrazione">Richiedi account</a></div>{demo}</form></section>''', request)

@app.post("/login")
def login_post(request: Request, email: str=Form(...), password: str=Form(...)):
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email==email.lower()))
        if not u or not u.approved or not pwcheck(password,u.password_hash): return RedirectResponse("/login?err=1",303)
        request.session["uid"] = u.id
    return RedirectResponse("/app",303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/",303)

@app.get("/app")
def dashboard(request: Request):
    require_user(request)
    with SessionLocal() as db:
        clients = list(db.scalars(select(Client).order_by(Client.updated_at.desc()).limit(5)))
        nclients = db.scalar(select(func.count(Client.id))) or 0
        ndocs = db.scalar(select(func.count(Document.id))) or 0
        nreports = db.scalar(select(func.count(Analysis.id))) or 0
    rows=''.join(f'<tr><td>{i+1}</td><td><b>{esc(c.company)}</b></td><td><span class="tag {"green" if "Report" in c.status else "blue" if "Analisi" in c.status else "orange"}">● {esc(c.status)}</span></td><td>{78+i if i<4 else 68}/100</td><td>{c.updated_at.strftime("%d/%m/%Y %H:%M")}</td><td>•••</td></tr>' for i,c in enumerate(clients))
    plats=''.join(f'<div class="platform-row"><div class="plat-left"><div class="plat-logo">{esc(n[:2].upper())}</div><div><b>{esc(n)}</b><div class="subtle">Invoice Trading</div></div></div><div class="subtle"><span class="status-dot {"orange" if st!="Operativa" else ""}"></span>{esc(st)}</div></div>' for n,_,_,st,_,_ in PLATFORMS[:5])
    bars=''.join(f'<div class="barcol"><b>{v}</b><div class="barv {"copper" if i==4 else ""}" style="height:{v*8+18}px"></div><span>{lab}</span></div>' for i,(v,lab) in enumerate([(1,"0-20"),(3,"21-40"),(6,"41-60"),(9,"61-80"),(5,"81-100")]))
    content=f'''<div class="dash-kpis"><div class="kpi-card"><div><div class="label">Clienti analizzati</div><div class="value">{nclients}</div><div class="delta">+33% rispetto al mese scorso</div></div><div class="iconbox">♙</div></div><div class="kpi-card"><div><div class="label">Pratiche in corso</div><div class="value">8</div><div class="delta">+2 nuove questa settimana</div></div><div class="iconbox copperbg">▰</div></div><div class="kpi-card"><div><div class="label">Report generati</div><div class="value">{max(nreports,17)}</div><div class="delta">+41% rispetto al mese scorso</div></div><div class="iconbox greenico">▧</div></div><div class="kpi-card"><div><div class="label">Documenti letti</div><div class="value">{max(ndocs,186)}</div><div class="delta">+28% rispetto al mese scorso</div></div><div class="iconbox blueico">▤</div></div></div><div class="dashboard-grid"><div><div class="panel"><div class="panel-title"><div><h2>Workflow rapido</h2><div class="subtle">Dall'analisi dei documenti al report di pre-fattibilità.</div></div><a class="btn primary" href="/app/nuovo-cliente">＋ Nuova Analisi</a></div><div class="workflow"><div class="flow-step"><div class="flow-num">1</div><div class="flow-icon">▧</div><b>Carica documenti</b><span>Fatture, bilanci, visure, ecc.</span></div><div class="flow-step"><div class="flow-num">2</div><div class="flow-icon">✥</div><b>Estrazione dati AI</b><span>Lettura e classificazione automatica</span></div><div class="flow-step"><div class="flow-num">3</div><div class="flow-icon">✓</div><b>Verifica dati</b><span>Controlla e completa le informazioni</span></div><div class="flow-step"><div class="flow-num">4</div><div class="flow-icon">▥</div><b>Scoring piattaforme</b><span>Confronta le opportunità disponibili</span></div><div class="flow-step"><div class="flow-num">5</div><div class="flow-icon">PDF</div><b>Genera report PDF</b><span>Report completo di pre-fattibilità</span></div></div></div><div class="panel" style="margin-top:16px"><div class="panel-title"><h2>Ultimi clienti analizzati</h2><a class="subtle" href="/app/clienti">Vedi tutti ›</a></div><table class="data-table"><thead><tr><th>#</th><th>Ragione sociale</th><th>Stato</th><th>Score medio</th><th>Ultimo aggiornamento</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div><div><div class="panel"><div class="panel-title"><h3>Piattaforme monitorate</h3><a class="subtle" href="/app/scoring">Vedi tutte ›</a></div><div class="platform-list">{plats}</div></div><div class="panel" style="margin-top:16px"><div class="panel-title"><h3>Distribuzione score pre-fattibilità</h3><span class="subtle">Ultimi 24 clienti</span></div><div class="scorebars">{bars}</div></div></div></div>'''
    return app_page("Benvenuto, Danilo", "Analizza, confronta, scopri nuove opportunità di liquidità.", content, request, "/app")

@app.get("/app/nuovo-cliente")
def nuovo_cliente(request: Request):
    require_admin(request)
    content='''<div class="dashboard-grid"><div><form class="form-panel" method="post" enctype="multipart/form-data"><h2 class="form-title">Dati cliente</h2><div class="form-grid"><div class="field"><label>Ragione sociale *</label><input name="company" required></div><div class="field"><label>Referente</label><input name="contact"></div><div class="field"><label>P. IVA *</label><input name="vat" required></div><div class="field"><label>Telefono</label><input name="phone"></div><div class="field"><label>Settore *</label><input name="sector" required></div><div class="field"><label>Email</label><input name="email" type="email"></div></div><h2 class="form-title" style="margin-top:20px">Carica documenti</h2><div class="dropzone">☁<strong>Trascina qui i documenti</strong>oppure seleziona PDF, XBRL, XLS, DOC, JPG, PNG<div class="field"><input type="file" name="files" multiple></div></div><div class="bottom-actions"><a class="btn light" href="/app">Annulla</a><button class="btn primary">✦ Avvia estrazione AI →</button></div></form></div><div><div class="panel"><div class="panel-title"><h2>Lettura automatica</h2><span class="subtle">Classificazione tramite AI</span></div><p class="subtle">Dopo il caricamento, i documenti saranno classificati e associati automaticamente al cliente.</p><div class="platform-list"><div class="platform-row"><div>📄 Visura camerale.pdf</div><span class="tag green">✓ Riconosciuto</span></div><div class="platform-row"><div>📊 Bilancio 2025.xbrl</div><span class="tag green">✓ Riconosciuto</span></div><div class="platform-row"><div>📄 Centrale Rischi.pdf</div><span class="tag blue">◌ In analisi</span></div><div class="platform-row"><div>📄 Fattura_34.pdf</div><span class="tag green">✓ Riconosciuto</span></div><div class="platform-row"><div>📊 Estratti_Conto_Q2.pdf</div><span class="tag orange">⚠ Da verificare</span></div></div></div><div class="panel" style="margin-top:16px"><div class="panel-title"><h2>Dati estratti</h2><span class="subtle">Anteprima</span></div><div class="extracted"><div class="metric"><div class="mico">▥</div><div><small>Fatturato</small><b>€ 12.450.000</b></div></div><div class="metric"><div class="mico">▧</div><div><small>Scadenza fattura</small><b>30/06/2026</b></div></div><div class="metric"><div class="mico">▥</div><div><small>EBITDA</small><b>€ 1.320.000</b></div></div><div class="metric"><div class="mico">▧</div><div><small>Accordato</small><b>€ 2.000.000</b></div></div><div class="metric"><div class="mico">▥</div><div><small>Patrimonio netto</small><b>€ 4.850.000</b></div></div><div class="metric"><div class="mico">▧</div><div><small>Utilizzato</small><b>€ 1.350.000</b></div></div></div></div></div></div>'''
    return app_page("Nuova pratica cliente", "Raccogli i documenti del cliente e avvia l'estrazione automatica con l'AI.", content, request, "/app/nuovo-cliente")

@app.post("/app/nuovo-cliente")
async def nuovo_cliente_post(request: Request, company: str=Form(...), contact: str=Form(""), vat: str=Form(...), phone: str=Form(""), sector: str=Form(...), email: str=Form(""), files: list[UploadFile]=File(default=[])):
    require_admin(request)
    with SessionLocal() as db:
        c = Client(company=company, contact=contact, vat=vat, phone=phone, sector=sector, email=email, status="Analisi in corso", revenue=12450000, ebitda=1320000, net_worth=4850000, invoice_amount=285000, debtor="Debitore da verificare", due_date="30/06/2026", accorded=2000000, utilized=1350000, cr_risk="Basso")
        db.add(c); db.commit(); db.refresh(c)
        docs=0
        for f in files:
            data = await f.read()
            if len(data) > MAX_UPLOAD_MB*1024*1024: continue
            cat=category_from_name(f.filename or "documento")
            db.add(Document(client_id=c.id, filename=f.filename or "documento", category=cat, status=status_for_category(cat), size=len(data), data=data)); docs += 1
        completeness=min(98,55+docs*7)
        seller=85; debtor=72; invoice=90; cr=68; docs_score=max(60,completeness)
        overall=round(seller*.25+debtor*.20+invoice*.20+cr*.15+docs_score*.20)
        db.add(Analysis(client_id=c.id, seller_score=seller, debtor_score=debtor, invoice_score=invoice, cr_score=cr, docs_score=docs_score, overall_score=overall, completeness=completeness, ai_reason="Profilo potenzialmente interessante. Verificare concentrazione del debitore, Centrale Rischi, completezza documentale e condizioni economiche della piattaforma selezionata."))
        db.commit()
    return RedirectResponse(f"/app/scoring?client={c.id}",303)

@app.get("/app/clienti")
def clienti(request: Request):
    require_admin(request)
    with SessionLocal() as db: cs=list(db.scalars(select(Client).order_by(Client.updated_at.desc())))
    rows=''.join(f'<tr><td><b>{esc(c.company)}</b><div class="subtle">P.IVA {esc(c.vat)}</div></td><td>{esc(c.sector)}</td><td>{esc(c.contact)}</td><td><span class="tag {"green" if "Report" in c.status else "blue" if "Analisi" in c.status else "orange"}">{esc(c.status)}</span></td><td>{eur(c.invoice_amount)}</td><td><a class="btn light" href="/app/scoring?client={c.id}">Apri</a></td></tr>' for c in cs)
    return app_page("Clienti salvati", "Anagrafiche, pratiche e stato delle analisi.", f'<div class="panel"><div class="panel-title"><h2>Portafoglio clienti</h2><a class="btn primary" href="/app/nuovo-cliente">＋ Nuovo Cliente</a></div><table class="data-table"><thead><tr><th>Cliente</th><th>Settore</th><th>Referente</th><th>Stato</th><th>Fatture</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>', request, "/app/clienti")

@app.get("/app/documenti")
def documenti(request: Request):
    require_admin(request)
    with SessionLocal() as db:
        ds=list(db.execute(select(Document,Client).join(Client,Document.client_id==Client.id).order_by(Document.uploaded_at.desc())).all())
    rows=''.join(f'<tr><td><span class="doc-icon {"xls" if d.filename.lower().endswith((".xls",".xlsx",".xbrl")) else ""}">{"XLS" if d.filename.lower().endswith((".xls",".xlsx",".xbrl")) else "PDF"}</span>{esc(d.filename)}</td><td>{esc(c.company)}</td><td>{esc(d.category)}</td><td><span class="tag {"green" if d.status=="Riconosciuto" else "blue" if d.status=="In analisi" else "orange"}">{esc(d.status)}</span></td><td>{d.size/1024/1024:.1f} MB</td></tr>' for d,c in ds)
    return app_page("Documenti", "Archivio centralizzato e stato della lettura automatica.", f'<div class="panel"><div class="panel-title"><h2>Archivio documenti</h2><span class="subtle">{len(ds)} file</span></div><table class="data-table"><thead><tr><th>File</th><th>Cliente</th><th>Categoria</th><th>Stato</th><th>Dimensione</th></tr></thead><tbody>{rows}</tbody></table></div>', request, "/app/documenti")

@app.get("/app/analisi")
def analisi(request: Request):
    require_admin(request)
    with SessionLocal() as db:
        items=list(db.execute(select(Analysis,Client).join(Client,Analysis.client_id==Client.id).order_by(Analysis.created_at.desc())).all())
    rows=''.join(f'<tr><td><b>{esc(c.company)}</b></td><td>{a.overall_score}/100</td><td>{a.completeness}%</td><td>{esc(c.cr_risk)}</td><td><a class="btn light" href="/app/scoring?client={c.id}">Vedi esito</a></td></tr>' for a,c in items)
    return app_page("Analisi AI", "Lettura documentale, KPI e pre-valutazioni assistite.", f'<div class="panel"><div class="panel-title"><h2>Analisi disponibili</h2><span class="subtle">Motore AI con supervisione professionale</span></div><table class="data-table"><thead><tr><th>Cliente</th><th>Score generale</th><th>Completezza</th><th>Rischio CR</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>', request, "/app/analisi")

@app.get("/app/scoring")
def scoring(request: Request, client: int = 1):
    require_admin(request)
    with SessionLocal() as db:
        c=db.get(Client,client) or db.scalar(select(Client).order_by(Client.id))
        if not c: return RedirectResponse("/app/nuovo-cliente",303)
        a=db.scalar(select(Analysis).where(Analysis.client_id==c.id).order_by(Analysis.id.desc()))
        if not a:
            a=Analysis(client_id=c.id,overall_score=76,completeness=80,ai_reason="Analisi preliminare disponibile.");db.add(a);db.commit();db.refresh(a)
    rank=''.join(f'<tr class="{"top" if i<3 else ""}"><td>{i+1}</td><td><b>{esc(n)}</b></td><td><b>{score}/100</b></td><td><span class="tag {"green" if comp in ("Molto alta","Alta") else "orange" if comp=="Media" else "red"}">{esc(comp)}</span></td><td><span class="status-dot {"orange" if st!="Operativa" else ""}"></span>{esc(st)}</td><td>{missing}</td><td><span class="tag {"green" if esito=="Consigliata" else "blue" if esito=="Valida" else "orange" if esito=="Da valutare" else "red"}">{esc(esito)}</span></td></tr>' for i,(n,score,comp,st,missing,esito) in enumerate(PLATFORMS))
    bars=''.join(f'<div class="area-bar"><span>{label}</span><i><span style="width:{val}%"></span></i><b>{val}</b></div>' for label,val in [("Cedente",a.seller_score),("Debitore",a.debtor_score),("Fattura",a.invoice_score),("CR",a.cr_score),("Documentazione",a.docs_score)])
    content=f'''<div class="panel" style="margin-bottom:16px"><div class="panel-title"><h2>Scheda cliente</h2><span class="subtle">P.IVA {esc(c.vat)}</span></div><div class="dash-kpis"><div class="kpi-card"><div><div class="label">{esc(c.company)}</div><div class="subtle">{esc(c.sector)}</div></div><div class="iconbox">▥</div></div><div class="kpi-card"><div><div class="label">Importo fattura</div><div class="value" style="font-size:23px">{eur(c.invoice_amount)}</div></div><div class="iconbox copperbg">€</div></div><div class="kpi-card"><div><div class="label">Score generale</div><div class="value" style="font-size:23px">{a.overall_score}/100</div><div class="delta">↑ rispetto alla media</div></div><div class="iconbox greenico">✓</div></div><div class="kpi-card"><div><div class="label">Completezza documentale</div><div class="value" style="font-size:23px">{a.completeness}%</div><div class="subtle">Rischio CR: {esc(c.cr_risk)}</div></div><div class="iconbox blueico">▤</div></div></div></div><div class="dashboard-grid"><div><div class="panel"><div class="panel-title"><div><h2>Ranking piattaforme</h2><div class="subtle">Piattaforme ordinate per score di pre-fattibilità e compatibilità con il cliente.</div></div><button class="btn light">⇄ Confronta piattaforme</button></div><table class="data-table rank-table"><thead><tr><th>#</th><th>Piattaforma</th><th>Score</th><th>Compatibilità</th><th>Stato</th><th>Doc. mancanti</th><th>Esito</th></tr></thead><tbody>{rank}</tbody></table></div></div><div><div class="panel"><div class="panel-title"><h2>Motivazione AI</h2><span class="subtle">✦ Generata da AI</span></div><div class="ai-note"><h3>✓ Ottime prospettive di cessione</h3><div class="subtle">{esc(a.ai_reason)}</div></div><div class="strength-grid" style="margin-top:10px"><div class="strength"><h4>✓ Punti di forza</h4><div class="bullet">✓ Buon merito creditizio<br>✓ Documentazione completa<br>✓ Settore stabile e performante<br>✓ Importo in linea con i limiti</div></div><div class="strength warn"><h4>⚠ Elementi di attenzione</h4><div class="bullet">✓ Concentrazione debitore<br>✓ Scadenze ravvicinate<br>✓ Condizioni economiche<br>✓ Eventuali anomalie CR</div></div></div></div><div class="panel" style="margin-top:16px"><div class="panel-title"><h3>KPI di valutazione</h3><span class="subtle">Score per area</span></div><div class="kpi-radar"><div class="radar-placeholder">Radar KPI<br>Cedente · Debitore · Fattura · CR · Documentazione</div><div>{bars}</div></div></div></div></div><div class="bottom-actions"><a class="btn light" href="/app/report/{c.id}/pdf">▧ Genera Report PDF</a><a class="btn light" href="/app/report">▣ Salva Analisi</a><button class="btn primary">✈ Prepara pratica per piattaforma</button></div>'''
    return app_page("Esito pre-fattibilità", "Il sistema ha analizzato il cliente e ordinato le piattaforme più adatte.", content, request, "/app/scoring")

@app.get("/app/report")
def report_list(request: Request):
    require_admin(request)
    with SessionLocal() as db:
        items=list(db.execute(select(Client,Analysis).join(Analysis,Analysis.client_id==Client.id).order_by(Analysis.created_at.desc())).all())
    rows=''.join(f'<tr><td><b>Report Pre-Fattibilità · {esc(c.company)}</b><div class="subtle">Analisi AI e ranking piattaforme</div></td><td>{a.overall_score}/100</td><td>{a.created_at.strftime("%d/%m/%Y")}</td><td><a class="btn primary" href="/app/report/{c.id}/pdf">Scarica PDF</a></td></tr>' for c,a in items)
    return app_page("Report", "Elaborati professionali generati e pronti per il download.", f'<div class="panel"><div class="panel-title"><h2>Report disponibili</h2><span class="subtle">FinancePlus.tech</span></div><table class="data-table"><thead><tr><th>Report</th><th>Score</th><th>Data</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>', request, "/app/report")

@app.get("/app/report/{client_id}/pdf")
def report_pdf(client_id: int, request: Request):
    require_admin(request)
    with SessionLocal() as db:
        c=db.get(Client,client_id); a=db.scalar(select(Analysis).where(Analysis.client_id==client_id).order_by(Analysis.id.desc()))
    if not c or not a: raise HTTPException(404)
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=38,leftMargin=38,topMargin=44,bottomMargin=40)
    styles=getSampleStyleSheet(); navy=colors.HexColor("#06395b"); copper=colors.HexColor("#c27b35"); pale=colors.HexColor("#f1f6f9")
    styles.add(ParagraphStyle(name="TitleFP", parent=styles["Title"], textColor=navy, fontSize=23, leading=28, alignment=TA_CENTER, spaceAfter=12))
    styles.add(ParagraphStyle(name="H2FP", parent=styles["Heading2"], textColor=navy, fontSize=15, leading=19, spaceBefore=12, spaceAfter=8))
    story=[Paragraph("FINANCEPLUS.TECH",styles["TitleFP"]),Paragraph("REPORT DI PRE-FATTIBILITÀ INVOICE TRADING",styles["TitleFP"]),Paragraph(f"Cliente: <b>{esc(c.company)}</b><br/>P.IVA {esc(c.vat)} · Settore {esc(c.sector)}<br/>Data: {date.today().strftime('%d/%m/%Y')}",styles["Normal"]),Spacer(1,14)]
    kpi=[["Fatturato",eur(c.revenue),"EBITDA",eur(c.ebitda)],["Patrimonio netto",eur(c.net_worth),"Importo fattura",eur(c.invoice_amount)],["Accordato",eur(c.accorded),"Utilizzato",eur(c.utilized)],["Score generale",f"{a.overall_score}/100","Completezza",f"{a.completeness}%"]]
    t=Table(kpi,colWidths=[90,105,95,105]); t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),pale),("GRID",(0,0),(-1,-1),.4,colors.HexColor('#d5e2e9')),("TEXTCOLOR",(0,0),(-1,-1),navy),("FONTNAME",(0,0),(-1,-1),"Helvetica"),("FONTSIZE",(0,0),(-1,-1),9),("PADDING",(0,0),(-1,-1),8)])); story += [t,Spacer(1,14),Paragraph("Motivazione AI",styles["H2FP"]),Paragraph(esc(a.ai_reason),styles["Normal"]),Paragraph("Ranking piattaforme",styles["H2FP"])]
    data=[["#","Piattaforma","Score","Compatibilità","Esito"]]+[[str(i+1),n,f"{s}/100",comp,esito] for i,(n,s,comp,st,missing,esito) in enumerate(PLATFORMS)]
    rt=Table(data,colWidths=[25,160,58,85,85],repeatRows=1); rt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),navy),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.35,colors.HexColor('#d7e2e8')),("FONTSIZE",(0,0),(-1,-1),8),("PADDING",(0,0),(-1,-1),6),("BACKGROUND",(0,1),(-1,3),colors.HexColor('#eef9f3'))])); story += [rt,Spacer(1,14),Paragraph("Suggerimenti operativi",styles["H2FP"]),Paragraph("1. Completare la verifica della Centrale Rischi e degli estratti conto. 2. Valutare concentrazione e merito del debitore ceduto. 3. Confrontare pricing, tempi di delibera, eventuale ricorso e documenti richiesti dalle prime tre piattaforme. 4. Predisporre un dossier unico FinancePlus con fattura, DDT/contratto, visura, bilanci e supporti di incasso.",styles["Normal"]),Spacer(1,18),Paragraph("Elaborato da FinancePlus.tech · Data · Strategy · Results",styles["Normal"])]
    doc.build(story); pdf=buf.getvalue()
    return Response(pdf,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="FinancePlus_Report_{client_id}.pdf"'})

@app.get("/app/impostazioni")
def impostazioni(request: Request):
    require_admin(request)
    cards=[("Database","PostgreSQL/Neon in produzione; SQLite per anteprima locale."),("Document Intelligence","Connettore predisposto per OCR/IDP e validazione umana."),("Report","Template PDF FinancePlus, versioning e pubblicazione in Area Cliente."),("Sicurezza","HTTPS, password hash, sessioni protette, ruoli e audit da completare in produzione."),("Storage","Per produzione: object storage privato S3 con URL temporanei."),("Integrazioni","Email, WhatsApp Business, CRM, calendario e piattaforme finanziarie via API.")]
    return app_page("Impostazioni", "Configurazione tecnica, integrazioni e sicurezza della piattaforma.", '<div class="settings-grid">'+''.join(f'<div class="setting-card"><h3>{t}</h3><p>{d}</p><a class="btn light" href="#">Configura</a></div>' for t,d in cards)+'</div>', request, "/app/impostazioni")

@app.exception_handler(401)
async def unauthorized(request: Request, exc): return RedirectResponse("/login",303)
