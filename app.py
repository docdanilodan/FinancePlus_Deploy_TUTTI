from __future__ import annotations

import base64
import hashlib
import hmac
import html
import os
import secrets
import smtplib
import ssl
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse, PlainTextResponse
from sqlalchemy import create_engine, String, Integer, Boolean, DateTime, Float, ForeignKey, Text, LargeBinary, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

APP_NAME = "FinancePlus.tech"
DATABASE_URL = os.environ["DATABASE_URL"]
SECRET_KEY = os.environ["SECRET_KEY"]
BASE_URL = os.getenv("BASE_URL", "https://financeplus.tech").rstrip("/")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "d.dangelo@financeplus.tech").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "d.dangelo@financeplus.tech").strip().lower()
PHONE = os.getenv("PHONE", "+393291135692")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "1").lower() in {"1", "true", "yes", "on"}

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(30), default="client")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    company_name: Mapped[str] = mapped_column(String(255), default="")
    vat: Mapped[str] = mapped_column(String(40), default="")
    contact_name: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(80), default="")
    service: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Practice(Base):
    __tablename__ = "practices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    product: Mapped[str] = mapped_column(String(255), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    institution: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(100), default="Da avviare")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    practice_id: Mapped[Optional[int]] = mapped_column(ForeignKey("practices.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(120), default="Altro")
    status: Mapped[str] = mapped_column(String(80), default="Caricato")
    is_report: Mapped[bool] = mapped_column(Boolean, default=False)
    size: Mapped[int] = mapped_column(Integer, default=0)
    file_data: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

def password_hash(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(dk).decode()

def password_verify(password: str, encoded: str) -> bool:
    try:
        _, salt_b64, hash_b64 = encoded.split("$", 2)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(hash_b64.encode())
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def seed_admin() -> None:
    if not ADMIN_PASSWORD:
        raise RuntimeError("ADMIN_PASSWORD non configurata")
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if not admin:
            db.add(User(email=ADMIN_EMAIL, password_hash=password_hash(ADMIN_PASSWORD), role="admin", approved=True, company_name="Financeplus S.r.l.", contact_name="Amministratore FinancePlus", phone=PHONE))
            db.commit()

seed_admin()

app = FastAPI(title="FinancePlus Platform", version="1.0")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=SESSION_HTTPS_ONLY, max_age=60 * 60 * 8)

SERVICES = [
    ("Strategia e sviluppo d'impresa", "Diagnosi strategica, scenari, priorità, crescita e investimenti."),
    ("Pianificazione e controllo", "Budget, forecast, KPI, margini, costi e analisi degli scostamenti."),
    ("Accesso al credito", "Pre-valutazione, dossier banca, selezione istituti e assistenza alla pratica."),
    ("Merito creditizio", "Bilanci, Centrale Rischi, flussi, scoring, anomalie e piano di miglioramento."),
    ("Business plan e investimenti", "Piani economico-finanziari, fabbisogno, cash flow, DSCR e stress test."),
    ("Organizzazione e innovazione", "Digitalizzazione, procedure, archivio, dashboard e automazione documentale."),
]
METHOD = [
    ("01", "Ascolto e raccolta dati", "Obiettivi, struttura, documenti e vincoli."),
    ("02", "Analisi", "Bilanci, CR, flussi, organizzazione, investimenti e mercato."),
    ("03", "Diagnosi", "Criticità, rischi, opportunità e priorità."),
    ("04", "Strategia", "Scenari, obiettivi, azioni, responsabilità e tempi."),
    ("05", "Attuazione", "Supporto operativo a pratiche, processi e documenti."),
    ("06", "Monitoraggio", "KPI, avanzamento, variazioni e interventi correttivi."),
]
STATES = ["Da avviare", "Documenti richiesti", "Documentazione incompleta", "In analisi", "Pronta per invio", "Inviata all'istituto", "In valutazione", "Deliberata", "Erogata", "Conclusa", "Sospesa"]
DOC_CATEGORIES = ["Visura camerale", "Bilancio", "Situazione contabile", "Centrale Rischi", "Estratto conto", "DURC", "Documento identità", "Contratto", "Business plan", "Altro"]
ALLOWED_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".csv", ".xml", ".p7m", ".zip"}

def esc(v) -> str:
    return html.escape(str(v or ""), quote=True)

def money(v: float) -> str:
    return f"€ {v:,.0f}".replace(",", ".")

def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token

def check_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf")
    if not expected or not hmac.compare_digest(expected, token or ""):
        raise HTTPException(status_code=400, detail="Token CSRF non valido")

def current_user(request: Request):
    uid = request.session.get("user_id")
    if not uid:
        return None
    with SessionLocal() as db:
        return db.get(User, uid)

