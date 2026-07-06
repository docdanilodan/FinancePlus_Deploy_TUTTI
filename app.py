# -*- coding: utf-8 -*-
"""
FinancePlus Master Suite PRO
Versione deploy Streamlit/GitHub - file principale app.py

Sintesi funzionale delle migliori parti dei progetti FinancePlus APP 01_07 - 12_07:
- Dashboard professionale blu/rame
- Cliente 360
- OCR/IDP documentale con hash anti-duplicati
- Cerca Azienda su mail, allegati, oggetto e testo documento
- Archivio cliente/mese/tipologia con coda Da Verificare
- Note, call, calendario operativo
- Centrale Rischi, PHANTOM score, MCC/DSCR e Business Plan sintetico
- Report PDF e backup ZIP

Avvio:
    streamlit run app.py

Note operative:
- Le credenziali mail restano in sessione Streamlit e non vengono salvate nel database.
- L'importazione cartella locale funziona su PC/server locale. Su Streamlit Cloud usare upload multiplo.
- OCR avanzato su scansioni richiede Tesseract installato a livello sistema; il programma usa fallback sicuri.
"""

from __future__ import annotations

import base64
import csv
import email
import hashlib
import imaplib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    from docx import Document as DocxDocument
except Exception:  # pragma: no cover
    DocxDocument = None

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image as RLImage,
        PageBreak,
        KeepTogether,
    )
except Exception:  # pragma: no cover
    colors = None


# -----------------------------------------------------------------------------
# Configurazione generale
# -----------------------------------------------------------------------------

APP_VERSION = "Master Suite PRO 12_07+"
APP_TITLE = "FinancePlus Master Suite PRO"
PRIMARY = "#0B2239"       # blu notte
PRIMARY_2 = "#123A5A"
COPPER = "#BE7A2D"        # rame
COPPER_DARK = "#9A5A19"
GREEN = "#138A62"
RED = "#B83A2E"
AMBER = "#E1A100"
LIGHT_BG = "#F4F7FA"
TEXT = "#132238"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "financeplus_data"
ARCHIVE_DIR = DATA_DIR / "clienti"
VERIFY_DIR = DATA_DIR / "_DA_VERIFICARE_TEMPORANEA"
REPORT_DIR = DATA_DIR / "report"
BACKUP_DIR = DATA_DIR / "backup"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "financeplus_master.db"

LOGO_CANDIDATES = [
    BASE_DIR / "FinancePlusTech_logo_completo.png",
    BASE_DIR / "FinancePlusTech_logo_completo.ico",
    BASE_DIR / "logo.png",
    BASE_DIR / "assets" / "FinancePlusTech_logo_completo.png",
    BASE_DIR / "assets" / "FinancePlusTech_logo_completo.ico",
]

SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".txt", ".csv",
    ".xlsx", ".xls", ".docx", ".eml", ".zip", ".json"
}

DOC_CATEGORIES = [
    "Visura", "Bilancio", "Centrale Rischi", "Estratto Conto", "Contratto",
    "Fattura", "Documento identita", "Business Plan", "Report", "Mail", "Altro"
]

INLINE_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"}


# -----------------------------------------------------------------------------
# Setup Streamlit e stile
# -----------------------------------------------------------------------------

_PAGE_ICON = "📊"
if Image is not None:
    for _logo_candidate in LOGO_CANDIDATES:
        if _logo_candidate.exists():
            try:
                _PAGE_ICON = Image.open(_logo_candidate)
                break
            except Exception:
                pass

