"""Presentation-only public website components.

No database, financial engine or application integration is defined here.  The
caller owns authentication, editorial persistence and the existing app routes.
"""
from __future__ import annotations

from datetime import date
from html import escape
import re
from typing import Mapping, Sequence


HOME_DEFAULTS = {
    "hero_eyebrow": "CONSULENZA E STRUMENTI PER LE IMPRESE",
    "hero_title": "La finanza della tua impresa, sotto controllo.",
    "hero_text": "Dai documenti alle decisioni, un percorso chiaro per la tua impresa. Con gli strumenti FinancePlus e il supporto del tuo consulente.",
    "hero_cta_label": "Scopri l’app",
    "hero_cta_href": "/lele-k-plus",
    "hero_image_url": "",
    "hero_image_alt": "",
}

SERVICE_SLUGS = (
    "strategia-impresa", "pianificazione-controllo", "accesso-credito",
    "merito-creditizio", "business-plan", "invoice-trading",
)

SERVICE_DETAILS = (
    ("Una direzione chiara, prima delle decisioni.",
     "Mettiamo a fuoco obiettivi, risorse e priorità per costruire un percorso di sviluppo coerente con la tua impresa.",
     ("Confronto su obiettivi e vincoli", "Lettura del modello di business", "Priorità, responsabilità e piano delle azioni"),
     "Una visione condivisa del progetto e delle attività da affrontare."),
    ("Numeri leggibili. Scelte consapevoli.",
     "Organizziamo le informazioni economiche e finanziarie per seguire margini, fabbisogni e andamento della gestione.",
     ("Raccolta dei dati gestionali disponibili", "Budget, forecast e indicatori pertinenti", "Lettura degli scostamenti e azioni correttive"),
     "Un quadro di controllo costruito sulle informazioni della tua azienda."),
    ("Prepara la tua impresa al confronto con il credito.",
     "Ti accompagniamo nella definizione del fabbisogno e nella preparazione delle informazioni utili alla richiesta di finanziamento.",
     ("Obiettivo, importo e finalità della richiesta", "Verifica documentale e informazioni mancanti", "Preparazione del dossier e supporto alla pratica"),
     "Una richiesta più chiara e documentata. La decisione di finanziamento resta all’istituto competente."),
    ("Conosci il profilo della tua impresa.",
     "Leggiamo bilanci, Centrale Rischi e flussi per individuare aspetti da approfondire e possibili interventi di miglioramento.",
     ("Verifica delle fonti e dei periodi", "Lettura economica, patrimoniale e finanziaria", "Criticità, approfondimenti e piano di miglioramento"),
     "Una valutazione professionale con fonti e limiti espliciti, distinta dalla delibera di una banca."),
    ("Dai forma ai tuoi progetti di investimento.",
     "Traduciamo obiettivi e ipotesi in un piano economico e finanziario, verificando fabbisogni e sostenibilità del progetto.",
     ("Progetto, investimenti e ipotesi di partenza", "Previsioni economiche e flussi di cassa", "Scenari, sensibilità e sostenibilità del debito"),
     "Un business plan coerente, con ipotesi riconoscibili e scenari confrontabili."),
    ("Valuta le opportunità legate ai crediti commerciali.",
     "Esaminiamo documenti, caratteristiche dei crediti e fabbisogno di liquidità per preparare una valutazione delle opzioni disponibili.",
     ("Fatture, contratti e documenti di supporto", "Profilo del cedente e del debitore", "Pre-fattibilità e preparazione del dossier"),
     "Una valutazione preliminare documentata. Condizioni e ammissibilità richiedono la verifica dell’operatore."),
)


def _e(value: object) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def normalize_home_content(content: Mapping[str, object] | None = None) -> dict[str, str]:
    """Normalize only supported editorial fields; never accept executable URLs."""
    result = dict(HOME_DEFAULTS)
    for key, value in (content or {}).items():
        if key in result and isinstance(value, str):
            result[key] = value.strip()[:1400 if key == "hero_text" else 300]
    for key in ("hero_eyebrow", "hero_title", "hero_text", "hero_cta_label"):
        if not result[key]:
            result[key] = HOME_DEFAULTS[key]
    if result["hero_cta_href"] not in {
        "/lele-k-plus", "/contatti", "/login", "/registrazione", "/piattaforma", "/go/app", "/servizi"
    }:
        result["hero_cta_href"] = HOME_DEFAULTS["hero_cta_href"]
    # Editorial media must already have been accepted into the site's static
    # assets by the host application. No remote tracking or arbitrary schemes.
    image = result["hero_image_url"]
    if image and not re.fullmatch(r"/static/[A-Za-z0-9_/-]+\.(?:png|jpg|jpeg|webp)", image, re.I):
        result["hero_image_url"] = ""
    if result["hero_image_url"] and not result["hero_image_alt"]:
        result["hero_image_alt"] = "FinancePlus, consulenza per le imprese"
    return result