def require_user(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(status_code=401)
    return u

def require_admin(request: Request):
    u = require_user(request)
    if u.role != "admin":
        raise HTTPException(status_code=403)
    return u

def nav(request: Request) -> str:
    u = current_user(request)
    account = f'<a class="login" href="{("/admin" if u.role == "admin" else "/area-clienti")}">Dashboard</a><a href="/logout">Esci</a>' if u else '<a class="login" href="/login">Area Clienti</a>'
    return f'''<header class="top"><div class="wrap topin"><span>Financeplus S.r.l. · Advisory d'impresa</span><span><a href="tel:{PHONE}">{PHONE}</a> · <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></span></div></header>
<header class="head"><div class="wrap nav"><a class="brand" href="/"><img src="/logo.png" alt="FinancePlus.tech"><span><b>FinancePlus.tech</b><small>DATA · STRATEGY · RESULTS</small></span></a><nav><a href="/">Home</a><a href="/servizi">Servizi</a><a href="/metodo">Metodo</a><a href="/chi-siamo">Chi siamo</a><a href="/insights">Insights</a><a href="/contatti">Contatti</a>{account}<a class="cta" href="/contatti">Richiedi consulenza</a></nav></div></header>'''

CSS = r'''
:root{--navy:#0b3552;--blue:#164e73;--copper:#bd7935;--ink:#173047;--pale:#f4f8fb;--line:#dce7ee;--green:#287e64;--red:#a94538}*{box-sizing:border-box}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;color:var(--ink);background:#fff}a{color:inherit;text-decoration:none}.wrap{width:min(1160px,92%);margin:auto}.top{background:#0a2d47;color:#dce9f2;font-size:12px}.topin{display:flex;justify-content:space-between;padding:8px 0;gap:20px}.head{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);backdrop-filter:blur(10px)}.nav{display:flex;align-items:center;justify-content:space-between;min-height:78px;gap:24px}.brand{display:flex;align-items:center;gap:10px}.brand img{width:54px;height:54px;object-fit:contain}.brand b{display:block;color:#0c3553;font-size:20px}.brand small{font-size:9px;letter-spacing:1.7px;color:#8a6b4b}.nav nav{display:flex;align-items:center;gap:17px;font-size:14px;font-weight:650}.nav nav a:hover{color:var(--copper)}.login{border:1px solid var(--line);padding:9px 13px;border-radius:11px}.cta,.btn{background:var(--copper)!important;color:#fff!important;border:0;border-radius:12px;padding:12px 18px;font-weight:750;cursor:pointer;display:inline-block}.btn.alt{background:#fff!important;color:var(--navy)!important;border:1px solid var(--navy)}.hero{background:linear-gradient(120deg,#edf7fc 0,#fff 55%,#f5efe8 100%);padding:82px 0 70px;overflow:hidden}.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:60px;align-items:center}.eyebrow{font-size:12px;font-weight:850;letter-spacing:1.5px;color:var(--copper);text-transform:uppercase}.hero h1{font-family:Georgia,serif;color:var(--navy);font-size:56px;line-height:1.02;margin:12px 0 18px}.hero p{font-size:19px;line-height:1.65;color:#476275;max-width:740px}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}.hero-panel,.card,.panel,.tablebox,.formbox{background:#fff;border:1px solid var(--line);border-radius:20px;box-shadow:0 14px 35px rgba(20,55,77,.08)}.hero-panel{padding:26px}.hero-panel h3{color:var(--navy);margin-top:0}.metric{display:flex;justify-content:space-between;border-top:1px solid var(--line);padding:15px 0}.metric strong{color:var(--copper)}section{padding:64px 0}.section-head{text-align:center;max-width:760px;margin:0 auto 34px}.section-head h2,.page-title{font-family:Georgia,serif;color:var(--navy);font-size:39px;margin:8px 0 12px}.muted{color:#637989}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.grid2{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}.card{padding:25px}.card h3{color:var(--navy);margin:8px 0}.number{width:38px;height:38px;border:1px solid #d8b48d;border-radius:12px;display:grid;place-items:center;color:var(--copper);font-weight:850}.band{background:var(--navy);color:#fff}.band h2{color:#fff}.band .card{background:#123f5e;border-color:#285774;box-shadow:none}.band .card h3{color:#fff}.pagehero{padding:46px 0;background:#f0f7fb;border-bottom:1px solid var(--line)}.pagehero p{max-width:760px;color:#5d7687;line-height:1.7}.content{padding:42px 0 70px}.formbox{padding:26px}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.full{grid-column:1/-1}label{display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:700}input,select,textarea{width:100%;border:1px solid #cfdde6;border-radius:11px;padding:12px 13px;font:inherit;background:#fff}textarea{resize:vertical}.notice{border-radius:12px;padding:12px 14px;margin:12px 0}.ok{background:#eaf7f1;color:#236b56}.err{background:#faece9;color:#963e33}.portal{background:#f4f8fb;min-height:70vh}.portalgrid{display:grid;grid-template-columns:220px 1fr;gap:24px}.side{background:var(--navy);border-radius:18px;padding:18px;color:#fff;height:max-content}.side a{display:block;padding:10px 12px;border-radius:9px;margin:3px 0}.side a:hover{background:#164e73}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}.kpi{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px}.kpi strong{display:block;font-size:28px;color:var(--navy)}.tablebox{overflow:auto}.tablebox h3{padding:18px 18px 0;color:var(--navy)}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:13px 15px;border-top:1px solid var(--line);vertical-align:top}th{font-size:11px;text-transform:uppercase;color:#6e8290;background:#f8fafc}.badge{display:inline-block;padding:4px 9px;border-radius:999px;background:#edf3f7;color:#36576d;font-size:12px}.footer{background:#071f31;color:#cfdee8;padding:48px 0 20px}.footergrid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:32px}.footer h4{color:#fff}.footer a{display:block;margin:7px 0}.fine{border-top:1px solid #244054;margin-top:28px;padding-top:18px;font-size:12px}.whatsapp{position:fixed;right:22px;bottom:22px;width:52px;height:52px;border-radius:50%;background:#1fa865;color:white;display:grid;place-items:center;font-weight:850;box-shadow:0 8px 20px #0003}@media(max-width:900px){.nav nav{display:none}.hero-grid,.grid3,.grid2,.portalgrid{grid-template-columns:1fr}.hero h1{font-size:42px}.kpis{grid-template-columns:1fr 1fr}.side{display:flex;overflow:auto;gap:4px}.side a{white-space:nowrap}.formgrid{grid-template-columns:1fr}.full{grid-column:auto}}@media(max-width:550px){.topin{display:block}.hero{padding-top:52px}.hero h1{font-size:36px}.section-head h2,.page-title{font-size:32px}.kpis{grid-template-columns:1fr}.footergrid{grid-template-columns:1fr}.brand span{display:none}}
'''

def layout(request: Request, title: str, body: str) -> HTMLResponse:
    footer = f'''<footer class="footer"><div class="wrap footergrid"><div><h4>FinancePlus.tech</h4><p>Advisory d'impresa · Consulenza integrata per la strategia, la gestione e il credito.</p><p>Data · Strategy · Results</p></div><div><h4>Piattaforma</h4><a href="/login">Area Clienti</a><a href="/registrazione">Richiedi account</a><a href="/privacy">Privacy</a><a href="/cookie">Cookie</a></div><div><h4>Contatti</h4><a href="tel:{PHONE}">{PHONE}</a><a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a><a href="https://wa.me/{PHONE.replace('+','')}">WhatsApp</a></div></div><div class="wrap fine">© {datetime.now().year} Financeplus S.r.l. · P.IVA 04825280615</div></footer><a class="whatsapp" href="https://wa.me/{PHONE.replace('+','')}">WA</a>'''
    page = f'''<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><meta name="description" content="FinancePlus.tech: advisory d'impresa, strategia, gestione, credito, business plan e merito creditizio."><style>{CSS}</style></head><body>{nav(request)}<main>{body}</main>{footer}</body></html>'''
    return HTMLResponse(page)

def notify_contact(lead: Lead) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    pwd = os.getenv("SMTP_PASSWORD", "")
    if not host or not pwd:
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Nuovo contatto FinancePlus: {lead.service or 'Richiesta'}"
        msg["From"] = os.getenv("SMTP_FROM", CONTACT_EMAIL)
        msg["To"] = CONTACT_EMAIL
        msg.set_content(f"Nominativo: {lead.name}\nAzienda: {lead.company}\nEmail: {lead.email}\nTelefono: {lead.phone}\nServizio: {lead.service}\n\n{lead.message}")
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as server:
            server.starttls(context=ctx)
            server.login(os.getenv("SMTP_USER", CONTACT_EMAIL), pwd)
            server.send_message(msg)
    except Exception:
        pass

@app.get("/logo.png")
def logo():
    p = Path("logo.png")
    if not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(p, media_type="image/png")

@app.get("/health")
def health():
    return {"status": "ok", "service": "financeplus-site-platform"}

@app.get("/")
def home(request: Request):
    services = ''.join(f'<div class="card"><span class="eyebrow">SERVIZIO</span><h3>{esc(t)}</h3><p class="muted">{esc(d)}</p></div>' for t,d in SERVICES)
    method = ''.join(f'<div class="card"><div class="number">{n}</div><h3>{esc(t)}</h3><p class="muted">{esc(d)}</p></div>' for n,t,d in METHOD)
    body = f'''<section class="hero"><div class="wrap hero-grid"><div><span class="eyebrow">ADVISORY D'IMPRESA</span><h1>Decisioni migliori.<br>Imprese più forti.</h1><p>Consulenza integrata per la strategia, la gestione e il credito. Trasformiamo dati, obiettivi e criticità in percorsi concreti di crescita, controllo e sostenibilità finanziaria.</p><div class="actions"><a class="btn" href="/contatti">Richiedi una consulenza</a><a class="btn alt" href="/servizi">Scopri i servizi</a></div></div><div class="hero-panel"><h3>FinancePlus Platform</h3><p class="muted">Un unico ambiente per relazione con il cliente, pratiche, documenti, report e comunicazioni.</p><div class="metric"><span>Area Clienti</span><strong>Riservata</strong></div><div class="metric"><span>Pratiche</span><strong>Tracciate</strong></div><div class="metric"><span>Documenti</span><strong>Protetti</strong></div><div class="metric"><span>Database</span><strong>Neon</strong></div></div></div></section><section><div class="wrap"><div class="section-head"><span class="eyebrow">AREE DI INTERVENTO</span><h2>Una visione completa dell'impresa</h2><p class="muted">Strategia, numeri, credito e innovazione vengono letti come parti dello stesso sistema.</p></div><div class="grid3">{services}</div></div></section><section class="band"><div class="wrap"><div class="section-head"><span class="eyebrow">METODO FINANCEPLUS</span><h2>Un percorso strutturato, non un prodotto standard</h2></div><div class="grid3">{method}</div></div></section>'''
    return layout(request, "FinancePlus.tech | Advisory d'impresa", body)

@app.get("/servizi")
def services(request: Request):
    cards=''.join(f'<div class="card"><h3>{esc(t)}</h3><p class="muted">{esc(d)}</p><p><a href="/contatti"><b>Richiedi informazioni →</b></a></p></div>' for t,d in SERVICES)
    return layout(request, "Servizi | FinancePlus.tech", f'<section class="pagehero"><div class="wrap"><span class="eyebrow">SERVIZI</span><h1 class="page-title">Aree di intervento</h1><p>Affianchiamo PMI e imprenditori con percorsi personalizzati basati su dati, analisi, pianificazione e assistenza operativa.</p></div></section><section class="content"><div class="wrap grid2">{cards}</div></section>')

@app.get("/metodo")
def metodo(request: Request):
    rows=''.join(f'<div class="card"><div class="number">{n}</div><h3>{esc(t)}</h3><p class="muted">{esc(d)}</p></div>' for n,t,d in METHOD)
    return layout(request, "Metodo | FinancePlus.tech", f'<section class="pagehero"><div class="wrap"><span class="eyebrow">METODO</span><h1 class="page-title">Dai dati al risultato</h1><p>Ogni incarico segue un processo tracciabile: raccolta, analisi, diagnosi, strategia, attuazione e monitoraggio.</p></div></section><section class="content"><div class="wrap grid2">{rows}</div></section>')

@app.get("/chi-siamo")
def about(request: Request):
    body='''<section class="pagehero"><div class="wrap"><span class="eyebrow">CHI SIAMO</span><h1 class="page-title">FinancePlus.tech</h1><p>FinancePlus.tech è la divisione di advisory d'impresa di Financeplus S.r.l. L'approccio integra economia, finanza, credito, organizzazione e tecnologia.</p></div></section><section class="content"><div class="wrap grid3"><div class="card"><h3>Missione</h3><p class="muted">Rendere più leggibili le decisioni d'impresa e trasformare dati e documenti in azioni concrete.</p></div><div class="card"><h3>Metodo</h3><p class="muted">Analisi rigorosa, tracciabilità, personalizzazione e supervisione professionale.</p></div><div class="card"><h3>Tecnologia</h3><p class="muted">Piattaforma digitale per pratiche, documenti, report, comunicazioni e automazioni future.</p></div></div></section>'''
    return layout(request, "Chi siamo | FinancePlus.tech", body)

@app.get("/insights")
def insights(request: Request):
    body='''<section class="pagehero"><div class="wrap"><span class="eyebrow">INSIGHTS</span><h1 class="page-title">Analisi e approfondimenti</h1><p>Contenuti dedicati a credito, Centrale Rischi, KPI, controllo di gestione e business plan.</p></div></section><section class="content"><div class="wrap grid3"><div class="card"><span class="eyebrow">CREDITO</span><h3>Centrale Rischi: cosa osservare</h3><p class="muted">Accordato, utilizzato, saturazione, sconfinamenti e trend prima della richiesta di credito.</p></div><div class="card"><span class="eyebrow">BUSINESS PLAN</span><h3>DSCR e sostenibilità del debito</h3><p class="muted">Collegare fabbisogno, servizio del debito, flussi prospettici e stress test.</p></div><div class="card"><span class="eyebrow">PERFORMANCE</span><h3>KPI collegati alle decisioni</h3><p class="muted">Pochi indicatori, soglie chiare e azioni correttive misurabili.</p></div></div></section>'''
    return layout(request, "Insights | FinancePlus.tech", body)

@app.get("/contatti")
def contact_get(request: Request):
    token=csrf_token(request)
    form=f'''<section class="pagehero"><div class="wrap"><span class="eyebrow">CONTATTI</span><h1 class="page-title">Parliamo della tua impresa</h1><p>Descrivi il progetto, il fabbisogno o la criticità. Il primo confronto serve a individuare il percorso più utile.</p></div></section><section class="content"><div class="wrap grid2"><div class="card"><h3>Contatto diretto</h3><p><b>Telefono</b><br>{PHONE}</p><p><b>Email</b><br>{CONTACT_EMAIL}</p><p><a class="btn" href="https://wa.me/{PHONE.replace('+','')}">WhatsApp</a></p></div><div class="formbox"><form method="post"><input type="hidden" name="csrf" value="{token}"><div class="formgrid"><label>Nome e cognome<input name="name" required></label><label>Azienda<input name="company"></label><label>Email<input type="email" name="email" required></label><label>Telefono<input name="phone"></label><label class="full">Servizio<select name="service"><option>Advisory d'impresa</option><option>Accesso al credito</option><option>Merito creditizio</option><option>Business plan</option><option>Controllo di gestione</option></select></label><label class="full">Messaggio<textarea name="message" rows="5" required></textarea></label><label class="full"><span><input style="width:auto" type="checkbox" name="privacy" value="1" required> Ho letto l'informativa privacy.</span></label></div><button class="btn" type="submit">Invia richiesta</button></form></div></div></section>'''
    return layout(request, "Contatti | FinancePlus.tech", form)

@app.post("/contatti")
def contact_post(request: Request, name: str=Form(...), company: str=Form(""), email: str=Form(...), phone: str=Form(""), service: str=Form(""), message: str=Form(...), privacy: Optional[str]=Form(None), csrf: str=Form(...)):
    check_csrf(request, csrf)
    if not privacy:
        raise HTTPException(status_code=400, detail="Consenso privacy necessario")
    with SessionLocal() as db:
        lead=Lead(name=name.strip(), company=company.strip(), email=email.strip().lower(), phone=phone.strip(), service=service.strip(), message=message.strip())
        db.add(lead); db.commit(); db.refresh(lead); notify_contact(lead)
    return layout(request, "Richiesta inviata | FinancePlus.tech", '<section class="content"><div class="wrap"><div class="notice ok"><b>Richiesta registrata.</b> Ti ricontatteremo utilizzando i recapiti indicati.</div><a class="btn" href="/">Torna alla Home</a></div></section>')

@app.get("/privacy")
def privacy(request: Request):
    return layout(request, "Privacy | FinancePlus.tech", '<section class="pagehero"><div class="wrap"><h1 class="page-title">Privacy</h1><p>Informativa in fase di completamento per la configurazione produttiva. Il titolare del trattamento è Financeplus S.r.l.; per richieste privacy utilizzare d.dangelo@financeplus.tech.</p></div></section>')

@app.get("/cookie")
def cookie(request: Request):
    return layout(request, "Cookie | FinancePlus.tech", '<section class="pagehero"><div class="wrap"><h1 class="page-title">Cookie</h1><p>Il portale utilizza cookie tecnici di sessione necessari al funzionamento dell’Area Clienti. Non sono attivati cookie pubblicitari nella versione corrente.</p></div></section>')

@app.get("/login")
def login_get(request: Request):
    token=csrf_token(request)
    body=f'''<section class="content portal"><div class="wrap" style="max-width:520px"><div class="formbox"><span class="eyebrow">AREA RISERVATA</span><h1 class="page-title">Accedi</h1><form method="post"><input type="hidden" name="csrf" value="{token}"><p><label>Email<input type="email" name="email" required></label></p><p><label>Password<input type="password" name="password" required></label></p><button class="btn" type="submit">Accedi</button></form><p class="muted">Nuovo cliente? <a href="/registrazione"><b>Richiedi un account</b></a></p></div></div></section>'''
    return layout(request, "Area Clienti | FinancePlus.tech", body)

@app.post("/login")
def login_post(request: Request, email: str=Form(...), password: str=Form(...), csrf: str=Form(...)):
    check_csrf(request, csrf)
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==email.strip().lower()))
        if not user or not password_verify(password, user.password_hash):
            return layout(request, "Accesso non riuscito", '<section class="content"><div class="wrap"><div class="notice err">Credenziali non valide.</div><a class="btn" href="/login">Riprova</a></div></section>')
        if not user.approved:
            return layout(request, "Account in attesa", '<section class="content"><div class="wrap"><div class="notice err">Account in attesa di approvazione FinancePlus.</div></div></section>')
        request.session["user_id"]=user.id
    return RedirectResponse("/admin" if user.role=="admin" else "/area-clienti", status_code=303)

