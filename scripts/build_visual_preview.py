#!/usr/bin/env python3
"""Build an autonomous, synthetic visual preview with Python's standard library.

Run from any directory: ``python scripts/build_visual_preview.py``.
The output is ``preview-dist`` at the repository root, ready for an ordinary
static HTTPS staging build. Only presentation modules are loaded: this script
never imports app.py, opens a database, contacts a gateway, or uses an account.
It does not consume previously rendered HTML or browser session files.
"""
from __future__ import annotations

import ast
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import sys
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "preview-dist"
BUILDER = "financeplus-synthetic-visual-preview-v1"
ASSETS = (
    "app.css", "public-site.css", "public-site.js", "portal.css", "portal.js", "logo.png",
)
ALLOWED_IMPORTS = {
    "__future__", "datetime", "html", "json", "re", "typing", "decimal", "urllib.parse",
    "zoneinfo", "portal_ui",
}
CSP = (
    "default-src 'none'; base-uri 'none'; object-src 'none'; form-action 'none'; "
    "connect-src 'none'; img-src 'self'; style-src 'self'; script-src 'self'; "
    "font-src 'self'; frame-src 'self'"
)
NOTICE = "ANTEPRIMA VISIVA · DATI SINTETICI · OPERAZIONI DISABILITATE"
SAMPLE_DATE = "2026-10-20"


def load_presentation_modules():
    """Reject newly introduced integration imports before executing source."""
    modules, hashes = {}, {}
    sys.dont_write_bytecode = True
    for name in ("portal_ui", "public_site", "portal_views"):
        path = ROOT / (name + ".py")
        source = path.read_text(encoding="utf-8")
        parsed = ast.parse(source, filename=str(path))
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
                if node.level:
                    raise RuntimeError(f"Relative import not permitted in preview: {name}")
            else:
                continue
            for imported in imports:
                if imported not in ALLOWED_IMPORTS:
                    raise RuntimeError(f"Preview presentation import not permitted: {name} -> {imported}")
        module = ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(parsed, str(path), "exec"), module.__dict__)
        modules[name] = module
        hashes[path.name] = sha256(source.encode("utf-8")).hexdigest()
    return modules, hashes