def icon(name: str, *, extra_class: str = "") -> str:
    paths = {
        "arrow": '<path d="M4 12h15m-6-6 6 6-6 6"/>',
        "building": '<path d="M4 21V4h11v17M15 9h5v12M2 21h20M8 8h3M8 12h3M8 16h3M8 21v-2h3v2"/>',
        "document": '<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6"/>',
        "phone": '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 5h4M11 19h2"/>',
        "people": '<circle cx="9" cy="8" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 5"/>',
        "message": '<path d="M4 4h16v12H9l-5 4zM8 8h8M8 12h5"/>',
        "check": '<path d="m5 12 4 4L19 6"/>',
        "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/>',
        "chart": '<path d="M3 21h18M6 18v-5h3v5M11 18V8h3v10M16 18V3h3v15"/>',
        "shield": '<path d="m12 2 8 3v6c0 5-4 8-8 11-4-3-8-6-8-11V5zM8 11l3 3 5-5"/>',
        "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 10h18M7 14h3M14 14h3M7 18h3"/>',
    }
    return f'<svg class="fp-icon {_e(extra_class)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{paths.get(name, paths["document"])}</svg>'


def header_html(current_path: str, authenticated: bool = False) -> str:
    nav = (("/servizi", "Soluzioni"), ("/metodo", "Metodo"), ("/piattaforma", "Piattaforma"),
           ("/lele-k-plus", "App"), ("/insights", "Risorse"), ("/chi-siamo", "Chi siamo"))
    links = "".join(
        f'<a href="{url}"' + (' aria-current="page"' if current_path == url or current_path.startswith(url + "/") else '') + f'>{label}</a>'
        for url, label in nav
    )
    account_href, account_label = ("/app", "Area riservata") if authenticated else ("/login", "Accedi")
    return f'''<a class="fp-skip" href="#main-content">Vai al contenuto</a>
<header class="fp-header"><div class="fp-container fp-header-inner">
<a class="fp-brand" href="/" aria-label="FinancePlus.tech — Home"><img src="/static/logo.png" width="64" height="64" alt=""><span>FinancePlus<span class="fp-brand-tech">.tech</span><small>DATA · STRATEGY · RESULTS</small></span></a>
<button class="fp-menu-toggle" type="button" aria-expanded="false" aria-controls="financeplus-navigation" hidden><span class="fp-menu-lines" aria-hidden="true"></span><span>Menu</span></button>
<nav class="fp-nav" id="financeplus-navigation" aria-label="Navigazione principale">{links}<a class="fp-button fp-button-outline fp-account" href="{account_href}">{account_label}</a><a class="fp-button fp-button-copper" href="/contatti">Parla con noi</a></nav>
</div></header>'''


def footer_html(contact_email: str, phone: str, year: int | None = None) -> str:
    tel = re.sub(r"[^+0-9]", "", phone)
    return f'''<footer class="fp-footer"><div class="fp-container"><div class="fp-footer-grid">
<div class="fp-footer-brand"><a href="/" class="fp-footer-wordmark">FinancePlus<span>.tech</span></a><p>Consulenza per la strategia, la gestione<br>e la finanza della tua impresa.</p><span class="fp-footer-payoff">DATA · STRATEGY · RESULTS</span></div>
<div><h2>Esplora</h2><a href="/servizi">Soluzioni per le imprese</a><a href="/metodo">Il nostro metodo</a><a href="/chi-siamo">Chi siamo</a><a href="/insights">Risorse</a></div>
<div><h2>Il tuo spazio</h2><a href="/lele-k-plus">App LELE_K_PLUS</a><a href="/piattaforma">Piattaforma</a><a href="/login">Accedi all’area riservata</a><a href="/registrazione">Richiedi un account</a></div>
<div><h2>Parliamone</h2><a href="mailto:{_e(contact_email)}">{_e(contact_email)}</a><a href="tel:{_e(tel)}">{_e(phone)}</a><a href="/contatti">Raccontaci il tuo progetto {icon('arrow')}</a></div>
</div><div class="fp-footer-bottom"><span>© {year or date.today().year} Financeplus S.r.l. · P.IVA 04825280615</span><span>Un percorso chiaro. Un referente. Ogni passo visibile.</span></div></div></footer>'''