@app.get("/registrazione")
def register_get(request: Request):
    token=csrf_token(request)
    body=f'''<section class="content portal"><div class="wrap" style="max-width:760px"><div class="formbox"><span class="eyebrow">ONBOARDING</span><h1 class="page-title">Richiedi account cliente</h1><form method="post"><input type="hidden" name="csrf" value="{token}"><div class="formgrid"><label>Azienda<input name="company_name" required></label><label>Partita IVA / CF<input name="vat"></label><label>Referente<input name="contact_name" required></label><label>Telefono<input name="phone"></label><label class="full">Email<input type="email" name="email" required></label><label class="full">Password<input type="password" name="password" minlength="10" required></label><label class="full"><span><input style="width:auto" type="checkbox" name="privacy" value="1" required> Accetto l'informativa privacy.</span></label></div><button class="btn" type="submit">Invia registrazione</button></form></div></div></section>'''
    return layout(request, "Registrazione | FinancePlus.tech", body)

@app.post("/registrazione")
def register_post(request: Request, company_name: str=Form(...), vat: str=Form(""), contact_name: str=Form(...), phone: str=Form(""), email: str=Form(...), password: str=Form(...), privacy: Optional[str]=Form(None), csrf: str=Form(...)):
    check_csrf(request, csrf)
    if not privacy or len(password)<10:
        raise HTTPException(status_code=400, detail="Dati di registrazione non validi")
    normalized=email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email==normalized)):
            return layout(request, "Registrazione", '<section class="content"><div class="wrap"><div class="notice err">Esiste già un account con questa email.</div></div></section>')
        db.add(User(email=normalized,password_hash=password_hash(password),role="client",approved=False,company_name=company_name.strip(),vat=vat.strip(),contact_name=contact_name.strip(),phone=phone.strip()))
        db.commit()
    return layout(request, "Registrazione ricevuta", '<section class="content"><div class="wrap"><div class="notice ok"><b>Registrazione ricevuta.</b> FinancePlus approverà l’account prima del primo accesso.</div></div></section>')

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