def synthetic_data():
    """Deliberately fictional identities; these are display fixtures, not seeds."""
    companies = [
        {"id": "demo-101", "name": "DEMO · Azienda dimostrativa A", "vat": "DEMO-IVA-001", "sector": "Manifattura · esempio"},
        {"id": "demo-102", "name": "DEMO · Azienda dimostrativa B", "vat": "DEMO-IVA-002", "sector": "Servizi · esempio"},
        {"id": "demo-103", "name": "DEMO · Azienda dimostrativa C", "vat": "DEMO-IVA-003", "sector": "Commercio · esempio"},
    ]
    practice_specs = (
        ("demo-p101", 0, "DEMO · Investimento in macchinari", 180000, "In verifica", "Verificare il preventivo dimostrativo", "Preventivo di esempio"),
        ("demo-p102", 0, "DEMO · Liquidità per la gestione", 32000, "Integrazione documenti", "Completare la raccolta dei documenti di esempio", "Situazione contabile di esempio"),
        ("demo-p201", 1, "DEMO · Piano di sviluppo", 75000, "In lavorazione", "Confrontare le ipotesi dimostrative", "Piano economico di esempio"),
        ("demo-p301", 2, "DEMO · Riepilogo progetto", 45000, "Completata", "Leggere il riepilogo dimostrativo", ""),
    )
    practices = []
    for pid, index, title, amount, status, next_action, missing in practice_specs:
        client = companies[index]
        practices.append({
            "id": pid, "client_id": client["id"], "client_name": client["name"],
            "title": title, "amount": amount, "status": status,
            "purpose": "Finalità esclusivamente dimostrativa",
            "institution": "Operatore dimostrativo · nessun servizio reale",
            "next_action": next_action, "missing_documents": [missing] if missing else [],
            "assigned_collaborators": [{"id": "demo-collaborator", "name": "Collaboratore DEMO"}],
            "document_requests": [{"description": missing, "status": "Aperta", "requested_at": SAMPLE_DATE}] if missing else [],
            "updated_at": SAMPLE_DATE,
        })
    documents = []
    for index, client in enumerate(companies, start=1):
        for suffix, category, status in (("bilancio", "Bilancio", "Da verificare"), ("visura", "Visura", "Validato · esempio")):
            documents.append({
                "id": f"demo-doc-{index}-{suffix}", "client_id": client["id"],
                "client_name": client["name"], "title": f"DEMO_{suffix}_{index}.pdf",
                "category": category, "status": status, "date": SAMPLE_DATE,
            })
    tasks = [
        {"id": f"demo-task-{index}", "client_id": c["id"], "client_name": c["name"],
         "title": "DEMO · Revisione del fascicolo di esempio", "due_date": f"2026-11-{index + 2:02d}", "status": "Da completare"}
        for index, c in enumerate(companies, start=1)
    ]
    bundles = []
    for index, client in enumerate(companies):
        analysis = None if index == 1 else {
            "status": "Dimostrativo", "period": "Esercizio 2025 · esempio", "version": "DEMO",
            "source": "Dati sintetici della sola anteprima", "updated_at": SAMPLE_DATE,
            "summary": "Testo di esempio per valutare la leggibilità della scheda. Non deriva da documenti, calcoli o valutazioni di un’impresa reale.",
        }
        bundles.append({
            "client": client, "requests": [p for p in practices if p["client_id"] == client["id"]],
            "documents": [d for d in documents if d["client_id"] == client["id"]],
            "tasks": [t for t in tasks if t["client_id"] == client["id"]],
            "analysis": analysis, "notes": [{"body": "DEMO · Nota del fascicolo interamente sintetica.", "created_at": SAMPLE_DATE}],
            "documents_loaded": True, "tasks_loaded": True, "read_at": SAMPLE_DATE,
            "source": "ANTEPRIMA SINTETICA", "restricted": False,
        })
    data = {
        "companies": companies, "practices": practices, "documents": documents, "tasks": tasks,
        "documents_loaded": True, "tasks_loaded": True, "complete": True,
        "all_companies_count": len(companies), "all_practices_count": len(practices),
        "role_fields_available": ["collaborator"],
    }
    return data, bundles


class PreviewHTML(HTMLParser):
    """Keep presentation markup, local navigation and menus; remove operations."""
    def __init__(self, routes, client_routes, service_routes):
        super().__init__(convert_charrefs=False)
        self.routes, self.client_routes, self.service_routes = routes, client_routes, service_routes
        self.parts, self.skip = [], []

    def destination(self, value):
        parsed = urlsplit(value.strip())
        if parsed.scheme or parsed.netloc:
            return None
        if not parsed.path:
            return "#" + parsed.fragment if parsed.fragment else None
        if parsed.path.startswith("/app/clienti/"):
            cid = parsed.path[len("/app/clienti/"):]
            query = parse_qs(parsed.query)
            tab = query.get("tab", ["sintesi"])[0]
            practice = query.get("practice", [None])[0]
            result = self.client_routes.get((cid, tab, practice)) or self.client_routes.get((cid, tab, None))
        else:
            result = self.routes.get(parsed.path) or self.service_routes.get(parsed.path)
        return result + ("#" + parsed.fragment if parsed.fragment else "") if result else None

    @staticmethod
    def asset(value):
        return "assets/" + value[len("/static/"):] if value.startswith("/static/") and value[len("/static/"):] in ASSETS else None

    def start(self, tag, attrs, closed=False):
        if self.skip:
            if tag == self.skip[-1] and not closed:
                self.skip.append(tag)
            return
        values = dict(attrs)
        if tag in {"iframe", "object", "embed", "base"} or (tag == "script" and self.asset(values.get("src", "")) not in {"assets/public-site.js", "assets/portal.js"}):
            if tag not in {"embed", "base"} and not closed:
                self.skip.append(tag)
            return
        if tag == "meta" and values.get("http-equiv", "").lower() == "refresh":
            return
        if tag == "input" and values.get("type") == "hidden":
            return
        original = tag
        if tag == "form":
            tag = "div"
            values["data-preview-form"] = "disabled"
            values["aria-label"] = "Controlli disabilitati nell’anteprima sintetica"
        for key in list(values):
            if key.lower().startswith("on") or key in {"action", "formaction", "method", "target", "download", "ping", "srcset", "xlink:href", "data-print", "data-confirm", "integrity", "crossorigin"}:
                del values[key]
        if original == "a":
            destination = self.destination(values.get("href", ""))
            if destination:
                values["href"] = destination
            else:
                values.pop("href", None)
                values.update({"aria-disabled": "true", "tabindex": "-1", "title": "Azione non disponibile nell’anteprima sintetica"})
                values["class"] = values.get("class", "") + " preview-disabled"
        elif "href" in values:
            asset = self.asset(values["href"])
            if not asset:
                return
            values["href"] = asset
        if "src" in values:
            asset = self.asset(values["src"])
            if not asset:
                return
            values["src"] = asset
        if tag in {"input", "textarea", "select"} or (tag == "button" and not {"p-menu-toggle", "fp-menu-toggle"}.intersection(values.get("class", "").split())):
            values["disabled"] = None
            values["aria-disabled"] = "true"
            if tag == "button":
                values["type"] = "button"
        rendered = []
        for key, value in values.items():
            key = {"viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio"}.get(key, key)
            rendered.append(key if value is None else f'{key}="{escape(value, quote=True)}"')
        self.parts.append("<" + tag + (" " + " ".join(rendered) if rendered else "") + ("/>" if closed else ">"))

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, True)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        self.parts.append("</" + ("div" if tag == "form" else tag) + ">")

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)

    def handle_entityref(self, name):
        if not self.skip:
            self.parts.append("&" + name + ";")

    def handle_charref(self, name):
        if not self.skip:
            self.parts.append("&#" + name + ";")

    def handle_decl(self, decl):
        if not self.skip:
            self.parts.append("<!" + decl + ">")