def home_body(content: Mapping[str, object] | None = None) -> str:
    c = normalize_home_content(content)
    image = (
        f'<img class="fp-hero-photo" src="{_e(c["hero_image_url"])}" alt="{_e(c["hero_image_alt"])}" fetchpriority="high">'
        if c["hero_image_url"] else '<div class="fp-hero-orbit fp-hero-orbit-one"></div><div class="fp-hero-orbit fp-hero-orbit-two"></div>'
    )
    areas = (
        ("chart", "Finanza d’impresa", "Soluzioni per la gestione, il credito e i tuoi progetti di crescita.", "/servizi"),
        ("document", "Documenti e pratiche", "Conosci il percorso: raccolta, verifica, analisi e prossime azioni.", "/piattaforma"),
        ("phone", "App e area riservata", "Scopri LELE_K_PLUS e i punti di accesso al tuo spazio FinancePlus.", "/lele-k-plus"),
    )
    area_cards = "".join(f'<a class="fp-area" href="{href}"><span class="fp-area-icon">{icon(ico)}</span><span><h3>{title}</h3><p>{text}</p></span>{icon("arrow", extra_class="fp-area-arrow")}</a>' for ico,title,text,href in areas)
    steps = (("01", "message", "Raccontaci il progetto", "Partiamo dai tuoi obiettivi e dalle esigenze della tua impresa."),
             ("02", "document", "Condividi le informazioni", "Definiamo insieme quali documenti servono per il tuo percorso."),
             ("03", "people", "Affronta il prossimo passo", "Il tuo consulente ti accompagna dalla lettura dei dati alle azioni."))
    journey = "".join(f'<li><span class="fp-step-number">{n}</span><span class="fp-step-icon">{icon(ico)}</span><div><h3>{title}</h3><p>{text}</p></div></li>' for n,ico,title,text in steps)
    return f'''<div class="fp-public">
<section class="fp-hero" aria-labelledby="fp-home-title"><div class="fp-container fp-hero-grid">
<div class="fp-hero-copy"><p class="fp-eyebrow">{_e(c['hero_eyebrow'])}</p><h1 id="fp-home-title">{_e(c['hero_title'])}</h1><p class="fp-lead">{_e(c['hero_text'])}</p><div class="fp-actions"><a class="fp-button fp-button-copper" href="{_e(c['hero_cta_href'])}">{_e(c['hero_cta_label'])} {icon('arrow')}</a><a class="fp-button fp-button-outline" href="/contatti">Richiedi una consulenza</a></div><p class="fp-hero-note">Un percorso chiaro. Un referente. Ogni passo visibile.</p></div>
<div class="fp-hero-visual">{image}<div class="fp-visual-caption"><span class="fp-small-dot"></span> LELE_K_PLUS · IL TUO SPAZIO FINANCEPLUS</div>
<div class="fp-device" aria-label="Illustrazione delle aree del percorso FinancePlus"><div class="fp-device-top" aria-hidden="true"></div><div class="fp-device-brand"><img src="/static/logo.png" width="42" height="42" alt=""><span>FinancePlus.tech</span></div><p class="fp-device-overline">VICINO ALLA TUA IMPRESA</p><h2>Il tuo percorso.</h2><p class="fp-device-intro">Informazioni, confronto,<br>prossime azioni.</p><div class="fp-device-row">{icon('document')}<div><strong>Documenti</strong><span>Le informazioni da condividere</span></div></div><div class="fp-device-row">{icon('building')}<div><strong>La tua impresa</strong><span>Obiettivi e progetti al centro</span></div></div><div class="fp-device-row">{icon('message')}<div><strong>Il tuo consulente</strong><span>Un riferimento nel percorso</span></div></div><div class="fp-device-base"><span>{icon('phone')} App</span><span>{icon('document')} Documenti</span><span>{icon('people')} Consulenza</span></div><span class="fp-illustration-label">Illustrazione del percorso</span></div>
<div class="fp-floating-note">{icon('shield')}<div><strong>Metodo e relazione</strong><span>La tecnologia al servizio delle scelte.</span></div></div></div>
</div></section>
<div class="fp-container fp-journey-wrap"><ol class="fp-journey">{journey}</ol></div>
<section class="fp-section fp-solutions" aria-labelledby="fp-tools-title"><div class="fp-container"><div class="fp-section-heading"><p class="fp-eyebrow">FINANCEPLUS, CON TE</p><h2 id="fp-tools-title">Strumenti utili,<br class="fp-mobile-break"> consulenza vicina.</h2><p>Un unico punto di partenza per orientarti nella finanza d’impresa.</p></div><div class="fp-area-grid">{area_cards}</div></div></section>
<section class="fp-section fp-method" aria-labelledby="fp-method-title"><div class="fp-container fp-method-grid"><div><p class="fp-eyebrow">DAL DATO ALLA DECISIONE</p><h2 id="fp-method-title">Prima comprendere.<br>Poi scegliere.</h2><p class="fp-lead">Ogni impresa ha una storia, obiettivi e vincoli diversi. Partiamo da qui per dare una direzione concreta al lavoro.</p><a class="fp-text-link" href="/metodo">Scopri il metodo FinancePlus {icon('arrow')}</a></div><div class="fp-method-list"><div><span>01</span><h3>Dati e contesto</h3><p>Mettiamo in ordine le informazioni disponibili e ciò che manca.</p></div><div><span>02</span><h3>Lettura e confronto</h3><p>Colleghiamo numeri, obiettivi e priorità della tua impresa.</p></div><div><span>03</span><h3>Azioni e percorso</h3><p>Definiamo i passi da affrontare con il tuo consulente.</p></div></div></div></section>
<section class="fp-section fp-access" aria-labelledby="fp-access-title"><div class="fp-container"><div class="fp-section-heading"><p class="fp-eyebrow">IL PUNTO DI ACCESSO GIUSTO</p><h2 id="fp-access-title">Uno spazio per ogni ruolo.</h2><p>Scegli da dove iniziare il tuo percorso con FinancePlus.</p></div><div class="fp-role-grid"><article class="fp-role-card"><span class="fp-role-icon">{icon('building')}</span><h3>Per la tua impresa</h3><p>Conosci i servizi, contatta il team e richiedi l’accesso alla tua area riservata.</p><a class="fp-text-link" href="/registrazione">Richiedi un account {icon('arrow')}</a></article><article class="fp-role-card"><span class="fp-role-icon">{icon('people')}</span><h3>Per i collaboratori</h3><p>Accedi allo spazio di lavoro con le funzioni e i clienti autorizzati per il tuo ruolo.</p><a class="fp-text-link" href="/login">Accedi allo spazio di lavoro {icon('arrow')}</a></article><article class="fp-role-card fp-role-app"><span class="fp-role-icon">{icon('phone')}</span><h3>FinancePlus anche in app</h3><p>Scopri LELE_K_PLUS, l’accesso mobile al mondo FinancePlus.</p><a class="fp-text-link" href="/lele-k-plus">Scopri LELE_K_PLUS {icon('arrow')}</a></article></div></div></section>
<section class="fp-section fp-cta-section"><div class="fp-container fp-cta"><div><p class="fp-eyebrow">IL PROSSIMO PASSO</p><h2>Parliamo della tua impresa.</h2><p>Raccontaci il progetto. Individuiamo insieme da dove partire.</p></div><a class="fp-button fp-button-copper" href="/contatti">Parla con noi {icon('arrow')}</a></div></section></div>'''