@app.get("/account/password")
def password_get(request: Request):
    require_user(request); token=csrf_token(request)
    return layout(request, "Cambia password | FinancePlus.tech", f'<section class="content portal"><div class="wrap" style="max-width:520px"><div class="formbox"><h1 class="page-title">Cambia password</h1><form method="post"><input type="hidden" name="csrf" value="{token}"><p><label>Password attuale<input type="password" name="current" required></label></p><p><label>Nuova password<input type="password" name="new" minlength="12" required></label></p><button class="btn">Aggiorna password</button></form></div></div></section>')

@app.post("/account/password")
def password_post(request: Request, current: str=Form(...), new: str=Form(...), csrf: str=Form(...)):
    check_csrf(request,csrf); u=require_user(request)
    if len(new)<12: raise HTTPException(status_code=400,detail="Password troppo corta")
    with SessionLocal() as db:
        user=db.get(User,u.id)
        if not password_verify(current,user.password_hash): raise HTTPException(status_code=400,detail="Password attuale non valida")
        user.password_hash=password_hash(new); db.commit()
    return layout(request,"Password aggiornata",'<section class="content"><div class="wrap"><div class="notice ok">Password aggiornata correttamente.</div></div></section>')

def side(role: str) -> str:
    if role=="admin":
        links=[("/admin","Dashboard"),("/admin#clienti","Clienti"),("/admin#pratiche","Pratiche"),("/admin#documenti","Documenti"),("/account/password","Password")]
    else:
        links=[("/area-clienti","Dashboard"),("/area-clienti/documenti","Documenti"),("/area-clienti/messaggi","Messaggi"),("/account/password","Password")]
    return '<aside class="side">'+''.join(f'<a href="{u}">{t}</a>' for u,t in links)+'</aside>'