PREVIEW_CSS = """
.preview-notice{position:relative;z-index:90;box-sizing:border-box;width:100%;padding:11px 18px;background:#fff3cf;color:#493711;border-bottom:1px solid #d6b86a;font:13px/1.5 system-ui,sans-serif;display:flex;gap:6px 20px;justify-content:space-between;align-items:center;flex-wrap:wrap}
.preview-notice strong{font-size:11px;letter-spacing:.045em}.preview-notice p{margin:3px 0 0;font-size:12px}.preview-notice nav{display:flex;gap:18px;flex-wrap:wrap}.preview-notice a{color:#173e59;text-decoration:underline;text-underline-offset:3px;font-weight:700}
.preview-disabled{cursor:not-allowed!important;opacity:.62}.preview-disabled:hover{box-shadow:none!important} [data-preview-form] button:disabled{cursor:not-allowed}
.preview-index{font:16px/1.6 system-ui,sans-serif;background:#edf3f8;color:#173e59;margin:0}.preview-wrap{max-width:1200px;margin:0 auto;padding:38px 24px}.preview-wrap h1{font-size:clamp(27px,4vw,42px);line-height:1.15;letter-spacing:-.03em;margin:0 0 16px}.preview-wrap h2{font-size:23px;margin:30px 0 15px}.preview-intro{max-width:810px;color:#50677a}.preview-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:16px}.preview-card{display:block;background:#fff;border:1px solid #cedce6;border-radius:13px;padding:22px;text-decoration:none;color:#173e59}.preview-card strong{display:block;font-size:20px}.preview-card span{display:block;margin-top:10px;color:#587084;font-size:14px}.preview-card:hover{border-color:#456f8a}.preview-card:focus-visible,.preview-notice a:focus-visible{outline:3px solid #2777a4;outline-offset:4px}
.preview-mobile-links{display:flex;flex-wrap:wrap;gap:10px 20px}.preview-mobile-links a{color:#173e59}.preview-phone-section{padding:18px 0 36px;border-bottom:1px solid #c8d9e4;scroll-margin-top:16px}.preview-phone-row{display:flex;align-items:flex-start;gap:24px;overflow-x:auto;padding:4px 4px 15px}.preview-phone{flex:none;margin:0}.preview-phone figcaption{font-size:14px;font-weight:700;margin-bottom:10px}.preview-phone iframe{display:block;box-sizing:content-box;max-width:none;height:1450px;background:#fff;border:1px solid #7693a6;border-radius:8px}.preview-width-390{width:390px}.preview-width-360{width:360px}
@media(max-width:500px){.preview-wrap{padding:28px 16px}.preview-notice{padding:9px 13px}.preview-notice p{font-size:11px}}
@media print{.preview-notice{display:block!important;position:static;background:#fff;color:#000;border:2px solid #000}.preview-notice nav{display:none}}
""".strip()


