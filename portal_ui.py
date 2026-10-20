"""Presentation helpers for the FinancePlus workspace. No business calculations."""
from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import quote, urlencode

RELEASE = "FinancePlus Web 4.1.0"
NAVIGATION = [
    ("/app", "home", "Panoramica"),
    ("/app/clienti", "users", "Clienti"),
    ("/app/pratiche", "folder", "Pratiche"),
    ("/app/documenti", "file", "Documenti"),
    ("/app/analisi", "chart", "Analisi e CR"),
    ("/app/finanziatori", "bank", "Finanziatori"),
    ("/app/report", "file", "Report"),
    ("/app/agenda", "calendar", "Agenda"),
]
ROLE_NAMES = {"admin": "Amministratore", "ADMIN": "Amministratore", "professional": "Professionista", "collaborator": "Collaboratore", "COLLABORATORE": "Collaboratore", "client": "Cliente", "CLIENTE": "Cliente", "SEGNALATORE": "Segnalatore", "GESTORE": "Gestore"}


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def path_id(value):
    return quote(str(value), safe="")


def icon(name):
    paths = {
        "home": '<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3z"/>',
        "users": '<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6m3 11v-3a6 6 0 0 0-2-4"/>',
        "folder": '<path d="M3 5h6l3 3h9v12H3z"/>',
        "file": '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8m-8 4h6"/>',
        "chart": '<path d="M4 3v18h17M9 16v-4m5 4V7m5 9V4"/>',
        "bank": '<path d="m3 8 9-5 9 5H3Zm2 3v7m7-7v7m7-7v7M3 21h18"/>',
        "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18m-13 5h3"/>',
        "settings": '<path d="M12 3v3m0 12v3M3 12h3m12 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/><circle cx="12" cy="12" r="5"/>',
        "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
        "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
        "print": '<path d="M6 8V3h12v5M6 17H3V9h18v8h-3M6 14h12v7H6z"/>',
        "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
        "plus": '<path d="M12 4v16M4 12h16"/>',
        "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
        "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/>',
    }
    return '<svg class="p-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths.get(name, paths["file"]) + '</svg>'


def badge(text, kind=""):
    if not kind:
        s = str(text).casefold()
        kind = "amber" if any(w in s for w in ("mancant", "verific", "attesa", "integra", "pending")) else "green" if any(w in s for w in ("complet", "validat", "approvat", "conclus")) else "blue"
    return f'<span class="p-badge p-{esc(kind)}">{esc(text or "Non indicato")}</span>'


def button(label, href, kind="secondary", symbol=None):
    return f'<a class="p-button p-{esc(kind)}" href="{esc(href)}">{icon(symbol) if symbol else ""}{esc(label)}</a>'


def notice(title, text, kind="info", action=""):
    return f'<div class="p-notice p-notice-{esc(kind)}" role="status"><div>{icon("shield" if kind == "info" else "clock")}</div><div><strong>{esc(title)}</strong><p>{esc(text)}</p>{action}</div></div>'


def empty(title, text, action="", symbol="folder"):
    return f'<div class="p-empty"><span class="p-empty-icon">{icon(symbol)}</span><h2>{esc(title)}</h2><p>{esc(text)}</p>{action}</div>'


def panel(title, body, action="", subtitle="", extra_class=""):
    return f'<section class="p-panel {esc(extra_class)}"><div class="p-panel-head"><div><h2>{esc(title)}</h2>{f"<p>{esc(subtitle)}</p>" if subtitle else ""}</div>{action}</div>{body}</section>'


def table(headers, rows, caption="", empty_message="Nessun risultato per i filtri selezionati."):
    columns = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = "".join('<tr>' + "".join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows)
    if not body:
        body = f'<tr><td colspan="{len(headers)}" class="p-table-empty">{esc(empty_message)}</td></tr>'
    return f'<div class="p-table-scroll" tabindex="0" role="region" aria-label="{esc(caption or "Tabella risultati")}"><table class="p-table">{f"<caption>{esc(caption)}</caption>" if caption else ""}<thead><tr>{columns}</tr></thead><tbody>{body}</tbody></table></div>'


def stat(label, value, href, symbol="users", tone="blue", detail=""):
    return f'<a class="p-stat" href="{esc(href)}"><span class="p-stat-icon p-{esc(tone)}">{icon(symbol)}</span><span><span class="p-stat-label">{esc(label)}</span><strong>{esc(value)}</strong>{f"<small>{esc(detail)}</small>" if detail else ""}</span><span class="p-stat-arrow">{icon("arrow")}</span></a>'