@app.get("/area-clienti")
def client_dashboard(request: Request):
    u=require_user(request)
    if u.role=="admin": return RedirectResponse("/admin",status_code=303)
    with SessionLocal() as db:
        practices=db.scalars(select(Practice).where(Practice.user_id==u.id).order_by(Practice.updated_at.desc())).all()
        docs=db.scalars(select(Document).where(Document.user_id==u.id,Document.is_report.is_(False)).order_by(Document.uploaded_at.desc())).all()
        reports=db.scalars(select(Document).where(Document.user_id==u.id,Document.is_report.is_(True)).order_by(Document.uploaded_at.desc())).all()
        msgs=db.scalars(select(Message).where((Message.sender_id==u.id)|(Message.recipient_id==u.id)).order_by(Message.created_at.desc())).all()
    rows=''.join(f'<tr><td>{esc(p.title)}</td><td>{esc(p.product)}</td><td>{money(p.amount)}</td><td>{esc(p.institution)}</td><td><span class="badge">{esc(p.status)}</span></td></tr>' for p in practices) or '<tr><td colspan="5">Nessuna pratica presente.</td></tr>'
    body=f'''<section class="content portal"><div class="wrap portalgrid">{side(u.role)}<div><span class="eyebrow">AREA CLIENTE</span><h1 class="page-title">Buongiorno, {esc(u.contact_name or u.company_name)}</h1><div class="kpis"><div class="kpi"><span>Pratiche</span><strong>{len(practices)}</strong></div><div class="kpi"><span>Documenti</span><strong>{len(docs)}</strong></div><div class="kpi"><span>Report</span><strong>{len(reports)}</strong></div><div class="kpi"><span>Messaggi</span><strong>{len(msgs)}</strong></div></div><div class="tablebox"><h3>Le mie pratiche</h3><table><thead><tr><th>Pratica</th><th>Prodotto</th><th>Importo</th><th>Istituto</th><th>Stato</th></tr></thead><tbody>{rows}</tbody></table></div><div class="actions"><a class="btn" href="/area-clienti/documenti">Carica documenti</a><a class="btn alt" href="/area-clienti/messaggi">Scrivi a FinancePlus</a></div></div></div></section>'''
    return layout(request,"Dashboard cliente | FinancePlus.tech",body)