def platform_body() -> str:
    modules = (
        ("clienti", "building", "Cliente 360", "L’impresa al centro", "Un contesto unico per anagrafica, documenti e richieste. L’accesso alle informazioni dipende dal ruolo e dalle assegnazioni."),
        ("documenti", "document", "Documenti", "Dalla raccolta alla verifica", "Originali, categorie e stato di revisione: un documento acquisito deve ancora essere verificato prima di essere usato nell’analisi."),
        ("pratiche", "people", "Pratiche", "Ogni richiesta ha il suo percorso", "Obiettivo, stato e prossima attività aiutano a distinguere le singole richieste della stessa impresa."),
        ("analisi", "chart", "Analisi", "Dati prima dei risultati", "La lettura economica e finanziaria utilizza i moduli del sistema FinancePlus e richiede fonti e informazioni sufficienti."),
        ("report", "document", "Report", "Un risultato da leggere e condividere", "Anteprima, stampa ed esportazione degli elaborati disponibili, secondo i permessi dell’utente."),
        ("app", "phone", "LELE_K_PLUS", "Il punto di accesso mobile", "Sito, area riservata e app accompagnano lo stesso rapporto con FinancePlus. Scopri la pagina dedicata all’app."),
    )
    cards = "".join(f'<article class="fp-module" id="{anchor}"><span class="fp-area-icon">{icon(ico)}</span><p class="fp-eyebrow">{title}</p><h2>{subtitle}</h2><p>{text}</p><a class="fp-text-link" href="{"/lele-k-plus" if anchor == "app" else "/login"}">{"Scopri l’app" if anchor == "app" else "Accedi all’area riservata"} {icon("arrow")}</a></article>' for anchor,ico,title,subtitle,text in modules)
    return f'''<div class="fp-public"><section class="fp-page-intro"><div class="fp-container"><p class="fp-eyebrow">FINANCEPLUS PLATFORM</p><h1>Il tuo percorso,<br>in un unico contesto.</h1><p class="fp-lead">Documenti, richieste e informazioni dell’impresa accompagnano il lavoro del tuo consulente. Qui trovi le aree che compongono il percorso.</p><div class="fp-actions"><a class="fp-button fp-button-copper" href="/login">Accedi all’area riservata {icon('arrow')}</a><a class="fp-button fp-button-outline" href="/lele-k-plus">Scopri l’app</a></div></div></section><section class="fp-section"><div class="fp-container"><div class="fp-platform-note">{icon('shield')}<p>Le funzioni disponibili nell’area riservata dipendono dal tuo ruolo e dai servizi attivati. Il consulente ti aiuta a scegliere il percorso adatto.</p></div><div class="fp-module-grid">{cards}</div></div></section><section class="fp-section fp-cta-section"><div class="fp-container fp-cta"><div><h2>Vuoi capire da dove iniziare?</h2><p>Confrontati con il team sui bisogni della tua impresa.</p></div><a class="fp-button fp-button-copper" href="/contatti">Parla con noi {icon('arrow')}</a></div></section></div>'''