def banner():
    return ('<div class="preview-notice" role="note"><div><strong>' + NOTICE
            + '</strong><p>Imprese, persone, importi e documenti sono esempi. Nessun account o sistema operativo collegato.</p></div>'
            + '<nav aria-label="Navigazione dell’anteprima"><a href="index.html">Tutte le schermate</a><a href="mobile.html">Viste mobile</a></nav></div>')


def decorate(html):
    head = (f'<meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer">'
            f'<meta http-equiv="Content-Security-Policy" content="{escape(CSP, quote=True)}">'
            '<link rel="stylesheet" href="assets/preview.css">')
    html = html.replace("</head>", head + "</head>", 1)
    return re.sub(r"(<body\b[^>]*>)", lambda match: match.group(1) + banner(), html, count=1)


def public_document(public, title, path, content):
    footer = public.footer_html("demo@example.invalid", "0000000000", year=2026)
    footer = re.sub(r"P\.IVA\s+\d{11}", "Identificativo DEMO", footer)
    return (f'<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · Anteprima FinancePlus</title>'
            '<link rel="icon" href="/static/logo.png"><link rel="stylesheet" href="/static/app.css"><link rel="stylesheet" href="/static/public-site.css"><script defer src="/static/public-site.js"></script></head><body>'
            + public.header_html(path) + '<main id="main-content">' + content + '</main>' + footer + '</body></html>')


def render_pages(modules):
    ui, public, views = (modules[key] for key in ("portal_ui", "public_site", "portal_views"))
    data, bundles = synthetic_data()
    user = SimpleNamespace(display_name="Operatore DEMO", email="demo@example.invalid", role="admin")
    raw, titles = {}, {}
    routes = {
        "/": "home.html", "/servizi": "servizi.html", "/piattaforma": "piattaforma.html",
        "/app": "dashboard.html", "/login": "dashboard.html", "/app/clienti": "clienti.html",
        "/app/pratiche": "pratiche.html", "/app/documenti": "documenti.html", "/app/analisi": "analisi.html",
        "/app/report": "report.html", "/app/agenda": "agenda.html", "/app/finanziatori": "finanziatori.html",
        "/lele-k-plus": "piattaforma.html#app", "/go/app": "piattaforma.html#app",
    }
    service_routes, client_routes = {}, {}

    def public_page(filename, title, path, content):
        raw[filename] = public_document(public, title, path, content)
        titles[filename] = title

    def workspace(filename, title, content, active="/app"):
        raw[filename] = ui.shell(user, title, "Anteprima con dati interamente sintetici", content,
                                 active=active, source_label="DEMO · Nessuna lettura dal MASTER", csrf="")
        titles[filename] = title

    service_titles = ("Strategia d’impresa", "Pianificazione e controllo", "Accesso al credito", "Merito creditizio", "Business plan", "Invoice trading")
    services = [(title, details[1], "") for title, details in zip(service_titles, public.SERVICE_DETAILS)]
    public_page("home.html", "Vetrina · Home", "/", public.home_body())
    public_page("servizi.html", "Soluzioni", "/servizi", public.services_body(services))
    public_page("piattaforma.html", "Piattaforma", "/piattaforma", public.platform_body())
    for slug in public.SERVICE_SLUGS:
        title, body = public.service_body(slug, services)
        filename = "servizio-" + slug + ".html"
        service_routes["/servizi/" + slug] = filename
        public_page(filename, title, "/servizi/" + slug, body)
    workspace("dashboard.html", "Panoramica", views.dashboard_view(data, role="admin", can_upload=True, can_create_client=True))
    workspace("clienti.html", "Clienti e aziende", views.companies_view(data, role="admin", can_upload=True, can_create_client=True), "/app/clienti")
    workspace("pratiche.html", "Pratiche", views.practices_view(data, role="admin"), "/app/pratiche")
    workspace("documenti.html", "Documenti", views.documents_view(data["documents"], can_upload=True), "/app/documenti")
    workspace("analisi.html", "Analisi e CR", views.analytics_view(bundles), "/app/analisi")
    workspace("report.html", "Report", views.reports_view(bundles), "/app/report")
    workspace("agenda.html", "Agenda", views.agenda_view(data["tasks"]), "/app/agenda")
    workspace("finanziatori.html", "Finanziatori", views.finance_view(), "/app/finanziatori")
    for index, bundle in enumerate(bundles):
        cid = bundle["client"]["id"]
        prefix = "cliente-360" if index == 0 else "cliente-" + cid
        for tab, label in views.TABS:
            filename = prefix + ("" if tab == "sintesi" else "-" + tab) + ".html"
            client_routes[(cid, tab, None)] = filename
            workspace(filename, "Cliente 360 · " + label, views.client_view(bundle, selected_tab=tab, role="admin", can_upload=True), "/app/clienti")
        for practice in bundle["requests"]:
            filename = prefix + "-pratica-" + practice["id"] + ".html"
            client_routes[(cid, "pratiche", practice["id"])] = filename
            workspace(filename, "Cliente 360 · Pratica", views.client_view(bundle, selected_tab="pratiche", selected_practice=practice["id"], role="admin"), "/app/clienti")
    pages = {}
    for filename, html in raw.items():
        parser = PreviewHTML(routes, client_routes, service_routes)
        parser.feed(html)
        parser.close()
        pages[filename] = decorate("".join(parser.parts))
    return pages, titles