@app.get("/area-clienti/documenti")
def docs_get(request: Request):
    u=require_user(request)
    if u.role=="admin": return RedirectResponse("/admin",status_code=303)
    token=csrf_token(request)
    with SessionLocal() as db:
        practices=db.scalars(select(Practice).where(Practice.user_id==u.id).order_by(Practice.created_at.desc())).all()
        docs=db.scalars(select(Document).where(Document.user_id==u.id).order_by(Document.uploaded_at.desc())).all()
    options=''.join(f'<option value="{p.id}">{esc(p.title)}</option>' for p in practices)
    cats=''.join(f'<option>{esc(c)}</option>' for c in DOC_CATEGORIES)
    rows=''.join(f'<tr><td>{esc(d.filename)}</td><td>{esc("Report FinancePlus" if d.is_report else d.category)}</td><td>{esc(d.status)}</td><td>{d.uploaded_at.strftime("%d/%m/%Y")}</td><td><a href="/download/{d.id}">Scarica</a></td></tr>' for d in docs) or '<tr><td colspan="5">Nessun documento.</td></tr>'
    body=f'''<section class="content portal"><div class="wrap portalgrid">{side(u.role)}<div><h1 class="page-title">Documenti</h1><div class="formbox"><form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{token}"><div class="formgrid"><label>Categoria<select name="category">{cats}</select></label><label>Pratica<select name="practice_id"><option value="">Archivio generale</option>{options}</select></label><label class="full">File (max {MAX_UPLOAD_MB} MB)<input type="file" name="file" required></label></div><button class="btn">Carica documento</button></form></div><div class="tablebox" style="margin-top:18px"><h3>Archivio e report</h3><table><thead><tr><th>Documento</th><th>Categoria</th><th>Stato</th><th>Data</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div></div></section>'''
    return layout(request,"Documenti | FinancePlus.tech",body)

@app.post("/area-clienti/documenti")
async def docs_post(request: Request, category: str=Form(...), practice_id: str=Form(""), csrf: str=Form(...), file: UploadFile=File(...)):
    check_csrf(request,csrf); u=require_user(request)
    if u.role=="admin": raise HTTPException(status_code=403)
    filename=Path(file.filename or "file").name
    if Path(filename).suffix.lower() not in ALLOWED_EXT: raise HTTPException(status_code=400,detail="Formato file non ammesso")
    data=await file.read(MAX_UPLOAD_MB*1024*1024+1)
    if len(data)>MAX_UPLOAD_MB*1024*1024: raise HTTPException(status_code=413,detail="File troppo grande")
    pid=int(practice_id) if practice_id.strip() else None
    with SessionLocal() as db:
        if pid:
            p=db.get(Practice,pid)
            if not p or p.user_id!=u.id: raise HTTPException(status_code=403)
        db.add(Document(user_id=u.id,practice_id=pid,filename=filename,category=category,status="Caricato",size=len(data),file_data=data,is_report=False)); db.commit()
    return RedirectResponse("/area-clienti/documenti",status_code=303)