st.set_page_config(
    page_title=APP_TITLE,
    page_icon=_PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --fp-primary: {PRIMARY};
            --fp-primary-2: {PRIMARY_2};
            --fp-copper: {COPPER};
            --fp-bg: {LIGHT_BG};
            --fp-text: {TEXT};
        }}
        .stApp {{
            background: linear-gradient(180deg, #F7FAFC 0%, #EFF4F8 100%);
            color: var(--fp-text);
        }}
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, {PRIMARY} 0%, #071827 100%);
            border-right: 5px solid {COPPER};
        }}
        section[data-testid="stSidebar"] * {{ color: #EEF3F7; }}
        div[data-testid="stSidebarNav"] {{ display: none; }}
        .fp-hero {{
            background: linear-gradient(135deg, {PRIMARY} 0%, {PRIMARY_2} 70%, #1A5075 100%);
            color: white;
            padding: 28px 30px;
            border-radius: 22px;
            box-shadow: 0 14px 36px rgba(11,34,57,0.18);
            border-bottom: 5px solid {COPPER};
            margin-bottom: 18px;
        }}
        .fp-hero h1 {{
            margin: 0 0 8px 0;
            font-size: 34px;
            letter-spacing: -0.3px;
        }}
        .fp-hero p {{
            margin: 0;
            opacity: 0.93;
            font-size: 16px;
        }}
        .fp-card {{
            background: white;
            border: 1px solid rgba(12,34,57,0.08);
            border-radius: 18px;
            padding: 18px 20px;
            box-shadow: 0 9px 24px rgba(11,34,57,0.07);
            margin-bottom: 14px;
        }}
        .fp-kpi {{
            background: white;
            border-radius: 18px;
            padding: 18px 18px 14px 18px;
            border: 1px solid rgba(12,34,57,0.09);
            box-shadow: 0 9px 24px rgba(11,34,57,0.07);
            position: relative;
            overflow: hidden;
        }}
        .fp-kpi:before {{
            content: "";
            position: absolute;
            right: 16px;
            top: 16px;
            height: 14px;
            width: 14px;
            border-radius: 50%;
            background: {COPPER};
        }}
        .fp-kpi .label {{ font-size: 12px; text-transform: uppercase; color: #64748B; font-weight: 700; }}
        .fp-kpi .value {{ font-size: 31px; color: {PRIMARY}; font-weight: 800; margin-top: 4px; }}
        .fp-kpi .help {{ font-size: 12px; color: #64748B; margin-top: 4px; }}
        .fp-section-title {{
            font-size: 24px;
            font-weight: 800;
            color: {PRIMARY};
            padding-bottom: 8px;
            border-bottom: 2px solid rgba(190,122,45,0.36);
            margin: 8px 0 16px 0;
        }}
        .fp-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            background: rgba(190,122,45,0.14);
            color: {COPPER_DARK};
            font-size: 12px;
            font-weight: 800;
            border: 1px solid rgba(190,122,45,0.25);
        }}
        .fp-pill-ok {{ background: rgba(19,138,98,0.12); color: {GREEN}; padding: 4px 10px; border-radius: 999px; font-weight: 800; }}
        .fp-pill-warn {{ background: rgba(225,161,0,0.12); color: #9A6B00; padding: 4px 10px; border-radius: 999px; font-weight: 800; }}
        .fp-pill-red {{ background: rgba(184,58,46,0.12); color: {RED}; padding: 4px 10px; border-radius: 999px; font-weight: 800; }}
        div.stButton > button, div.stDownloadButton > button {{
            border-radius: 12px;
            border: 1px solid rgba(11,34,57,0.15);
            background: linear-gradient(180deg, {COPPER} 0%, {COPPER_DARK} 100%);
            color: white;
            font-weight: 800;
        }}
        div.stButton > button:hover, div.stDownloadButton > button:hover {{
            border: 1px solid {PRIMARY};
            color: white;
            filter: brightness(0.97);
        }}
        .stTabs [data-baseweb="tab-list"] {{ gap: 10px; }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 12px;
            padding: 10px 16px;
            background: white;
            border: 1px solid rgba(11,34,57,0.08);
        }}
        .stTabs [aria-selected="true"] {{
            background: {PRIMARY};
            color: white;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Utility base
# -----------------------------------------------------------------------------


def ensure_dirs() -> None:
    for path in [DATA_DIR, ARCHIVE_DIR, VERIFY_DIR, REPORT_DIR, BACKUP_DIR, LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def find_logo_path() -> Optional[Path]:
    for p in LOGO_CANDIDATES:
        if p.exists():
            return p
    return None


def image_to_base64(path: Path) -> str:
    try:
        suffix = path.suffix.lower()
        if suffix == ".ico" and Image is not None:
            im = Image.open(path).convert("RGBA")
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii")
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return ""


def safe_filename(value: str, max_len: int = 90) -> str:
    value = value.strip().replace("\n", " ")
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_ .")
    return (value[:max_len] or "file").upper()


def today_str() -> str:
    return datetime.now().strftime("%d-%m-%Y")


def month_folder(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%Y-%m")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_text_file_bytes(data: bytes, suffix: str) -> str:
    suffix = suffix.lower()
    try:
        if suffix in {".txt", ".csv", ".json"}:
            return data.decode("utf-8", errors="ignore")[:30000]
        if suffix == ".pdf" and fitz is not None:
            doc = fitz.open(stream=data, filetype="pdf")
            pages = []
            for page in doc[:10]:
                pages.append(page.get_text("text"))
            return "\n".join(pages)[:50000]
        if suffix == ".docx" and DocxDocument is not None:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                doc = DocxDocument(tmp_path)
                return "\n".join(p.text for p in doc.paragraphs)[:50000]
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        if suffix in {".xlsx", ".xls"}:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                frames = pd.read_excel(tmp_path, sheet_name=None, nrows=80)
                parts = []
                for name, frame in frames.items():
                    parts.append(f"Foglio: {name}\n" + frame.astype(str).to_csv(index=False))
                return "\n".join(parts)[:50000]
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        if suffix == ".eml":
            msg = email.message_from_bytes(data)
            return extract_email_text(msg)[:50000]
    except Exception as exc:
        return f"[lettura non disponibile: {exc}]"
    return ""


def normalize_for_match(text: str) -> str:
    text = text.lower()
    replacements = {
        "s.r.l.": "srl", "s.r.l": "srl", "s.p.a.": "spa", "s.p.a": "spa",
        "societa": "societa", "à": "a", "è": "e", "é": "e", "ì": "i", "ò": "o", "ù": "u",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[^a-z0-9@._\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_email_text(msg: email.message.Message) -> str:
    parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", "")).lower()
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                parts.append(payload.decode(charset, errors="ignore"))
            elif content_type == "text/html" and "attachment" not in disposition and not parts:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                html = payload.decode(charset, errors="ignore")
                parts.append(re.sub(r"<[^>]+>", " ", html))
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        parts.append(payload.decode(charset, errors="ignore"))
    return re.sub(r"\s+", " ", "\n".join(parts)).strip()


def decode_mime_header(value: Any) -> str:
    if not value:
        return ""
    out = []
    for text, charset in decode_header(str(value)):
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="ignore"))
        else:
            out.append(text)
    return "".join(out)


# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------


def get_conn() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_dirs()
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                piva TEXT,
                cf TEXT,
                pec TEXT,
                address TEXT,
                admin TEXT,
                ateco TEXT,
                bank TEXT,
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_name ON clients(name);

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                original_name TEXT NOT NULL,
                saved_name TEXT NOT NULL,
                category TEXT,
                ext TEXT,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER,
                confidence REAL,
                status TEXT,
                source TEXT,
                saved_path TEXT,
                preview TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            );
            CREATE INDEX IF NOT EXISTS idx_documents_client ON documents(client_id);
            CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(sha256);

            CREATE TABLE IF NOT EXISTS mail_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                subject TEXT,
                sender TEXT,
                recipients TEXT,
                received_at TEXT,
                saved_eml_path TEXT,
                message_uid TEXT,
                preview TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            );

            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                kind TEXT,
                title TEXT,
                status TEXT,
                amount REAL,
                bank TEXT,
                due_date TEXT,
                body TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            );

            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                phantom_score REAL,
                rating TEXT,
                dscr REAL,
                mcc_class TEXT,
                financing_capacity REAL,
                json_data TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            );

            CREATE TABLE IF NOT EXISTS app_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                area TEXT,
                message TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def log_event(level: str, area: str, message: str) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO app_logs(level, area, message, created_at) VALUES (?, ?, ?, ?)",
                (level.upper(), area, message[:1000], datetime.now().isoformat(timespec="seconds")),
            )
    except Exception:
        pass


def df_query(query: str, params: Tuple[Any, ...] = ()) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(query, conn, params=params)


def list_clients() -> pd.DataFrame:
    return df_query("SELECT * FROM clients ORDER BY name")


def get_client(client_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()


def get_client_options() -> Dict[str, int]:
    df = list_clients()
    if df.empty:
        return {}
    return {f"{row['name']}" + (f" - P.IVA {row['piva']}" if row.get('piva') else ""): int(row['id']) for _, row in df.iterrows()}


def add_or_update_client(data: Dict[str, Any]) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    clean_name = data.get("name", "").strip().upper()
    if not clean_name:
        raise ValueError("Nome cliente obbligatorio")
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM clients WHERE name=?", (clean_name,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE clients SET piva=?, cf=?, pec=?, address=?, admin=?, ateco=?, bank=?, notes=?
                WHERE id=?
                """,
                (
                    data.get("piva"), data.get("cf"), data.get("pec"), data.get("address"),
                    data.get("admin"), data.get("ateco"), data.get("bank"), data.get("notes"),
                    existing["id"],
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO clients(name, piva, cf, pec, address, admin, ateco, bank, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_name, data.get("piva"), data.get("cf"), data.get("pec"), data.get("address"),
                data.get("admin"), data.get("ateco"), data.get("bank"), data.get("notes"), now,
            ),
        )
        log_event("INFO", "CLIENTI", f"Creato cliente {clean_name}")
        return int(cur.lastrowid)


# -----------------------------------------------------------------------------
# Motore IDP: classificazione, matching, archiviazione
# -----------------------------------------------------------------------------


CATEGORY_RULES: Dict[str, List[str]] = {
    "Visura": ["visura", "camera di commercio", "cciaa", "rea", "registro imprese", "ateco"],
    "Bilancio": ["bilancio", "stato patrimoniale", "conto economico", "nota integrativa", "xbrl"],
    "Centrale Rischi": ["centrale rischi", "crif", "banca d'italia", "accordato", "utilizzato", "sconfin"],
    "Estratto Conto": ["estratto conto", "movimenti", "saldo", "iban", "conto corrente"],
    "Contratto": ["contratto", "mandato", "accordo", "scrittura privata", "condizioni"],
    "Fattura": ["fattura", "invoice", "fatturazione", "imponibile", "iva"],
    "Documento identita": ["carta identita", "passaporto", "patente", "documento di identita"],
    "Business Plan": ["business plan", "forecast", "break even", "cash flow", "previsionale", "dscr"],
    "Report": ["report", "dossier", "analisi", "riepilogo", "valutazione"],
    "Mail": ["from:", "subject:", "to:", "mittente", "oggetto"],
}


def classify_document(filename: str, text: str) -> Tuple[str, float, str]:
    sample = normalize_for_match(filename + " " + text[:8000])
    scores: Dict[str, int] = {}
    for category, keywords in CATEGORY_RULES.items():
        score = 0
        for kw in keywords:
            score += sample.count(normalize_for_match(kw))
        if score:
            scores[category] = score
    if not scores:
        return "Altro", 0.35, "Nessuna regola forte trovata"
    category = max(scores, key=scores.get)
    raw = scores[category]
    confidence = min(0.98, 0.55 + raw * 0.12)
    return category, confidence, f"Regole trovate: {scores}"


def match_client(text: str, forced_client_id: Optional[int] = None) -> Tuple[Optional[int], float, str]:
    if forced_client_id:
        return forced_client_id, 1.0, "Cliente selezionato manualmente"
    clients = list_clients()
    if clients.empty:
        return None, 0.0, "Nessun cliente registrato"
    sample = normalize_for_match(text[:30000])
    best_id: Optional[int] = None
    best_score = 0.0
    best_reason = ""
    for _, row in clients.iterrows():
        score = 0.0
        reasons = []
        name = normalize_for_match(str(row.get("name", "")))
        piva = re.sub(r"\D", "", str(row.get("piva", "")))
        cf = normalize_for_match(str(row.get("cf", "")))
        pec = normalize_for_match(str(row.get("pec", "")))
        admin = normalize_for_match(str(row.get("admin", "")))
        aliases = [name]
        if name:
            aliases.extend([name.replace(" srl", ""), name.replace(" spa", "")])
        for alias in aliases:
            if alias and len(alias) >= 4 and alias in sample:
                score += 0.55
                reasons.append("ragione sociale/alias")
                break
        if piva and len(piva) >= 8 and piva in re.sub(r"\D", "", sample):
            score += 0.45
            reasons.append("P.IVA")
        if cf and len(cf) >= 8 and cf in sample:
            score += 0.35
            reasons.append("C.F.")
        if pec and len(pec) >= 6 and pec in sample:
            score += 0.25
            reasons.append("PEC")
        if admin and len(admin) >= 6 and admin in sample:
            score += 0.20
            reasons.append("amministratore")
        if score > best_score:
            best_score = min(1.0, score)
            best_id = int(row["id"])
            best_reason = ", ".join(reasons)
    if best_score >= 0.45:
        return best_id, best_score, best_reason or "match regole"
    return None, best_score, "Match sotto soglia"


def build_archive_path(client_id: Optional[int], category: str, original_name: str, status: str) -> Tuple[Path, str]:
    ext = Path(original_name).suffix.lower() or ".bin"
    category_safe = safe_filename(category, 40).title().replace("_", " ")
    if status == "DA VERIFICARE" or client_id is None:
        target_dir = VERIFY_DIR / month_folder() / category_safe
        client_prefix = "CLIENTE_DA_VERIFICARE"
    else:
        client = get_client(client_id)
        client_name = safe_filename(client["name"] if client else "CLIENTE")
        target_dir = ARCHIVE_DIR / client_name / month_folder() / category_safe
        client_prefix = client_name
    target_dir.mkdir(parents=True, exist_ok=True)
    base = f"{client_prefix}_{safe_filename(category, 36)}_{today_str()}{ext.lower()}"
    final = target_dir / base
    counter = 2
    while final.exists():
        final = target_dir / f"{Path(base).stem}_{counter}{ext.lower()}"
        counter += 1
    return final, final.name


def save_document_bytes(
    data: bytes,
    original_name: str,
    source: str = "upload",
    forced_client_id: Optional[int] = None,
) -> Dict[str, Any]:
    ensure_dirs()
    ext = Path(original_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {
            "ok": False,
            "original_name": original_name,
            "status": "SCARTATO",
            "message": f"Estensione non gestita: {ext}",
        }

    digest = sha256_bytes(data)
    with get_conn() as conn:
        duplicate = conn.execute("SELECT id, saved_path FROM documents WHERE sha256=?", (digest,)).fetchone()
    if duplicate:
        log_event("INFO", "DOCUMENTI", f"Duplicato bloccato: {original_name}")
        return {
            "ok": True,
            "duplicate": True,
            "original_name": original_name,
            "status": "DUPLICATO",
            "message": f"Duplicato gia presente: {duplicate['saved_path']}",
            "sha256": digest,
        }

    text = read_text_file_bytes(data, ext)
    category, cat_conf, cat_reason = classify_document(original_name, text)
    client_id, match_conf, match_reason = match_client(original_name + "\n" + text, forced_client_id)
    total_conf = round((cat_conf * 0.45 + match_conf * 0.55), 3)
    status = "ARCHIVIATO" if client_id and total_conf >= 0.56 else "DA VERIFICARE"
    final_path, saved_name = build_archive_path(client_id, category, original_name, status)
    final_path.write_bytes(data)

    preview = (text[:3500] or "[anteprima non disponibile]").strip()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO documents(client_id, original_name, saved_name, category, ext, sha256, size_bytes,
                                  confidence, status, source, saved_path, preview, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id, original_name, saved_name, category, ext, digest, len(data), total_conf,
                status, source, str(final_path), preview, datetime.now().isoformat(timespec="seconds"),
            ),
        )
    log_event("INFO", "DOCUMENTI", f"{status}: {original_name} -> {saved_name}")
    return {
        "ok": True,
        "duplicate": False,
        "original_name": original_name,
        "saved_name": saved_name,
        "category": category,
        "client_id": client_id,
        "confidence": total_conf,
        "status": status,
        "path": str(final_path),
        "classification_reason": cat_reason,
        "match_reason": match_reason,
        "sha256": digest,
    }


def scan_local_folder(folder: Path, forced_client_id: Optional[int] = None, limit: int = 800) -> List[Dict[str, Any]]:
    results = []
    count = 0
    for path in folder.rglob("*"):
        if count >= limit:
            break
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            results.append(save_document_bytes(path.read_bytes(), path.name, source="cartella locale", forced_client_id=forced_client_id))
            count += 1
        except Exception as exc:
            results.append({"ok": False, "original_name": str(path), "status": "ERRORE", "message": str(exc)})
    return results


# -----------------------------------------------------------------------------
# Mail IMAP
# -----------------------------------------------------------------------------


@dataclass
class MailSearchResult:
    uid: str
    subject: str
    sender: str
    date_received: str
    preview: str
    attachment_names: List[str]
    raw_bytes: bytes


def is_inline_image(part: email.message.Message, filename: str) -> bool:
    disp = str(part.get("Content-Disposition", "")).lower()
    cid = part.get("Content-ID")
    ext = Path(filename or "").suffix.lower()
    size = len(part.get_payload(decode=True) or b"")
    if "inline" in disp or cid:
        return True
    if ext in INLINE_IMAGE_EXT and size < 350_000:
        return True
    return False


def email_attachment_names(msg: email.message.Message) -> List[str]:
    names = []
    for part in msg.walk():
        filename = decode_mime_header(part.get_filename())
        if filename:
            names.append(filename)
    return names


def search_imap_messages(
    host: str,
    email_user: str,
    password: str,
    azienda: str,
    mailbox: str = "INBOX",
    max_messages: int = 50,
    days_back: int = 365,
) -> List[MailSearchResult]:
    azienda_norm = normalize_for_match(azienda)
    since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
    results: List[MailSearchResult] = []
    imap = imaplib.IMAP4_SSL(host)
    try:
        imap.login(email_user, password)
        imap.select(mailbox)
        status, data = imap.search(None, f'(SINCE "{since}")')
        if status != "OK":
            raise RuntimeError("Ricerca IMAP non riuscita")
        uids = data[0].split()[-max_messages * 4:]
        for uid in reversed(uids):
            if len(results) >= max_messages:
                break
            status, msg_data = imap.fetch(uid, "(RFC822)")
            if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            subject = decode_mime_header(msg.get("Subject"))
            sender = decode_mime_header(msg.get("From"))
            dt = decode_mime_header(msg.get("Date"))
            body = extract_email_text(msg)
            attachment_names = email_attachment_names(msg)
            haystack = normalize_for_match(" ".join([subject, sender, body, " ".join(attachment_names)]))
            if azienda_norm and azienda_norm in haystack:
                results.append(
                    MailSearchResult(
                        uid=uid.decode("ascii", errors="ignore"),
                        subject=subject,
                        sender=sender,
                        date_received=dt,
                        preview=body[:1200],
                        attachment_names=attachment_names,
                        raw_bytes=raw,
                    )
                )
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return results


def save_mail_result(result: MailSearchResult, client_id: Optional[int], save_attachments: bool = True) -> Dict[str, Any]:
    msg = email.message_from_bytes(result.raw_bytes)
    client = get_client(client_id) if client_id else None
    client_name = safe_filename(client["name"] if client else "CLIENTE_DA_VERIFICARE")
    target = ARCHIVE_DIR / client_name / month_folder() / "Mail"
    if not client_id:
        target = VERIFY_DIR / month_folder() / "Mail"
    target.mkdir(parents=True, exist_ok=True)
    subject_safe = safe_filename(result.subject or "mail", 70)
    eml_name = f"{client_name}_MAIL_{today_str()}_{subject_safe}.eml"
    eml_path = target / eml_name
    counter = 2
    while eml_path.exists():
        eml_path = target / f"{Path(eml_name).stem}_{counter}.eml"
        counter += 1
    eml_path.write_bytes(result.raw_bytes)

    saved_attachments = []
    if save_attachments:
        for part in msg.walk():
            filename = decode_mime_header(part.get_filename())
            if not filename:
                continue
            if is_inline_image(part, filename):
                continue
            payload = part.get_payload(decode=True) or b""
            if not payload:
                continue
            saved_attachments.append(save_document_bytes(payload, filename, source="mail", forced_client_id=client_id))

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO mail_items(client_id, subject, sender, recipients, received_at, saved_eml_path, message_uid, preview, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id, result.subject, result.sender, "", result.date_received, str(eml_path), result.uid,
                result.preview[:1800], datetime.now().isoformat(timespec="seconds"),
            ),
        )
    log_event("INFO", "MAIL", f"Mail salvata: {result.subject}")
    return {"eml_path": str(eml_path), "attachments": saved_attachments}


# -----------------------------------------------------------------------------
# Scoring, CR, MCC, Business Plan
# -----------------------------------------------------------------------------


def compute_phantom_score(metrics: Dict[str, float]) -> Tuple[float, str, str, float]:
    score = 100.0
    utilization = metrics.get("utilization", 0.0)
    past_due = metrics.get("past_due", 0.0)
    overdraft = metrics.get("overdraft", 0.0)
    dscr = metrics.get("dscr", 1.2)
    leverage = metrics.get("leverage", 2.5)
    ebitda_margin = metrics.get("ebitda_margin", 0.10)

    if utilization > 90:
        score -= 16
    elif utilization > 75:
        score -= 8
    if past_due > 0:
        score -= min(22, 8 + past_due / 5000)
    if overdraft > 0:
        score -= min(16, 6 + overdraft / 7000)
    if dscr < 1.0:
        score -= 22
    elif dscr < 1.2:
        score -= 10
    if leverage > 5:
        score -= 12
    elif leverage > 3.5:
        score -= 6
    if ebitda_margin < 0.04:
        score -= 10
    elif ebitda_margin > 0.16:
        score += 4

    score = max(0, min(100, round(score, 1)))
    if score >= 82:
        rating = "A - forte"
        mcc = "Classe 1/2 simulata"
    elif score >= 70:
        rating = "B - buona"
        mcc = "Classe 2/3 simulata"
    elif score >= 58:
        rating = "C - monitorare"
        mcc = "Classe 3/4 simulata"
    elif score >= 45:
        rating = "D - critica"
        mcc = "Classe 4/5 simulata"
    else:
        rating = "E - rischio elevato"
        mcc = "Classe 5 simulata"

    financing_capacity = max(0.0, metrics.get("ebitda", 0.0) * max(dscr, 0.1) * 2.8 - metrics.get("existing_debt", 0.0) * 0.15)
    return score, rating, mcc, round(financing_capacity, 2)


def save_score(client_id: int, metrics: Dict[str, float]) -> None:
    score, rating, mcc, capacity = compute_phantom_score(metrics)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO scores(client_id, phantom_score, rating, dscr, mcc_class, financing_capacity, json_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id, score, rating, metrics.get("dscr"), mcc, capacity,
                json.dumps(metrics, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"),
            ),
        )
    log_event("INFO", "SCORE", f"Score salvato cliente {client_id}: {score}")


# -----------------------------------------------------------------------------
# Report PDF
# -----------------------------------------------------------------------------


def rl_style_sheet() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "FPTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=22,
            leading=26, textColor=colors.HexColor(PRIMARY), spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "FPH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=14,
            leading=18, textColor=colors.HexColor(PRIMARY), spaceBefore=8, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "FPBody", parent=base["BodyText"], fontName="Helvetica", fontSize=9,
            leading=12, textColor=colors.HexColor(TEXT), spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "FPSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=7.5,
            leading=10, textColor=colors.HexColor("#425466"), spaceAfter=3,
        ),
        "center": ParagraphStyle(
            "FPCenter", parent=base["BodyText"], alignment=TA_CENTER, fontSize=9,
            textColor=colors.HexColor(TEXT), leading=11,
        ),
    }


def pdf_header_footer(canvas, doc) -> None:  # noqa: ANN001
    canvas.saveState()
    w, h = landscape(A4)
    canvas.setFillColor(colors.HexColor(PRIMARY))
    canvas.rect(0, h - 13 * mm, w, 13 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor(COPPER))
    canvas.rect(0, h - 14 * mm, w, 1.6 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(14 * mm, h - 8.7 * mm, "FinancePlus.Tech - Master Suite PRO")
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(w - 14 * mm, h - 8.7 * mm, f"Pag. {doc.page}")
    canvas.setFillColor(colors.HexColor("#7D8896"))
    canvas.setFont("Helvetica", 7)
    canvas.drawString(14 * mm, 9 * mm, "Documento operativo - sintesi, funzionalita e programma unico .py")
    canvas.restoreState()


def make_table(data: List[List[Any]], col_widths: Optional[List[float]] = None, font_size: float = 7.5) -> Table:
    table_data = []
    styles = rl_style_sheet()
    for row in data:
        table_data.append([Paragraph(str(cell).replace("\n", "<br/>") if cell is not None else "", styles["small"]) for cell in row])
    t = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PRIMARY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def create_client_report(client_id: int) -> Path:
    if colors is None:
        raise RuntimeError("reportlab non installato. Installare requirements.txt")
    client = get_client(client_id)
    if client is None:
        raise ValueError("Cliente non trovato")

    out = REPORT_DIR / f"Dossier_{safe_filename(client['name'])}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    doc = SimpleDocTemplate(
        str(out), pagesize=landscape(A4), rightMargin=14 * mm, leftMargin=14 * mm,
        topMargin=20 * mm, bottomMargin=14 * mm,
    )
    styles = rl_style_sheet()
    story: List[Any] = []
    logo = find_logo_path()
    if logo and logo.suffix.lower() != ".ico":
        story.append(RLImage(str(logo), width=22 * mm, height=22 * mm))
    story.append(Paragraph(f"Dossier Cliente 360 - {client['name']}", styles["title"]))
    story.append(Paragraph(f"Generato il {datetime.now().strftime('%d/%m/%Y %H:%M')} - {APP_VERSION}", styles["body"]))

    anag = [
        ["Campo", "Valore"],
        ["Ragione sociale", client["name"]],
        ["P.IVA", client["piva"] or ""],
        ["Codice fiscale", client["cf"] or ""],
        ["PEC", client["pec"] or ""],
        ["Amministratore", client["admin"] or ""],
        ["ATECO", client["ateco"] or ""],
        ["Banca", client["bank"] or ""],
    ]
    story.append(Paragraph("Anagrafica", styles["h2"]))
    story.append(make_table(anag, [50 * mm, 190 * mm], 8))
    story.append(Spacer(1, 6))

    docs_df = df_query(
        "SELECT original_name, category, confidence, status, saved_path, created_at FROM documents WHERE client_id=? ORDER BY created_at DESC LIMIT 40",
        (client_id,),
    )
    story.append(Paragraph("Documenti collegati", styles["h2"]))
    if docs_df.empty:
        story.append(Paragraph("Nessun documento collegato.", styles["body"]))
    else:
        rows = [["Documento", "Categoria", "Conf.", "Stato", "Data"]]
        for _, row in docs_df.iterrows():
            rows.append([row["original_name"], row["category"], row["confidence"], row["status"], row["created_at"]])
        story.append(make_table(rows, [75 * mm, 38 * mm, 18 * mm, 32 * mm, 38 * mm], 7.2))

    notes_df = df_query(
        "SELECT kind, title, status, amount, bank, due_date, created_at FROM notes WHERE client_id=? ORDER BY created_at DESC LIMIT 25",
        (client_id,),
    )
    story.append(Paragraph("Note, call e appuntamenti", styles["h2"]))
    if notes_df.empty:
        story.append(Paragraph("Nessuna nota presente.", styles["body"]))
    else:
        rows = [["Tipo", "Titolo", "Stato", "Importo", "Banca", "Scadenza"]]
        for _, row in notes_df.iterrows():
            rows.append([row["kind"], row["title"], row["status"], row["amount"] or "", row["bank"] or "", row["due_date"] or ""])
        story.append(make_table(rows, [25 * mm, 80 * mm, 25 * mm, 25 * mm, 45 * mm, 30 * mm], 7.2))

    score_df = df_query(
        "SELECT phantom_score, rating, dscr, mcc_class, financing_capacity, created_at FROM scores WHERE client_id=? ORDER BY created_at DESC LIMIT 5",
        (client_id,),
    )
    story.append(Paragraph("Valutazione CR / PHANTOM / MCC", styles["h2"]))
    if score_df.empty:
        story.append(Paragraph("Nessuna valutazione salvata.", styles["body"]))
    else:
        rows = [["PHANTOM", "Rating", "DSCR", "MCC", "Capacita stimata", "Data"]]
        for _, row in score_df.iterrows():
            rows.append([row["phantom_score"], row["rating"], row["dscr"], row["mcc_class"], row["financing_capacity"], row["created_at"]])
        story.append(make_table(rows, [24 * mm, 40 * mm, 22 * mm, 45 * mm, 36 * mm, 35 * mm], 7.2))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Nota: i punteggi sono simulazioni operative interne e devono essere verificati su dati reali, policy banca/MCC e documentazione ufficiale.", styles["small"]))
    doc.build(story, onFirstPage=pdf_header_footer, onLaterPages=pdf_header_footer)
    log_event("INFO", "REPORT", f"Creato dossier PDF {out.name}")
    return out


# -----------------------------------------------------------------------------
# Backup ed export
# -----------------------------------------------------------------------------


def create_backup_zip() -> Path:
    ensure_dirs()
    out = BACKUP_DIR / f"FinancePlus_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        if DB_PATH.exists():
            zf.write(DB_PATH, arcname="database/financeplus_master.db")
        for root in [ARCHIVE_DIR, VERIFY_DIR, REPORT_DIR, LOG_DIR]:
            if root.exists():
                for path in root.rglob("*"):
                    if path.is_file():
                        zf.write(path, arcname=str(path.relative_to(DATA_DIR)))
    log_event("INFO", "BACKUP", f"Backup creato {out.name}")
    return out


def export_table_csv(table: str) -> bytes:
    df = df_query(f"SELECT * FROM {table}")
    return df.to_csv(index=False).encode("utf-8-sig")


# -----------------------------------------------------------------------------
# Componenti UI
# -----------------------------------------------------------------------------


def sidebar_header() -> None:
    logo = find_logo_path()
    if logo and Image is not None:
        try:
            st.sidebar.image(str(logo), use_container_width=True)
        except Exception:
            st.sidebar.markdown("### FinancePlus.Tech")
    else:
        st.sidebar.markdown("## FinancePlus.Tech")
    st.sidebar.markdown(f"<span class='fp-badge'>{APP_VERSION}</span>", unsafe_allow_html=True)
    st.sidebar.write("")


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="fp-hero">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi(label: str, value: Any, help_text: str = "") -> None:
    st.markdown(
        f"""
        <div class="fp-kpi">
            <div class="label">{label}</div>
            <div class="value">{value}</div>
            <div class="help">{help_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f"<div class='fp-section-title'>{text}</div>", unsafe_allow_html=True)


def choose_client(label: str = "Cliente") -> Optional[int]:
    options = get_client_options()
    if not options:
        st.info("Prima crea almeno un cliente nella sezione Cliente 360.")
        return None
    selected = st.selectbox(label, list(options.keys()))
    return options[selected]


def status_badge(status: str) -> str:
    if status in {"ARCHIVIATO", "OK", "EVASA"}:
        return f"<span class='fp-pill-ok'>{status}</span>"
    if status in {"DA VERIFICARE", "IN ATTESA", "DUPLICATO"}:
        return f"<span class='fp-pill-warn'>{status}</span>"
    return f"<span class='fp-pill-red'>{status}</span>"


# -----------------------------------------------------------------------------
# Pagine applicative
# -----------------------------------------------------------------------------


def page_dashboard() -> None:
    hero(
        "Dashboard operativa",
        "Cliente 360, documenti, mail, OCR/IDP, scoring bancario, report e backup in un unico programma .py.",
    )
    col1, col2, col3, col4, col5 = st.columns(5)
    clients = df_query("SELECT COUNT(*) AS n FROM clients")["n"].iloc[0]
    docs = df_query("SELECT COUNT(*) AS n FROM documents")["n"].iloc[0]
    verify = df_query("SELECT COUNT(*) AS n FROM documents WHERE status='DA VERIFICARE'")["n"].iloc[0]
    mails = df_query("SELECT COUNT(*) AS n FROM mail_items")["n"].iloc[0]
    reports = len(list(REPORT_DIR.glob("*.pdf"))) if REPORT_DIR.exists() else 0
    with col1:
        kpi("Clienti", clients, "fascicoli Cliente 360")
    with col2:
        kpi("Documenti", docs, "file letti e tracciati")
    with col3:
        kpi("Da verificare", verify, "match sotto soglia")
    with col4:
        kpi("Mail", mails, "email archiviate")
    with col5:
        kpi("Report", reports, "PDF generati")

    c1, c2 = st.columns([1.2, 0.8])
    with c1:
        st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
        section_title("Flusso Cliente 360")
        st.write("**1. Crea cliente -> 2. Carica documenti/mail -> 3. Classifica e abbina -> 4. Score CR/MCC -> 5. Dossier banca**")
        steps = pd.DataFrame(
            [
                ["Input", "Upload, cartelle, IMAP/PEC, PDF, Excel, Word, EML"],
                ["Lettura", "PyMuPDF, lettura testo, metadati, OCR opzionale"],
                ["Decisione", "Regole + score confidenza + coda Da Verificare"],
                ["Archivio", "Cliente / mese / tipologia, hash SHA-256 e log"],
                ["Output", "Dashboard, CSV, dossier PDF, backup ZIP"],
            ],
            columns=["Fase", "Controllo operativo"],
        )
        st.dataframe(steps, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
        section_title("Azioni rapide")
        if st.button("Nuovo backup ZIP", use_container_width=True):
            path = create_backup_zip()
            st.success(f"Backup creato: {path.name}")
        st.download_button(
            "Export clienti CSV",
            data=export_table_csv("clients"),
            file_name="financeplus_clienti.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.download_button(
            "Export documenti CSV",
            data=export_table_csv("documents"),
            file_name="financeplus_documenti.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    section_title("Ultime attivita")
    recent = df_query(
        "SELECT created_at, level, area, message FROM app_logs ORDER BY created_at DESC LIMIT 20"
    )
    if recent.empty:
        st.info("Nessun log operativo ancora presente.")
    else:
        st.dataframe(recent, use_container_width=True, hide_index=True)


def page_clienti() -> None:
    hero("Cliente 360", "Anagrafica, documenti, mail, note, valutazioni e report banca in un fascicolo unico.")
    tab_new, tab_list = st.tabs(["Nuovo / aggiorna cliente", "Elenco e fascicolo"])
    with tab_new:
        with st.form("client_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                name = st.text_input("Ragione sociale *", placeholder="BEL GARDEN EUROPE SRL")
                piva = st.text_input("P.IVA")
                cf = st.text_input("Codice fiscale")
            with col2:
                pec = st.text_input("PEC")
                admin = st.text_input("Amministratore")
                ateco = st.text_input("ATECO")
            with col3:
                address = st.text_input("Sede")
                bank = st.text_input("Banca principale")
                notes = st.text_area("Note operative", height=105)
            submitted = st.form_submit_button("Salva cliente")
            if submitted:
                try:
                    cid = add_or_update_client({
                        "name": name, "piva": piva, "cf": cf, "pec": pec, "address": address,
                        "admin": admin, "ateco": ateco, "bank": bank, "notes": notes,
                    })
                    st.success(f"Cliente salvato - ID {cid}")
                except Exception as exc:
                    st.error(str(exc))

    with tab_list:
        df = list_clients()
        if df.empty:
            st.info("Nessun cliente presente.")
            return
        search = st.text_input("Cerca cliente", placeholder="Ragione sociale, P.IVA, PEC...")
        view_df = df.copy()
        if search:
            s = normalize_for_match(search)
            mask = view_df.apply(lambda r: s in normalize_for_match(" ".join(map(str, r.values))), axis=1)
            view_df = view_df[mask]
        st.dataframe(view_df[["id", "name", "piva", "cf", "pec", "admin", "bank", "created_at"]], use_container_width=True, hide_index=True)
        selected = st.selectbox("Apri fascicolo", [f"{r['id']} - {r['name']}" for _, r in view_df.iterrows()]) if not view_df.empty else None
        if selected:
            cid = int(selected.split(" - ")[0])
            client = get_client(cid)
            st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
            st.subheader(client["name"])
            cols = st.columns(4)
            docs_count = df_query("SELECT COUNT(*) AS n FROM documents WHERE client_id=?", (cid,))["n"].iloc[0]
            mail_count = df_query("SELECT COUNT(*) AS n FROM mail_items WHERE client_id=?", (cid,))["n"].iloc[0]
            note_count = df_query("SELECT COUNT(*) AS n FROM notes WHERE client_id=?", (cid,))["n"].iloc[0]
            last_score = df_query("SELECT phantom_score FROM scores WHERE client_id=? ORDER BY created_at DESC LIMIT 1", (cid,))
            with cols[0]: kpi("Documenti", docs_count, "collegati")
            with cols[1]: kpi("Mail", mail_count, "archiviate")
            with cols[2]: kpi("Note/Call", note_count, "operative")
            with cols[3]: kpi("Score", "-" if last_score.empty else last_score["phantom_score"].iloc[0], "PHANTOM")
            st.write(f"**P.IVA:** {client['piva'] or '-'} | **PEC:** {client['pec'] or '-'} | **Admin:** {client['admin'] or '-'}")
            if st.button("Genera dossier PDF cliente", use_container_width=True):
                try:
                    out = create_client_report(cid)
                    st.success(f"Creato: {out.name}")
                    st.download_button("Scarica dossier", out.read_bytes(), file_name=out.name, mime="application/pdf")
                except Exception as exc:
                    st.error(str(exc))
            st.markdown("</div>", unsafe_allow_html=True)

            sub1, sub2, sub3 = st.tabs(["Documenti", "Mail", "Score"])
            with sub1:
                docs = df_query("SELECT original_name, category, confidence, status, saved_path, created_at FROM documents WHERE client_id=? ORDER BY created_at DESC", (cid,))
                st.dataframe(docs, use_container_width=True, hide_index=True)
            with sub2:
                mails = df_query("SELECT subject, sender, received_at, saved_eml_path, created_at FROM mail_items WHERE client_id=? ORDER BY created_at DESC", (cid,))
                st.dataframe(mails, use_container_width=True, hide_index=True)
            with sub3:
                scores = df_query("SELECT phantom_score, rating, dscr, mcc_class, financing_capacity, created_at FROM scores WHERE client_id=? ORDER BY created_at DESC", (cid,))
                st.dataframe(scores, use_container_width=True, hide_index=True)


def page_documenti() -> None:
    hero("Documenti / IDP / Archivio", "Upload, import cartella, classificazione, matching cliente, hash SHA-256 e coda Da Verificare.")
    tab_upload, tab_folder, tab_verify, tab_archive = st.tabs(["Upload multiplo", "Import cartella locale", "Da verificare", "Archivio"])

    with tab_upload:
        client_options = get_client_options()
        manual_client = st.checkbox("Forza cliente manuale")
        forced_id = None
        if manual_client and client_options:
            forced_id = client_options[st.selectbox("Cliente destinazione", list(client_options.keys()))]
        files = st.file_uploader("Carica PDF, Word, Excel, immagini, TXT, EML o ZIP", accept_multiple_files=True)
        if st.button("Classifica e archivia upload", use_container_width=True):
            if not files:
                st.warning("Carica almeno un file.")
            else:
                rows = []
                progress = st.progress(0)
                for i, uploaded in enumerate(files, start=1):
                    try:
                        result = save_document_bytes(uploaded.getvalue(), uploaded.name, source="upload", forced_client_id=forced_id)
                    except Exception as exc:
                        result = {"ok": False, "original_name": uploaded.name, "status": "ERRORE", "message": str(exc)}
                    rows.append(result)
                    progress.progress(i / len(files))
                st.dataframe(pd.DataFrame(rows), use_container_width=True)

    with tab_folder:
        st.info("Funzione utile in locale o su server interno. Su Streamlit Cloud usare Upload multiplo, perche il browser non consente al server di leggere cartelle del PC.")
        folder = st.text_input("Percorso cartella madre", value="")
        forced_id = None
        client_options = get_client_options()
        if client_options and st.checkbox("Forza cliente per tutta la cartella", key="force_folder"):
            forced_id = client_options[st.selectbox("Cliente", list(client_options.keys()), key="force_folder_client")]
        limit = st.number_input("Limite file da processare", min_value=1, max_value=5000, value=800, step=50)
        if st.button("Scansiona sottocartelle e archivia", use_container_width=True):
            p = Path(folder).expanduser()
            if not p.exists() or not p.is_dir():
                st.error("Cartella non trovata.")
            else:
                with st.spinner("Scansione in corso..."):
                    rows = scan_local_folder(p, forced_client_id=forced_id, limit=int(limit))
                st.success(f"Processati {len(rows)} file candidati")
                st.dataframe(pd.DataFrame(rows), use_container_width=True)

    with tab_verify:
        df = df_query("SELECT id, original_name, category, confidence, status, saved_path, created_at FROM documents WHERE status='DA VERIFICARE' ORDER BY created_at DESC")
        if df.empty:
            st.success("Nessun documento in coda Da Verificare.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.warning("Per una versione production: aggiungere workflow di riassegnazione cliente/tipologia con audit utente.")

    with tab_archive:
        docs = df_query("SELECT id, original_name, category, confidence, status, source, saved_path, created_at FROM documents ORDER BY created_at DESC LIMIT 500")
        st.dataframe(docs, use_container_width=True, hide_index=True)


def page_mail() -> None:
    hero("Mail / Allegati / Cerca Azienda", "Ricerca su oggetto, corpo, mittente e nomi allegati. Vedi Tutto, Scarica Tutto, Scarica Selezionati.")
    client_options = get_client_options()
    col1, col2 = st.columns([0.42, 0.58])
    with col1:
        st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
        section_title("Configurazione IMAP")
        host = st.text_input("Server IMAP", value=st.session_state.get("imap_host", "imap.gmail.com"))
        user = st.text_input("Email / username", value=st.session_state.get("imap_user", ""))
        password = st.text_input("Password / app password", type="password")
        mailbox = st.text_input("Cartella IMAP", value="INBOX")
        days = st.number_input("Giorni indietro", 7, 3650, 365)
        max_messages = st.number_input("Max risultati", 5, 200, 40)
        azienda = st.text_input("Cerca azienda / P.IVA / parola chiave", placeholder="BEL GARDEN")
        if client_options:
            client_id = client_options[st.selectbox("Cliente destinazione per salvataggio", list(client_options.keys()))]
        else:
            client_id = None
        st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
        section_title("Risultati")
        if st.button("Cerca in email", use_container_width=True):
            if not (host and user and password and azienda):
                st.error("Compila server, account, password e azienda.")
            else:
                st.session_state["imap_host"] = host
                st.session_state["imap_user"] = user
                with st.spinner("Connessione IMAP e ricerca in corso..."):
                    try:
                        st.session_state["mail_results"] = search_imap_messages(host, user, password, azienda, mailbox, int(max_messages), int(days))
                        st.success(f"Trovate {len(st.session_state['mail_results'])} email pertinenti")
                    except Exception as exc:
                        st.error(f"Errore IMAP: {exc}")
        results: List[MailSearchResult] = st.session_state.get("mail_results", [])
        if results:
            table = pd.DataFrame([
                {
                    "uid": r.uid,
                    "data": r.date_received,
                    "mittente": r.sender,
                    "oggetto": r.subject,
                    "allegati": ", ".join(r.attachment_names[:6]),
                    "anteprima": r.preview[:180],
                }
                for r in results
            ])
            st.dataframe(table, use_container_width=True, hide_index=True)
            save_mode = st.radio("Azione", ["Vedi tutto", "Scarica tutto", "Scarica solo selezionate"], horizontal=True)
            if save_mode == "Scarica solo selezionate":
                selected_uids = st.multiselect("UID email da salvare", [r.uid for r in results])
            else:
                selected_uids = [r.uid for r in results]
            if save_mode != "Vedi tutto" and st.button("Esegui salvataggio mail + allegati", use_container_width=True):
                if not client_id:
                    st.error("Crea/seleziona un cliente destinazione.")
                else:
                    rows = []
                    for r in results:
                        if r.uid in selected_uids:
                            rows.append(save_mail_result(r, client_id, save_attachments=True))
                    st.success(f"Salvate {len(rows)} email")
                    st.json(rows)
        else:
            st.info("Nessun risultato in sessione. Esegui una ricerca.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.caption("Filtro attivo: immagini inline, loghi e firme vengono esclusi automaticamente dagli allegati documentali salvo gestione manuale.")


def page_scoring() -> None:
    hero("Centrale Rischi / PHANTOM / MCC / DSCR", "Simulatore operativo per rating interno, sostenibilita finanziaria e capacita indicativa di nuovo credito.")
    cid = choose_client("Cliente da valutare")
    if not cid:
        return
    with st.form("score_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            accordato = st.number_input("Accordato totale", min_value=0.0, value=250000.0, step=10000.0)
            utilizzato = st.number_input("Utilizzato totale", min_value=0.0, value=150000.0, step=10000.0)
            scaduto = st.number_input("Scaduti / past due", min_value=0.0, value=0.0, step=1000.0)
            sconfinamento = st.number_input("Sconfinamenti", min_value=0.0, value=0.0, step=1000.0)
        with col2:
            ebitda = st.number_input("EBITDA", min_value=-1_000_000.0, value=90000.0, step=5000.0)
            ricavi = st.number_input("Ricavi", min_value=0.0, value=850000.0, step=25000.0)
            debito_esistente = st.number_input("Debito finanziario esistente", min_value=0.0, value=180000.0, step=10000.0)
            servizio_debito = st.number_input("Servizio annuo debito", min_value=1.0, value=65000.0, step=5000.0)
        with col3:
            patrimonio = st.number_input("Patrimonio netto", min_value=-1_000_000.0, value=160000.0, step=10000.0)
            importo_richiesto = st.number_input("Importo richiesto", min_value=0.0, value=200000.0, step=10000.0)
            durata = st.number_input("Durata finanziamento anni", min_value=1, max_value=30, value=5)
            tasso = st.number_input("Tasso indicativo %", min_value=0.0, max_value=25.0, value=6.5, step=0.25)
        submitted = st.form_submit_button("Calcola e salva valutazione")
        if submitted:
            utilization = (utilizzato / accordato * 100) if accordato else 0.0
            dscr = ebitda / servizio_debito if servizio_debito else 0.0
            leverage = debito_esistente / max(ebitda, 1.0) if ebitda > 0 else 99.0
            ebitda_margin = ebitda / ricavi if ricavi else 0.0
            metrics = {
                "accordato": accordato,
                "utilizzato": utilizzato,
                "utilization": utilization,
                "past_due": scaduto,
                "overdraft": sconfinamento,
                "ebitda": ebitda,
                "revenue": ricavi,
                "existing_debt": debito_esistente,
                "debt_service": servizio_debito,
                "dscr": dscr,
                "leverage": leverage,
                "ebitda_margin": ebitda_margin,
                "patrimonio": patrimonio,
                "importo_richiesto": importo_richiesto,
                "durata": float(durata),
                "tasso": tasso,
            }
            save_score(cid, metrics)
            score, rating, mcc, cap = compute_phantom_score(metrics)
            c1, c2, c3, c4 = st.columns(4)
            with c1: kpi("PHANTOM", score, rating)
            with c2: kpi("DSCR", round(dscr, 2), "soglia prudente > 1,20")
            with c3: kpi("MCC", mcc, "classe simulata")
            with c4: kpi("Capacita", f"€ {cap:,.0f}", "stima interna")
            st.info("Valutazione indicativa: va validata con dati ufficiali, policy banca/MCC e collaudo professionale.")

    st.subheader("Storico valutazioni")
    hist = df_query("SELECT phantom_score, rating, dscr, mcc_class, financing_capacity, created_at FROM scores WHERE client_id=? ORDER BY created_at DESC", (cid,))
    st.dataframe(hist, use_container_width=True, hide_index=True)


def page_business_plan() -> None:
    hero("Business Plan / DSCR", "Scenario rapido banca-ready: ricavi, costi, EBITDA, cash flow, break-even e sostenibilita della rata.")
    cid = choose_client("Cliente")
    if not cid:
        return
    col1, col2 = st.columns([0.42, 0.58])
    with col1:
        ricavi0 = st.number_input("Ricavi anno base", value=800000.0, step=25000.0)
        crescita = st.slider("Crescita annua ricavi %", -20.0, 50.0, 8.0, 0.5)
        costi_var = st.slider("Costi variabili % ricavi", 10.0, 90.0, 55.0, 0.5)
        costi_fissi = st.number_input("Costi fissi annui", value=220000.0, step=10000.0)
        investimento = st.number_input("Investimento / richiesta", value=200000.0, step=10000.0)
        durata = st.number_input("Durata anni", min_value=1, max_value=15, value=5, key="bp_durata")
        rata_annua = st.number_input("Rata annua stimata", value=48000.0, step=2500.0)
    rows = []
    ricavi = ricavi0
    for anno in range(1, 4):
        if anno > 1:
            ricavi *= (1 + crescita / 100)
        margine = ricavi * (1 - costi_var / 100)
        ebitda = margine - costi_fissi
        cash_flow = ebitda - rata_annua
        dscr = ebitda / rata_annua if rata_annua else 0
        break_even = costi_fissi / max(1 - costi_var / 100, 0.01)
        rows.append({
            "Anno": anno,
            "Ricavi": round(ricavi, 2),
            "Margine lordo": round(margine, 2),
            "EBITDA": round(ebitda, 2),
            "Rata": round(rata_annua, 2),
            "Cash flow dopo rata": round(cash_flow, 2),
            "DSCR": round(dscr, 2),
            "Break-even ricavi": round(break_even, 2),
        })
    bp = pd.DataFrame(rows)
    with col2:
        st.dataframe(bp, use_container_width=True, hide_index=True)
        avg_dscr = bp["DSCR"].mean()
        kpi("DSCR medio 3 anni", round(avg_dscr, 2), "sostenibile se stabilmente sopra 1,20")
        if avg_dscr >= 1.25:
            st.success("Scenario sostenibile in simulazione.")
        elif avg_dscr >= 1.0:
            st.warning("Scenario da monitorare: margine di sicurezza limitato.")
        else:
            st.error("Scenario critico: rata non pienamente sostenuta dall'EBITDA.")
    if st.button("Salva scenario come nota", use_container_width=True):
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO notes(client_id, kind, title, status, amount, bank, due_date, body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid, "Business Plan", "Scenario DSCR 3 anni", "IN ATTESA", investimento,
                    "", "", bp.to_json(orient="records", force_ascii=False), datetime.now().isoformat(timespec="seconds"),
                ),
            )
        st.success("Scenario salvato nelle note cliente.")


def page_note_calendar() -> None:
    hero("Note / Call / Calendario", "Controllo operativo di richieste, stati pratica, video call, appuntamenti e follow-up.")
    tab_new, tab_list = st.tabs(["Nuova attivita", "Elenco e calendario"])
    with tab_new:
        cid = choose_client("Cliente")
        if not cid:
            return
        with st.form("note_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                kind = st.selectbox("Tipo", ["Nota", "Call", "Video call", "Appuntamento", "Richiesta banca", "Promemoria"])
                title = st.text_input("Titolo")
                status = st.selectbox("Stato", ["IN ATTESA", "INEVASA", "EVASA", "DA RICHIAMARE"])
            with col2:
                amount = st.number_input("Importo collegato", min_value=0.0, value=0.0, step=1000.0)
                bank = st.text_input("Banca / interlocutore")
                due = st.date_input("Data scadenza / appuntamento", value=date.today())
            with col3:
                body = st.text_area("Descrizione operativa", height=145)
            if st.form_submit_button("Salva attivita"):
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO notes(client_id, kind, title, status, amount, bank, due_date, body, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (cid, kind, title, status, amount, bank, due.isoformat(), body, datetime.now().isoformat(timespec="seconds")),
                    )
                st.success("Attivita salvata.")
    with tab_list:
        df = df_query(
            """
            SELECT n.id, c.name AS cliente, n.kind, n.title, n.status, n.amount, n.bank, n.due_date, n.created_at
            FROM notes n LEFT JOIN clients c ON c.id=n.client_id
            ORDER BY COALESCE(n.due_date, n.created_at) DESC
            """
        )
        if df.empty:
            st.info("Nessuna attivita presente.")
        else:
            status_filter = st.multiselect("Filtra stato", sorted(df["status"].dropna().unique().tolist()), default=[])
            view = df if not status_filter else df[df["status"].isin(status_filter)]
            st.dataframe(view, use_container_width=True, hide_index=True)


def page_report_backup() -> None:
    hero("Report PDF / Export / Backup", "Dossier Cliente 360, CSV operativi, database SQLite e archivio ZIP completo.")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
        section_title("Dossier PDF cliente")
        cid = choose_client("Seleziona cliente per report")
        if cid and st.button("Genera PDF cliente", use_container_width=True):
            try:
                out = create_client_report(cid)
                st.success(out.name)
                st.download_button("Scarica PDF", out.read_bytes(), file_name=out.name, mime="application/pdf", use_container_width=True)
            except Exception as exc:
                st.error(str(exc))
        st.markdown("</div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
        section_title("Backup e export")
        if st.button("Crea backup completo ZIP", use_container_width=True):
            out = create_backup_zip()
            st.success(out.name)
            st.download_button("Scarica backup", out.read_bytes(), file_name=out.name, mime="application/zip", use_container_width=True)
        for table in ["clients", "documents", "mail_items", "notes", "scores", "app_logs"]:
            st.download_button(
                f"CSV {table}",
                data=export_table_csv(table),
                file_name=f"financeplus_{table}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    section_title("Report generati")
    files = sorted(REPORT_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True) if REPORT_DIR.exists() else []
    if not files:
        st.info("Nessun report generato.")
    else:
        for p in files[:20]:
            with st.expander(p.name):
                st.write(f"Percorso: `{p}`")
                st.download_button("Scarica", p.read_bytes(), file_name=p.name, mime="application/pdf", key=f"dl_{p.name}")


def page_settings() -> None:
    hero("Impostazioni tecniche", "Stato ambiente, percorsi dati, logo, database e controlli prima del deploy.")
    st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
    section_title("Percorsi")
    paths = pd.DataFrame([
        ["Base app", str(BASE_DIR)],
        ["Database", str(DB_PATH)],
        ["Archivio clienti", str(ARCHIVE_DIR)],
        ["Da verificare", str(VERIFY_DIR)],
        ["Report", str(REPORT_DIR)],
        ["Backup", str(BACKUP_DIR)],
        ["Logo", str(find_logo_path() or "non trovato")],
    ], columns=["Elemento", "Percorso"])
    st.dataframe(paths, hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='fp-card'>", unsafe_allow_html=True)
    section_title("Checklist deploy")
    checklist = pd.DataFrame([
        ["Streamlit Cloud", "Nessun Tkinter, app avviabile con streamlit run", "OK"],
        ["Secrets", "Password mail e API key fuori dal codice .py", "Da configurare"],
        ["Database", "SQLite locale; valutare PostgreSQL se multiutente", "OK base"],
        ["OCR", "PyMuPDF pronto; OCR scansioni richiede Tesseract/server", "Opzionale"],
        ["Backup", "ZIP completo archivio + DB", "OK"],
        ["Logo", "PNG/ICO usato in sidebar e report", "OK se file presente"],
    ], columns=["Area", "Controllo", "Stato"])
    st.dataframe(checklist, hide_index=True, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main() -> None:
    ensure_dirs()
    init_db()
    inject_css()
    sidebar_header()

    menu = st.sidebar.radio(
        "Menu",
        [
            "Dashboard",
            "Cliente 360",
            "Documenti / IDP",
            "Mail / Cerca Azienda",
            "CR / PHANTOM / MCC",
            "Business Plan",
            "Note / Calendario",
            "Report / Backup",
            "Impostazioni",
        ],
    )

    if menu == "Dashboard":
        page_dashboard()
    elif menu == "Cliente 360":
        page_clienti()
    elif menu == "Documenti / IDP":
        page_documenti()
    elif menu == "Mail / Cerca Azienda":
        page_mail()
    elif menu == "CR / PHANTOM / MCC":
        page_scoring()
    elif menu == "Business Plan":
        page_business_plan()
    elif menu == "Note / Calendario":
        page_note_calendar()
    elif menu == "Report / Backup":
        page_report_backup()
    elif menu == "Impostazioni":
        page_settings()

    st.sidebar.markdown("---")
    st.sidebar.caption("FinancePlus.Tech - programma unico .py - grafica blu/rame - logo incluso")


if __name__ == "__main__":
    main()