def services_body(services: Sequence[tuple[str, str, str]]) -> str:
    cards = "".join(f'<article class="fp-service-card"><span class="fp-service-index">0{i+1}</span><h2>{_e(title)}</h2><p>{_e(desc)}</p><a class="fp-text-link" href="/servizi/{SERVICE_SLUGS[i]}">Esplora il servizio {icon("arrow")}</a></article>' for i,(title,desc,_) in enumerate(services[:len(SERVICE_SLUGS)]))
    return f'''<div class="fp-public"><section class="fp-page-intro"><div class="fp-container"><p class="fp-eyebrow">SOLUZIONI PER LE IMPRESE</p><h1>Le tue priorità.<br>Il nostro punto di partenza.</h1><p class="fp-lead">Strategia, controllo e finanza d’impresa. Scegli l’area da approfondire o raccontaci il tuo progetto per orientare il percorso.</p></div></section><section class="fp-section"><div class="fp-container fp-service-grid">{cards}</div></section><section class="fp-section fp-cta-section"><div class="fp-container fp-cta"><div><h2>Troviamo insieme la direzione.</h2><p>Partiamo dalle esigenze della tua azienda.</p></div><a class="fp-button fp-button-copper" href="/contatti">Richiedi una consulenza {icon('arrow')}</a></div></section></div>'''


def service_body(slug: str, services: Sequence[tuple[str, str, str]]) -> tuple[str, str] | None:
    if slug not in SERVICE_SLUGS:
        return None
    index = SERVICE_SLUGS.index(slug)
    if index >= len(services):
        return None
    title, _, _ = services[index]
    heading, description, steps, outcome = SERVICE_DETAILS[index]
    items = "".join(f'<li><span>0{i+1}</span><p>{_e(step)}</p></li>' for i, step in enumerate(steps))
    body = f'''<div class="fp-public"><section class="fp-page-intro"><div class="fp-container"><a class="fp-back-link" href="/servizi">← Tutte le soluzioni</a><p class="fp-eyebrow">{_e(title)}</p><h1>{_e(heading)}</h1><p class="fp-lead">{_e(description)}</p><a class="fp-button fp-button-copper" href="/contatti?service={slug}">Parliamo del tuo progetto {icon('arrow')}</a></div></section><section class="fp-section"><div class="fp-container fp-method-grid"><div><p class="fp-eyebrow">IL PERCORSO</p><h2>Come lavoriamo insieme.</h2><p class="fp-lead">Concordiamo obiettivi e attività dopo aver compreso il contesto e le informazioni disponibili.</p></div><ol class="fp-service-steps">{items}</ol></div></section><section class="fp-section fp-cta-section"><div class="fp-container fp-cta"><div><p class="fp-eyebrow">IL RISULTATO ATTESO</p><h2>Un passo concreto per la tua impresa.</h2><p>{_e(outcome)}</p></div><a class="fp-button fp-button-copper" href="/contatti?service={slug}">Contattaci {icon('arrow')}</a></div></section></div>'''
    return title, body