def shell(user, title, subtitle, content, active="/app", source_label="", csrf="", public_admin=False):
    name = getattr(user, "display_name", "") or getattr(user, "email", "") or "Utente"
    role = getattr(user, "role", "")
    role_label = ROLE_NAMES.get(role, role or "Utente")
    initials = "".join(word[0] for word in name.replace("@", " ").split()[:2]).upper()
    nav = list(NAVIGATION)
    if str(role).casefold() in {"client", "cliente", "collaborator", "collaboratore"}:
        allowed = {"/app", "/app/clienti", "/app/pratiche"}
        principal = getattr(user, "principal", {})
        if isinstance(principal, dict) and principal.get("can_upload") is True:
            allowed.add("/app/documenti")
        nav = [item for item in nav if item[0] in allowed]
    if public_admin:
        nav += [("/app/richieste-sito", "users", "Richieste dal sito"), ("/app/gestione-sito", "settings", "Gestione sito")]
    nav += [("/app/impostazioni", "shield", "Collegamenti")]
    links = "".join(f'<a href="{href}" class="{"is-active" if active == href else ""}" {"aria-current=page" if active == href else ""}>{icon(ico)}<span>{label}</span></a>' for href, ico, label in nav)
    return f'''<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{esc(title)} | FinancePlus</title><link rel="icon" href="/static/logo.png"><link rel="stylesheet" href="/static/portal.css"><script src="/static/portal.js" defer></script></head>
<body class="p-body"><a class="p-skip" href="#contenuto">Vai al contenuto</a><div class="p-layout"><aside class="p-sidebar"><a class="p-brand" href="/app"><img src="/static/logo.png" alt="" width="40" height="40"><span>FinancePlus<span class="p-brand-tech">.tech</span><small>AREA OPERATIVA</small></span></a><div class="p-role">{icon("shield")}<span>{esc(role_label)}</span></div><button class="p-menu-toggle" aria-controls="menu-operativo" aria-expanded="true" type="button">Menu operativo</button><nav id="menu-operativo" class="p-navigation" aria-label="Navigazione operativa">{links}</nav><div class="p-sidebar-foot"><a href="/">Visita il sito {icon("arrow")}</a><small>{RELEASE}</small></div></aside>
<div class="p-main"><header class="p-topbar"><form class="p-search" action="/app/clienti" method="get" role="search"><label class="p-sr-only" for="ricerca-globale">Cerca un'azienda</label>{icon("search")}<input id="ricerca-globale" name="q" type="search" placeholder="Cerca azienda o partita IVA" maxlength="120"><button type="submit">Cerca</button></form><div class="p-user"><span class="p-avatar" aria-hidden="true">{esc(initials)}</span><span><strong>{esc(name)}</strong><small>{esc(role_label)}</small></span><form action="/logout" method="post"><input type="hidden" name="csrf_token" value="{esc(csrf)}"><button type="submit" class="p-signout">Esci</button></form></div></header>
<main id="contenuto" class="p-content"><div class="p-page-heading"><div><div class="p-eyebrow">IL TUO SPAZIO FINANCEPLUS</div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div></div>{content}<footer class="p-workspace-footer"><span>{esc(source_label)}</span><span>{RELEASE}</span></footer></main></div></div></body></html>'''


def filter_form(action, filters, choices):
    labels = [("client", "Cliente"), ("collaborator", "Collaboratore"), ("referrer", "Segnalatore"), ("manager", "Gestore"), ("status", "Stato")]
    fields = f'<div class="p-field p-query"><label for="f-q">Ricerca</label><input id="f-q" name="q" type="search" maxlength="120" value="{esc(filters.get("q", ""))}" placeholder="Nome, partita IVA, richiesta"></div>'
    for key, label in labels:
        options = '<option value="">Tutti</option>' + "".join(f'<option value="{esc(value)}" {"selected" if str(filters.get(key, "")) == str(value) else ""}>{esc(text)}</option>' for value, text in choices.get(key, []))
        fields += f'<div class="p-field"><label for="f-{key}">{label}</label><select id="f-{key}" name="{key}">{options}</select></div>'
    return f'<form class="p-filters" method="get" action="{esc(action)}">{fields}<div class="p-filter-actions"><button class="p-button p-primary" type="submit">Applica filtri</button><a href="{esc(action)}" class="p-button p-quiet">Azzera</a></div></form>'


def export_actions(base, filters, total, filtered):
    query = {k: v for k, v in filters.items() if v}
    query["scope"] = "filtered"
    filtered_url = base + "/stampa?" + urlencode(query)
    full_url = base + "/stampa?scope=all"
    return f'<div class="p-export-actions">{button(f"Vista filtrata ({filtered})", filtered_url, symbol="print")}{button(f"Elenco completo ({total})", full_url, symbol="download")}</div>'