@app.get("/area-clienti/messaggi")
def messages_get(request: Request):
    u=require_user(request); token=csrf_token(request)
    if u.role=="admin": return RedirectResponse("/admin",status_code=303)
    with SessionLocal() as db:
        msgs=db.scalars(select(Message).where((Message.sender_id==u.id)|(Message.recipient_id==u.id)).order_by(Message.created_at.desc())).all()
    cards=''.join(f'<div class="card"><span class="eyebrow">{m.created_at.strftime("%d/%m/%Y %H:%M")}</span><h3>{esc(m.subject)}</h3><p class="muted">{esc(m.body)}</p></div>' for m in msgs) or '<div class="card">Nessun messaggio.</div>'
    body=f'''<section class="content portal"><div class="wrap portalgrid">{side(u.role)}<div><h1 class="page-title">Messaggi</h1><div class="formbox"><form method="post"><input type="hidden" name="csrf" value="{token}"><p><label>Oggetto<input name="subject" required></label></p><p><label>Messaggio<textarea name="body" rows="4" required></textarea></label></p><button class="btn">Invia</button></form></div><div class="grid2" style="margin-top:18px">{cards}</div></div></div></section>'''
    return layout(request,"Messaggi | FinancePlus.tech",body)

@app.post("/area-clienti/messaggi")
def messages_post(request: Request, subject: str=Form(...), body: str=Form(...), csrf: str=Form(...)):
    check_csrf(request,csrf); u=require_user(request)
    with SessionLocal() as db:
        admin=db.scalar(select(User).where(User.role=="admin"))
        db.add(Message(sender_id=u.id,recipient_id=admin.id,subject=subject.strip(),body=body.strip())); db.commit()
    return RedirectResponse("/area-clienti/messaggi",status_code=303)

@app.get("/download/{doc_id}")
def download(request: Request, doc_id: int):
    u=require_user(request)
    with SessionLocal() as db:
        d=db.get(Document,doc_id)
        if not d or (u.role!="admin" and d.user_id!=u.id): raise HTTPException(status_code=404)
        return Response(content=d.file_data,media_type="application/pdf" if d.filename.lower().endswith(".pdf") else "application/octet-stream",headers={"Content-Disposition":f"attachment; filename*=UTF-8''{quote(d.filename)}"})

@app.get("/admin")
def admin(request: Request):
    u=require_admin(request); token=csrf_token(request)
    with SessionLocal() as db:
        clients=db.scalars(select(User).where(User.role=="client").order_by(User.created_at.desc())).all()
        practices=db.scalars(select(Practice).order_by(Practice.updated_at.desc())).all()
        docs=db.scalars(select(Document).order_by(Document.uploaded_at.desc())).all()
        leads=db.scalars(select(Lead).order_by(Lead.created_at.desc())).all()
    client_rows=''.join(f'<tr><td>{esc(c.company_name)}</td><td>{esc(c.email)}</td><td>{"Attivo" if c.approved else "Da approvare"}</td><td><form method="post" action="/admin/clienti/{c.id}/toggle"><input type="hidden" name="csrf" value="{token}"><button class="btn">{"Disattiva" if c.approved else "Approva"}</button></form></td></tr>' for c in clients) or '<tr><td colspan="4">Nessun cliente.</td></tr>'
    client_opts=''.join(f'<option value="{c.id}">{esc(c.company_name)}</option>' for c in clients if c.approved)
    state_opts=''.join(f'<option>{esc(s)}</option>' for s in STATES)
    practice_rows=''.join(f'<tr><td>{esc(p.title)}</td><td>{money(p.amount)}</td><td>{esc(p.institution)}</td><td><form method="post" action="/admin/pratiche/{p.id}/stato"><input type="hidden" name="csrf" value="{token}"><select name="status">'+''.join(f'<option {"selected" if s==p.status else ""}>{esc(s)}</option>' for s in STATES)+f'</select><button class="btn">Salva</button></form></td></tr>' for p in practices) or '<tr><td colspan="4">Nessuna pratica.</td></tr>'
    doc_rows=''.join(f'<tr><td>{esc(d.filename)}</td><td>{esc(d.category)}</td><td>{"Report" if d.is_report else "Documento"}</td><td><a href="/download/{d.id}">Scarica</a></td></tr>' for d in docs[:50]) or '<tr><td colspan="4">Nessun documento.</td></tr>'
    lead_rows=''.join(f'<tr><td>{esc(l.name)}</td><td>{esc(l.company)}</td><td>{esc(l.email)}</td><td>{esc(l.service)}</td></tr>' for l in leads[:30]) or '<tr><td colspan="4">Nessun lead.</td></tr>'
    body=f'''<section class="content portal"><div class="wrap portalgrid">{side(u.role)}<div><span class="eyebrow">CONTROLLO CENTRALE</span><h1 class="page-title">Dashboard amministrativa</h1><div class="kpis"><div class="kpi"><span>Clienti</span><strong>{len(clients)}</strong></div><div class="kpi"><span>Da approvare</span><strong>{sum(1 for c in clients if not c.approved)}</strong></div><div class="kpi"><span>Pratiche</span><strong>{len(practices)}</strong></div><div class="kpi"><span>Documenti</span><strong>{len(docs)}</strong></div></div><div id="clienti" class="tablebox"><h3>Clienti e registrazioni</h3><table><thead><tr><th>Azienda</th><th>Email</th><th>Stato</th><th></th></tr></thead><tbody>{client_rows}</tbody></table></div><div id="pratiche" class="formbox" style="margin-top:18px"><h3>Nuova pratica</h3><form method="post" action="/admin/pratiche"><input type="hidden" name="csrf" value="{token}"><div class="formgrid"><label>Cliente<select name="user_id" required>{client_opts}</select></label><label>Titolo<input name="title" required></label><label>Prodotto<input name="product"></label><label>Importo<input type="number" step="0.01" name="amount"></label><label>Istituto<input name="institution"></label><label>Stato<select name="status">{state_opts}</select></label></div><button class="btn">Crea pratica</button></form></div><div class="tablebox" style="margin-top:18px"><h3>Pratiche</h3><table><thead><tr><th>Pratica</th><th>Importo</th><th>Istituto</th><th>Stato</th></tr></thead><tbody>{practice_rows}</tbody></table></div><div id="documenti" class="formbox" style="margin-top:18px"><h3>Pubblica report PDF</h3><form method="post" action="/admin/report" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{token}"><div class="formgrid"><label>Cliente<select name="user_id" required>{client_opts}</select></label><label>Titolo<input name="title" required></label><label class="full">PDF<input type="file" name="file" accept="application/pdf" required></label></div><button class="btn">Pubblica report</button></form></div><div class="tablebox" style="margin-top:18px"><h3>Documenti e report</h3><table><thead><tr><th>File</th><th>Categoria</th><th>Tipo</th><th></th></tr></thead><tbody>{doc_rows}</tbody></table></div><div class="tablebox" style="margin-top:18px"><h3>Lead sito</h3><table><thead><tr><th>Nome</th><th>Azienda</th><th>Email</th><th>Servizio</th></tr></thead><tbody>{lead_rows}</tbody></table></div></div></div></section>'''
    return layout(request,"Pannello amministratore | FinancePlus.tech",body)