def catalogue(pages, titles):
    featured = (
        ("home.html", "La nuova vetrina e l’illustrazione del percorso."),
        ("servizi.html", "Soluzioni e pagine di approfondimento."),
        ("piattaforma.html", "Aree e funzionalità presentate al pubblico."),
        ("dashboard.html", "Panoramica dell’amministratore con tre imprese dimostrative."),
        ("clienti.html", "Lista aziende, filtri e richieste di esempio."),
        ("cliente-360.html", "Scheda dell’impresa e sei sezioni collegate."),
        ("documenti.html", "Archivio dimostrativo con stati di revisione."),
        ("analisi.html", "Esiti di esempio e caso senza analisi disponibile."),
        ("report.html", "Elaborati dimostrativi; anteprime e download operativi disabilitati."),
    )
    def document(title, content):
        return decorate(f'<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title></head><body class="preview-index"><main class="preview-wrap">{content}</main></body></html>')
    cards = "".join(f'<a class="preview-card" href="{filename}"><strong>{escape(titles[filename])}</strong><span>{escape(description)}</span></a>' for filename, description in featured)
    auxiliary = "".join(f'<li><a href="{filename}">{escape(titles[filename])}</a></li>' for filename in ("pratiche.html", "agenda.html", "finanziatori.html", "cliente-demo-102-analisi.html"))
    pages["index.html"] = document("FinancePlus · Anteprima visiva", '<h1>FinancePlus · Anteprima del nuovo sito</h1><p class="preview-intro">Queste schermate sono generate dai componenti di presentazione del prodotto. I contenuti operativi sono interamente sintetici: puoi esplorare le viste e i menu; i controlli che eseguono operazioni sono disabilitati.</p><div class="preview-cards">' + cards + '</div><h2>Altre viste</h2><ul>' + auxiliary + '</ul><h2>Controllo su telefono</h2><p><a href="mobile.html">Apri tutte le schermate a 390 e 360 px</a>.</p>')
    mobile_links, sections = [], []
    for filename, _ in featured:
        key, title = filename.removesuffix(".html"), titles[filename]
        mobile_links.append(f'<a href="#{key}">{escape(title)}</a>')
        frames = "".join(f'<figure class="preview-phone"><figcaption>{width} px · <a href="{filename}" target="_self">Apri pagina</a></figcaption><iframe class="preview-width-{width}" title="{escape(title)} · {width} px · dati sintetici" src="{filename}" width="{width}" height="1450" loading="lazy" referrerpolicy="no-referrer" sandbox="allow-scripts allow-same-origin"></iframe></figure>' for width in (390, 360))
        sections.append(f'<section class="preview-phone-section" id="{key}"><h2>{escape(title)}</h2><div class="preview-phone-row">{frames}</div></section>')
    pages["mobile.html"] = document("FinancePlus · Anteprima mobile", '<h1>Schermate mobile · 390 e 360 px</h1><p class="preview-intro">Ogni riquadro usa le stesse pagine e gli stessi fogli di stile della build. Scorri dentro il riquadro per controllare la pagina; usa i menu per verificare la navigazione compatta. I breakpoint dipendono dalla larghezza effettiva del riquadro.</p><nav class="preview-mobile-links" aria-label="Schermate mobile">' + "".join(mobile_links) + '</nav>' + "".join(sections))