@app.post("/admin/clienti/{user_id}/toggle")
def client_toggle(request: Request, user_id: int, csrf: str=Form(...)):
    check_csrf(request,csrf); require_admin(request)
    with SessionLocal() as db:
        c=db.get(User,user_id)
        if not c or c.role!="client": raise HTTPException(status_code=404)
        c.approved=not c.approved; db.commit()
    return RedirectResponse("/admin#clienti",status_code=303)

@app.post("/admin/pratiche")
def practice_create(request: Request, user_id: int=Form(...), title: str=Form(...), product: str=Form(""), amount: float=Form(0), institution: str=Form(""), status: str=Form("Da avviare"), csrf: str=Form(...)):
    check_csrf(request,csrf); require_admin(request)
    with SessionLocal() as db:
        c=db.get(User,user_id)
        if not c or c.role!="client": raise HTTPException(status_code=404)
        db.add(Practice(user_id=user_id,title=title.strip(),product=product.strip(),amount=amount,institution=institution.strip(),status=status)); db.commit()
    return RedirectResponse("/admin#pratiche",status_code=303)

@app.post("/admin/pratiche/{practice_id}/stato")
def practice_state(request: Request, practice_id: int, status: str=Form(...), csrf: str=Form(...)):
    check_csrf(request,csrf); require_admin(request)
    with SessionLocal() as db:
        p=db.get(Practice,practice_id)
        if not p: raise HTTPException(status_code=404)
        p.status=status; p.updated_at=datetime.utcnow(); db.commit()
    return RedirectResponse("/admin#pratiche",status_code=303)

@app.post("/admin/report")
async def report_upload(request: Request, user_id: int=Form(...), title: str=Form(...), csrf: str=Form(...), file: UploadFile=File(...)):
    check_csrf(request,csrf); require_admin(request)
    filename=Path(file.filename or "report.pdf").name
    if not filename.lower().endswith(".pdf"): raise HTTPException(status_code=400,detail="Il report deve essere PDF")
    data=await file.read(MAX_UPLOAD_MB*1024*1024+1)
    if len(data)>MAX_UPLOAD_MB*1024*1024: raise HTTPException(status_code=413,detail="File troppo grande")
    with SessionLocal() as db:
        c=db.get(User,user_id)
        if not c or c.role!="client": raise HTTPException(status_code=404)
        db.add(Document(user_id=user_id,filename=filename,category=title.strip(),status="Disponibile",is_report=True,size=len(data),file_data=data)); db.commit()
    return RedirectResponse("/admin#documenti",status_code=303)

@app.get("/robots.txt")
def robots():
    return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /area-clienti\nSitemap: {BASE_URL}/sitemap.xml\n")

@app.get("/sitemap.xml")
def sitemap():
    paths=["/","/servizi","/metodo","/chi-siamo","/insights","/contatti","/login"]
    xml=''.join(f"<url><loc>{BASE_URL}{p}</loc></url>" for p in paths)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{xml}</urlset>',media_type="application/xml")

@app.exception_handler(401)
async def unauthorized(request: Request, exc):
    return RedirectResponse("/login",status_code=303)