class OutputCheck(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.ids, self.errors = [], set(), []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            if values["id"] in self.ids:
                self.errors.append("Duplicate ID: " + values["id"])
            self.ids.add(values["id"])
        if tag == "form" or any(key.lower().startswith("on") for key in values):
            self.errors.append("Executable form or inline event remains")
        if tag in {"input", "select", "textarea"} and "disabled" not in values:
            self.errors.append("Enabled form control remains")
        for key in ("href", "src", "action", "formaction", "ping", "srcset"):
            if key in values:
                parsed = urlsplit(values[key])
                if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
                    self.errors.append("Non-preview URL remains: " + values[key])
                self.refs.append(parsed)


def validate(pages):
    parsed = {}
    for filename, html in pages.items():
        check = OutputCheck()
        check.feed(html)
        check.close()
        if NOTICE not in html or "connect-src &#x27;none&#x27;" not in html:
            check.errors.append("Synthetic notice or network restriction missing")
        if check.errors:
            raise RuntimeError(filename + ": " + "; ".join(check.errors))
        parsed[filename] = check
    for filename, check in parsed.items():
        for ref in check.refs:
            if ref.path.startswith("assets/"):
                if ref.path not in {"assets/" + name for name in ASSETS} | {"assets/preview.css"}:
                    raise RuntimeError("Unknown asset: " + ref.path)
                continue
            target = ref.path or filename
            if target not in parsed or (ref.fragment and ref.fragment not in parsed[target].ids):
                raise RuntimeError(f"Unresolved preview link: {filename} -> {ref.geturl()}")


def main():
    modules, source_hashes = load_presentation_modules()
    pages, titles = render_pages(modules)
    catalogue(pages, titles)
    validate(pages)
    asset_hashes, asset_bytes = {}, {}
    for name in ASSETS:
        asset = ROOT / "static" / name
        raw = asset.read_bytes()
        if name.endswith((".css", ".js")) and re.search(rb"https?://|@import\s|\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon", raw):
            raise RuntimeError("Review required before copying a network-capable preview asset: " + name)
        asset_hashes[name] = sha256(raw).hexdigest()
        asset_bytes[name] = raw
    if OUTPUT.is_symlink():
        raise RuntimeError("Refusing a symlink as preview output")
    if OUTPUT.exists():
        marker = OUTPUT / "preview-manifest.json"
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("builder") != BUILDER:
            raise RuntimeError("Output already exists and is not owned by this preview builder")
        shutil.rmtree(OUTPUT)
    (OUTPUT / "assets").mkdir(parents=True)
    for name, raw in asset_bytes.items():
        (OUTPUT / "assets" / name).write_bytes(raw)
    (OUTPUT / "assets" / "preview.css").write_text(PREVIEW_CSS + "\n", encoding="utf-8")
    for name, html in sorted(pages.items()):
        (OUTPUT / name).write_text(html + "\n", encoding="utf-8")
    (OUTPUT / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    manifest = {"builder": BUILDER, "synthetic_data_only": True, "forms_disabled": True,
                "network_connections": False, "source_sha256": source_hashes,
                "asset_sha256": asset_hashes, "pages": sorted(pages), "page_count": len(pages)}
    (OUTPUT / "preview-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(pages)} synthetic preview pages in {OUTPUT}")
    print("Validated local links, disabled forms, visible synthetic labels and no external URLs.")


if __name__ == "__main__":
    main()
