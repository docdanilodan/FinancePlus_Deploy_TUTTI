"""Pure, authorized-data-only views for the FinancePlus workspace.

The route/controller must fetch and authorize every record before calling a
view.  These functions never widen a scope, fetch data, persist records or
calculate a financial result.  A missing field stays explicitly unavailable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from portal_ui import badge, button, empty, esc, export_actions, filter_form, icon, panel, path_id, stat, table


FILTER_KEYS = ("q", "client", "collaborator", "referrer", "manager", "status")
TABS = (("sintesi", "Sintesi"), ("pratiche", "Pratiche"), ("documenti", "Documenti"),
        ("analisi", "Analisi"), ("attivita", "Attività"), ("report", "Report"))


def _records(value):
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, (list, tuple)) else []


def _text(value, fallback="—"):
    if value is None or value == "":
        return fallback
    if isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    return fallback


def _date(value):
    if not value:
        return "Non disponibile"
    try:
        dt = datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) and not isinstance(value, bool) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(ZoneInfo("Europe/Rome"))
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError, OverflowError, OSError):
        return _text(value)


def _schedule(value):
    if not value:
        return "Non disponibile"
    raw = str(value)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if "T" not in raw and " " not in raw:
            return dt.strftime("%d/%m/%Y")
        if dt.tzinfo is not None:
            return dt.astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y · %H:%M") + " (Roma)"
        return dt.strftime("%d/%m/%Y · %H:%M") + " (ora registrata)"
    except (ValueError, TypeError):
        return _text(value)


def _amount(value):
    """Format a canonical amount; missing/invalid numbers are never zeroed."""
    if value is None or value == "" or isinstance(value, bool):
        return "Non indicato"
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return "Non disponibile"
        return (f"€ {number:,.2f}").replace(",", "_").replace(".", ",").replace("_", ".")
    except (InvalidOperation, ValueError):
        return "Non disponibile"


def _name(client):
    return _text(client.get("name") or client.get("company"), "Azienda")


def _href(client_id, *, tab=None, practice=None):
    url = "/app/clienti/" + path_id(client_id)
    query = {}
    if tab:
        query["tab"] = tab
    if practice is not None:
        query["practice"] = str(practice)
    return url + ("?" + urlencode(query) if query else "")


def _mutating_actions(*, can_upload=False, can_create_client=False, can_create_practice=False, client_id=None):
    parts = []
    suffix = "?" + urlencode({"client": client_id}) if client_id is not None else ""
    if can_create_client:
        parts.append(button("Nuovo cliente", "/app/nuovo-cliente", "primary", "plus"))
    if can_create_practice:
        parts.append(button("Nuova pratica", "/app/nuova-pratica" + suffix, "primary", "plus"))
    if can_upload:
        parts.append(button("Carica documenti", "/app/carica-documenti" + suffix, symbol="file"))
    return '<div class="p-actions">' + "".join(parts) + '</div>' if parts else ""


def _choices(data):
    """Use explicit canonical assignments only; never infer roles from names."""
    if isinstance(data.get("filter_source"), Mapping):
        data = data["filter_source"]
    if isinstance(data.get("filter_choices"), Mapping):
        return data["filter_choices"]
    clients = _records(data.get("companies"))
    practices = _records(data.get("practices"))
    collaborators = {}
    managers = set()
    for practice in practices:
        for person in _records(practice.get("assigned_collaborators")):
            if person.get("id") is not None:
                collaborators[str(person["id"])] = _text(person.get("name"), str(person["id"]))
        if practice.get("manager_name"):
            managers.add(str(practice["manager_name"]))
    return {
        "client": [(str(c["id"]), _name(c)) for c in clients if c.get("id") is not None],
        "collaborator": sorted(collaborators.items(), key=lambda item: item[1].casefold()),
        "referrer": [],
        "manager": [(name, name) for name in sorted(managers)],
        "status": [(status, status) for status in sorted({str(p["status"]) for p in practices if p.get("status")})],
    }


def _filters(filters):
    return {key: _text(value, "") for key, value in (filters or {}).items() if key in FILTER_KEYS and value is not None}


def _filter_block(action, data, filters):
    choices = _choices(data)
    rendered = filter_form(action, _filters(filters), choices)
    source = data["filter_source"] if isinstance(data.get("filter_source"), Mapping) else data
    role_fields = source.get("role_fields_available")
    if isinstance(role_fields, (list, tuple, set)):
        available_roles = set(role_fields)
    elif role_fields is False:
        available_roles = set()
    else:
        available_roles = {key for key in ("collaborator", "referrer", "manager") if choices.get(key)}
    unavailable = []
    for key in ("collaborator", "referrer", "manager"):
        if key not in available_roles:
            unavailable.append(key)
            start = rendered.find(f'<select id="f-{key}"')
            end = rendered.find('</select>', start) if start >= 0 else -1
            if end >= 0:
                replacement = f'<select id="f-{key}" name="{key}" disabled aria-describedby="p-role-filters-note"><option value="">Non disponibile</option></select>'
                rendered = rendered[:start] + replacement + rendered[end + len('</select>'):]
    if unavailable:
        names = {"collaborator": "collaboratore", "referrer": "segnalatore", "manager": "gestore"}
        labels = [names[key] for key in unavailable]
        combined = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " e " + labels[-1]
        rendered += f'<p id="p-role-filters-note" class="p-print-note">{combined.capitalize()} {"saranno disponibili quando trasmessi" if len(labels) > 1 else "sarà disponibile quando trasmesso"} dal MASTER.</p>'
    return rendered


def _partial_notice(data):
    if data.get("complete", True):
        return ""
    return '<div class="p-notice p-notice-warning" role="status">' + icon("clock") + '<div><strong>Vista parziale</strong><p>Il servizio ha restituito solo una parte dei dati autorizzati. I conteggi si riferiscono alle righe caricate; l’esportazione completa non è disponibile in questa vista.</p></div></div>'


def _exports(base, data, filters, key):
    rows = _records(data.get(key))
    if not data.get("complete", True):
        return ""
    total = data.get("all_" + key + "_count", len(rows))
    if not isinstance(total, int) or total < len(rows):
        total = len(rows)
    return export_actions(base, _filters(filters), total, len(rows))


def _practice_title(practice):
    return _text(practice.get("title"), "Richiesta " + _text(practice.get("id"), ""))


def _missing_text(practice):
    missing = practice.get("missing_documents")
    if isinstance(missing, list):
        labels = [_text(item, "") for item in missing]
        return ", ".join(x for x in labels if x) or "Nessuna carenza indicata"
    if isinstance(missing, str) and missing.strip():
        return missing
    requests = _records(practice.get("document_requests"))
    if requests:
        return f"{len(requests)} richieste documentali"
    return "Non indicato"


def _company_rows(data, *, limit=None):
    clients = _records(data.get("companies"))
    practices = _records(data.get("practices"))
    if limit is not None:
        clients = clients[:limit]
    rows = []
    for company in clients:
        client_id = company.get("id")
        own = [p for p in practices if str(p.get("client_id")) == str(client_id)]
        label = f'<a href="{esc(_href(client_id))}">{esc(_name(company))}</a>'
        if company.get("vat"):
            label += f'<small>P.IVA {esc(company["vat"])}</small>'
        elif company.get("sector"):
            label += f'<small>{esc(company["sector"])}</small>'
        statuses = list(dict.fromkeys(_text(p.get("status"), "Non indicato") for p in own))
        status_html = " ".join(badge(status) for status in statuses[:3]) if statuses else '<span class="p-badge p-neutral">Nessuna richiesta caricata</span>'
        if len(statuses) > 3:
            status_html += f'<small>Altri {len(statuses) - 3} stati nella scheda</small>'
        next_actions = [_text(p.get("next_action"), "") for p in own if p.get("next_action")]
        next_html = esc(next_actions[0]) if next_actions else "Non indicata"
        if len(next_actions) > 1:
            next_html += f'<small>Altre {len(next_actions) - 1} azioni nelle pratiche</small>'
        count = f'<a href="{esc(_href(client_id, tab="pratiche"))}">{len(own)} richieste</a>'
        rows.append((label, count, status_html, next_html, button("Apri", _href(client_id), "quiet", "arrow")))
    return rows


def _practice_rows(items, *, show_company=True, selected_practice=None):
    rows = []
    for practice in _records(items):
        href = _href(practice.get("client_id"), tab="pratiche", practice=practice.get("id"))
        title = f'<a href="{esc(href)}">{esc(_practice_title(practice))}</a><small>ID {esc(practice.get("id"))}</small>'
        if selected_practice is not None and str(selected_practice) == str(practice.get("id")):
            title += badge("Selezionata", "neutral")
        row = []
        if show_company:
            row.append(f'<a href="{esc(_href(practice.get("client_id")))}">{esc(_text(practice.get("client_name"), "Azienda"))}</a>')
        row += [title, esc(_amount(practice.get("amount"))), badge(practice.get("status")), esc(_text(practice.get("manager_name"), "Non indicato")), esc(_missing_text(practice))]
        rows.append(row)
    return rows


def dashboard_view(data, filters=None, *, role="", can_upload=False, can_create_client=False, can_create_practice=False):
    restricted = str(role).casefold() in {"client", "cliente", "collaborator", "collaboratore"} or data.get("restricted") is True
    companies = _records(data.get("companies"))
    practices = _records(data.get("practices"))
    documents = _records(data.get("documents"))
    tasks = _records(data.get("tasks"))
    loaded_docs = bool(data.get("documents_loaded", False))
    loaded_tasks = bool(data.get("tasks_loaded", False))
    doc_value = len(documents) if loaded_docs else "—"
    task_value = len(tasks) if loaded_tasks else "—"
    stats_items = [
        stat("Clienti / Aziende", len(companies), "/app/clienti", "users", detail="Aziende nella vista autorizzata"),
        stat("Pratiche", len(practices), "/app/pratiche", "folder", "green", "Una richiesta per pratica"),
    ]
    if not restricted:
        doc_note = "Documenti caricati" if loaded_docs else (f"{len(documents)} ricevuti · vista parziale" if documents else "Apri l’archivio per consultarli")
        task_note = "Attività caricate" if loaded_tasks else (f"{len(tasks)} ricevute · vista parziale" if tasks else "Consulta l’agenda disponibile")
        stats_items += [stat("Documenti", doc_value, "/app/documenti", "file", "amber", doc_note), stat("Attività", task_value, "/app/agenda", "calendar", "blue", task_note)]
    stats = '<div class="p-stats' + (' p-stats-compact' if restricted else '') + '">' + "".join(stats_items) + '</div>'
    client_panel = panel("Clienti e aziende", table(("Azienda", "Richieste", "Stato", "Prossima azione", ""), _company_rows(data, limit=6), "Ultime aziende nella vista autorizzata"), button("Vedi tutti", "/app/clienti", "quiet", "arrow"), "Apri l’azienda per entrare nel Cliente 360.")
    activity = []
    for practice in practices:
        if practice.get("next_action"):
            activity.append(f'<li><div><strong>{esc(practice.get("next_action"))}</strong><small>{esc(practice.get("client_name") or _practice_title(practice))}</small></div>{button("Apri", _href(practice.get("client_id"), tab="pratiche", practice=practice.get("id")), "quiet", "arrow")}</li>')
    next_body = '<ul class="p-list">' + "".join(activity[:4]) + '</ul>' if activity else empty("Il prossimo passo", "Le prossime azioni compaiono qui quando sono disponibili nelle pratiche autorizzate.", button("Apri le pratiche", "/app/pratiche", "quiet"), "clock")
    quick = '<ul class="p-list"><li><div><strong>Documenti</strong><small>Originali, categorie e stato disponibile</small></div>' + button("Apri", "/app/documenti", "quiet", "arrow") + '</li><li><div><strong>Analisi e CR</strong><small>Consulta gli esiti disponibili dal MASTER</small></div>' + button("Apri", "/app/analisi", "quiet", "arrow") + '</li><li><div><strong>Report</strong><small>Anteprima, stampa e PDF</small></div>' + button("Apri", "/app/report", "quiet", "arrow") + '</li></ul>'
    if restricted:
        quick = '<ul class="p-list"><li><div><strong>Richieste e integrazioni</strong><small>Documenti richiesti e stato delle tue pratiche</small></div>' + button("Apri", "/app/pratiche", "quiet", "arrow") + '</li><li><div><strong>Elenco aziende</strong><small>Consulta e stampa l’elenco autorizzato</small></div>' + button("Apri", "/app/clienti", "quiet", "arrow") + '</li>'
        if can_upload:
            quick += '<li><div><strong>Carica un documento</strong><small>Acquisizione nel canale autorizzato</small></div>' + button("Apri", "/app/carica-documenti", "quiet", "arrow") + '</li>'
        quick += '</ul>'
    return _mutating_actions(can_upload=can_upload, can_create_client=can_create_client, can_create_practice=can_create_practice) + _partial_notice(data) + stats + '<div class="p-grid-main"><div>' + client_panel + '</div><div>' + panel("Da seguire", next_body) + panel("Accessi rapidi", quick) + '</div></div>'


def companies_view(data, filters=None, *, role="", can_upload=False, can_create_client=False, can_create_practice=False):
    body = _filter_block("/app/clienti", data, filters)
    body += _exports("/app/clienti", data, filters, "companies")
    body += table(("Azienda", "Richieste", "Stato delle pratiche", "Prossima azione", ""), _company_rows(data), f'{len(_records(data.get("companies")))} aziende · una riga per azienda')
    return _mutating_actions(can_upload=can_upload, can_create_client=can_create_client, can_create_practice=can_create_practice) + _partial_notice(data) + panel("Elenco aziende", body, subtitle="Clienti, richieste e prossime azioni nel tuo perimetro di accesso.")


def practices_view(data, filters=None, *, role="", can_upload=False, can_create_client=False, can_create_practice=False):
    body = _filter_block("/app/pratiche", data, filters)
    body += _exports("/app/pratiche", data, filters, "practices")
    body += table(("Azienda", "Pratica", "Importo richiesto", "Stato", "Gestore", "Documenti richiesti"), _practice_rows(data.get("practices")), f'{len(_records(data.get("practices")))} pratiche · una riga per richiesta')
    return _mutating_actions(can_upload=can_upload, can_create_client=can_create_client, can_create_practice=can_create_practice) + _partial_notice(data) + panel("Richieste e pratiche", body, subtitle="Importo, stato e assegnazioni appartengono alla singola richiesta.")


def _document_rows(items, *, show_company=True):
    rows = []
    for doc in _records(items):
        doc_id = doc.get("id")
        href = "/app/documenti/" + path_id(doc_id) + "/anteprima"
        title = _text(doc.get("title") or doc.get("filename"), "Documento")
        row = [f'<a href="{esc(href)}">{icon("file")} {esc(title)}</a>']
        if show_company:
            row.append(f'<a href="{esc(_href(doc.get("client_id")))}">{esc(_text(doc.get("client_name"), "Azienda " + _text(doc.get("client_id"), "")))}</a>')
        # Category is the canonical value, never inferred from the filename.
        row += [esc(_text(doc.get("category"), "Non classificato")), esc(_date(doc.get("date") or doc.get("document_date"))), badge(doc.get("status") or "Stato non disponibile", "neutral" if not doc.get("status") else ""), button("Anteprima", href, "quiet", "arrow")]
        rows.append(row)
    return rows


def documents_view(items, *, client_id=None, loaded=True, can_upload=False, role="", **kwargs):
    action = _mutating_actions(can_upload=can_upload, client_id=client_id)
    records = _records(items)
    if not loaded and not records:
        return action + panel("Documenti", empty("Documenti da consultare", "Apri un’azienda autorizzata per consultare i documenti disponibili nel suo fascicolo.", button("Vai ai clienti", "/app/clienti", "quiet", "users"), "file"))
    body = '<p class="p-print-note">Un documento acquisito non equivale a un documento validato. Le categorie e gli stati riportati provengono dal fascicolo autorizzato.</p>'
    if not loaded:
        body = '<div class="p-notice p-notice-warning" role="status"><div><strong>Elenco documenti parziale</strong><p>Le righe ricevute sono consultabili. Questa vista non copre l’intero archivio autorizzato.</p></div></div>' + body
    headers = ["Documento"] + (["Azienda"] if client_id is None else []) + ["Categoria", "Data documento", "Stato revisione", ""]
    body += table(headers, _document_rows(records, show_company=client_id is None), f"{len(records)} documenti nella vista" + (" · elenco parziale" if not loaded else ""), "Nessun documento disponibile nella vista autorizzata.")
    return action + panel("Archivio documenti", body)


def _kv(entries):
    return '<dl class="p-kv">' + "".join(f'<div><dt>{esc(label)}</dt><dd>{value}</dd></div>' for label, value in entries) + '</dl>'


def _practices_for_bundle(bundle):
    client = bundle.get("client") if isinstance(bundle.get("client"), Mapping) else {}
    result = []
    for original in _records(bundle.get("requests")):
        practice = dict(original)
        practice.setdefault("client_id", client.get("id"))
        practice.setdefault("client_name", _name(client))
        result.append(practice)
    return result


def _practice_detail(practice):
    requests = _records(practice.get("document_requests"))
    rows = [(esc(_text(item.get("description") or item.get("title"), "Richiesta documentale")), badge(item.get("status")), esc(_date(item.get("requested_at") or item.get("date")))) for item in requests]
    body = _kv((("Importo richiesto", esc(_amount(practice.get("amount")))), ("Finalità", esc(_text(practice.get("purpose"), "Non indicata"))), ("Istituto", esc(_text(practice.get("institution"), "Non indicato"))), ("Stato", badge(practice.get("status"))), ("Gestore", esc(_text(practice.get("manager_name"), "Non indicato"))), ("Prossima azione", esc(_text(practice.get("next_action"), "Non indicata")))))
    if practice.get("assigned_collaborators"):
        names = [_text(person.get("name"), "Collaboratore " + _text(person.get("id"), "")) for person in _records(practice["assigned_collaborators"])]
        body += '<div class="p-details"><strong>Collaboratori assegnati</strong><p>' + esc(", ".join(names)) + '</p></div>'
    body += '<div class="p-details"><strong>Documenti mancanti / integrazioni</strong><p>' + esc(_missing_text(practice)) + '</p></div>'
    if requests:
        body += table(("Richiesta documentale", "Stato", "Data"), rows, "Integrazioni associate a questa pratica")
    return panel(_practice_title(practice), body, subtitle="Pratica " + _text(practice.get("id"), ""))


def _analysis_body(bundle):
    analysis = bundle.get("analysis")
    if analysis is None:
        return empty("Analisi non disponibile", "Nel fascicolo autorizzato non è presente un esito di analisi consultabile. Il caricamento di documenti non genera automaticamente punteggi o valutazioni.", symbol="chart")
    if not isinstance(analysis, Mapping):
        return empty("Esito da verificare", "Il servizio ha restituito un’analisi in un formato non interpretabile da questa vista. Consulta il fascicolo nel MASTER.", symbol="chart")
    known_fields = (("status", "Stato"), ("period", "Periodo"), ("year", "Anno"), ("version", "Versione"), ("source", "Fonte"), ("updated_at", "Aggiornamento"), ("generated_at", "Generata il"))
    values = []
    for key, label in known_fields:
        if key in analysis and _text(analysis[key], ""):
            value = _date(analysis[key]) if key.endswith("_at") else _text(analysis[key])
            values.append((label, esc(value)))
    result = '<div class="p-notice" role="status">' + icon("chart") + '<div><strong>Esito presente nel fascicolo</strong><p>La vista riporta informazioni trasmesse dal MASTER. Non esegue nuove elaborazioni finanziarie e non attribuisce una delibera bancaria.</p></div></div>'
    if values:
        result += _kv(values)
    summary = next((analysis[key] for key in ("summary", "synthesis", "conclusion", "description") if isinstance(analysis.get(key), str) and analysis[key].strip()), None)
    if summary:
        result += '<div class="p-details"><strong>Sintesi del MASTER</strong><p>' + esc(summary) + '</p></div>'
    if not values and not summary:
        result += '<p class="p-print-note">L’esito è disponibile, ma non include campi di sintesi compatibili con questa vista. I valori finanziari non vengono ricostruiti o sostituiti.</p>'
    result += '<details class="p-details"><summary>Consulta tutti i campi originali dell’analisi</summary><p class="p-print-note">Nomi e valori trasmessi dal MASTER, con la loro struttura originale.</p><pre class="p-source-data">' + esc(json.dumps(analysis, ensure_ascii=False, indent=2, default=str)) + '</pre></details>'
    return result


def client_view(bundle, selected_tab="sintesi", base_path=None, *, selected_practice=None, role="", can_upload=False, can_create_practice=False, can_prepare_analysis=False, **kwargs):
    client = bundle.get("client") if isinstance(bundle.get("client"), Mapping) else {}
    client_id = client.get("id")
    base = base_path or _href(client_id)
    restricted = bundle.get("restricted") is True
    visible_tabs = TABS[:2] if restricted else TABS
    selected_tab = selected_tab if selected_tab in {key for key, _ in visible_tabs} else "sintesi"
    selected_practice = selected_practice if selected_practice is not None else bundle.get("selected_practice")
    practices = _practices_for_bundle(bundle)
    documents_loaded = bool(bundle.get("documents_loaded", "documents" in bundle))
    tasks_loaded = bool(bundle.get("tasks_loaded", "tasks" in bundle))
    name = _name(client)
    initials = "".join(word[0] for word in name.split()[:2]).upper()
    heading = f'<div class="p-breadcrumb"><a href="/app/clienti">Clienti</a> / {esc(name)}</div><div class="p-profile"><span class="p-company-mark" aria-hidden="true">{esc(initials)}</span><div><h2>{esc(name)}</h2><p>' + esc("P.IVA " + str(client["vat"]) if client.get("vat") else "Identificativo " + _text(client_id, "non disponibile")) + (" · " + esc(client["sector"]) if client.get("sector") else "") + '</p></div></div>'
    tab_links = []
    for key, label in visible_tabs:
        query = {"tab": key}
        if selected_practice is not None:
            query["practice"] = str(selected_practice)
        tab_links.append(f'<a href="{esc(base + "?" + urlencode(query))}"' + (' aria-current="page"' if key == selected_tab else '') + f'>{label}</a>')
    nav = '<nav class="p-tabs" aria-label="Sezioni Cliente 360">' + "".join(tab_links) + '</nav>'
    action = _mutating_actions(can_upload=can_upload, can_create_practice=can_create_practice, client_id=client_id)
    action += '<div class="p-actions">' + button("Attività e richieste documentali", base + "/attivita", "secondary", "calendar") + '</div>'
    if can_prepare_analysis and role == "admin" and not restricted:
        action += '<div class="p-actions">' + button("Prepara fascicolo di analisi", base + "/prepara-analisi", "secondary", "chart") + '</div>'
    if bundle.get("requests_loaded") is False:
        action += '<div class="p-notice p-notice-warning" role="status"><div><strong>Pratiche: vista parziale</strong><p>Il servizio ha raggiunto il limite di 100 richieste per fascicolo. Le righe ricevute sono consultabili; il numero non rappresenta il totale completo.</p></div></div>'
    if restricted:
        action += '<p class="p-print-note">Questo spazio mostra le richieste e le integrazioni documentali condivise con il tuo account.</p>'
    content = ""
    if selected_tab == "pratiche":
        content = panel("Richieste dell’azienda", table(("Pratica", "Importo richiesto", "Stato", "Gestore", "Documenti richiesti"), _practice_rows(practices, show_company=False, selected_practice=selected_practice), f"{len(practices)} richieste disponibili"))
        selected = next((p for p in practices if str(p.get("id")) == str(selected_practice)), None)
        if selected is not None:
            content += _practice_detail(selected)
        elif selected_practice is not None:
            content += panel("Pratica selezionata", empty("Pratica non disponibile", "La richiesta selezionata non è presente nel fascicolo autorizzato.", symbol="folder"))
    elif selected_tab == "documenti":
        content = documents_view(bundle.get("documents"), client_id=client_id, loaded=documents_loaded, can_upload=False)
    elif selected_tab == "analisi":
        content = panel("Analisi e valutazioni", _analysis_body(bundle))
    elif selected_tab == "attivita":
        content = agenda_view(bundle.get("tasks"), loaded=tasks_loaded, client_id=client_id)
        notes = _records(bundle.get("notes"))
        if notes:
            note_list = '<ul class="p-list">' + "".join('<li><div><strong>' + esc(_text(n.get("body"), "Nota")) + '</strong><small>' + esc(_date(n.get("created_at"))) + '</small></div></li>' for n in notes) + '</ul>'
            content += panel("Note del fascicolo", note_list)
    elif selected_tab == "report":
        content = reports_view([bundle], client_id=client_id)
    else:
        summary_stats = '<div class="p-stats">' + stat("Pratiche", len(practices), base + "?tab=pratiche", "folder", detail="Richieste dell’azienda") + stat("Documenti", len(_records(bundle.get("documents"))) if documents_loaded else "—", base + "?tab=documenti", "file", "amber", "Nel fascicolo disponibile" if documents_loaded else "Accesso limitato") + stat("Attività", len(_records(bundle.get("tasks"))) if tasks_loaded else "—", base + "?tab=attivita", "calendar", "blue", "Nel fascicolo disponibile" if tasks_loaded else "Accesso limitato") + stat("Analisi", "Presente" if bundle.get("analysis") is not None else "—", base + "?tab=analisi", "chart", "green", "Esito dal MASTER" if bundle.get("analysis") is not None else "Nessun esito consultabile") + '</div>'
        identity = _kv((("Ragione sociale", esc(name)), ("Partita IVA", esc(_text(client.get("vat"), "Non disponibile"))), ("Settore", esc(_text(client.get("sector"), "Non disponibile"))), ("Lettura fascicolo", esc(_date(bundle.get("read_at"))))))
        if restricted:
            summary_stats = '<div class="p-stats p-stats-compact">' + stat("Pratiche autorizzate", len(practices), base + "?tab=pratiche", "folder", detail="Richieste condivise con il tuo account") + '</div>'
            identity = _kv((("Ragione sociale", esc(name)), ("Identificativo azienda", esc(_text(client_id, "Non disponibile")))))
        practice_panel = panel("Le richieste dell’azienda", table(("Pratica", "Importo richiesto", "Stato", "Gestore", "Documenti richiesti"), _practice_rows(practices, show_company=False), "Ogni riga mantiene la propria richiesta"), button("Vedi pratiche", base + "?tab=pratiche", "quiet", "arrow"))
        content = summary_stats + panel("Anagrafica", identity) + practice_panel
    return heading + action + nav + content


def agenda_view(items, *, loaded=True, client_id=None, **kwargs):
    records = _records(items)
    if not loaded and not records:
        return panel("Agenda", empty("Attività da consultare", "Le attività si consultano nel fascicolo di ciascuna azienda autorizzata.", button("Vai ai clienti", "/app/clienti", "quiet", "users"), "calendar"))
    rows = []
    for task in records:
        row = [esc(_text(task.get("title"), "Attività"))]
        if client_id is None:
            row.append(f'<a href="{esc(_href(task.get("client_id"), tab="attivita"))}">{esc(_text(task.get("client_name"), "Azienda " + _text(task.get("client_id"), "")))}</a>')
        row += [esc(_schedule(task.get("due_date"))), badge(task.get("status"))]
        rows.append(row)
    headers = ["Attività"] + (["Azienda"] if client_id is None else []) + ["Scadenza", "Stato"]
    partial = '<div class="p-notice p-notice-warning" role="status"><div><strong>Elenco attività parziale</strong><p>Sono mostrate le attività ricevute dal servizio; la vista non copre l’intera agenda.</p></div></div>' if not loaded else ""
    return panel("Agenda e attività", partial + table(headers, rows, "Attività disponibili nel fascicolo" + (" · elenco parziale" if not loaded else ""), "Nessuna attività disponibile nella vista autorizzata."), subtitle="Le scadenze riportate sono quelle registrate nel MASTER.")


def analytics_view(bundles, *, loaded=True, **kwargs):
    if not loaded:
        return panel("Analisi e CR", empty("Consulta le analisi del fascicolo", "Apri un’azienda per leggere gli esiti disponibili nel tuo perimetro.", button("Vai ai clienti", "/app/clienti", "quiet", "users"), "chart"))
    rows = []
    for bundle in _records(bundles):
        client = bundle.get("client") if isinstance(bundle.get("client"), Mapping) else {}
        analysis = bundle.get("analysis")
        rows.append((f'<a href="{esc(_href(client.get("id"), tab="analisi"))}">{esc(_name(client))}</a>', badge("Esito disponibile" if analysis is not None else "Non disponibile", "blue" if analysis is not None else "neutral"), esc(_date(analysis.get("updated_at") or analysis.get("generated_at"))) if isinstance(analysis, Mapping) else "—", button("Apri analisi", _href(client.get("id"), tab="analisi"), "quiet", "arrow")))
    return panel("Analisi disponibili", table(("Azienda", "Analisi", "Data esito", ""), rows, "Esiti trasmessi dal MASTER"), subtitle="I dati mancanti restano espliciti. Questa vista non genera score, rating o delibere.")


def reports_view(bundles, *, client_id=None, loaded=True, **kwargs):
    if not loaded:
        return panel("Report", empty("Report da consultare", "Apri il Cliente 360 per verificare gli elaborati disponibili nel fascicolo autorizzato.", button("Vai ai clienti", "/app/clienti", "quiet", "users"), "file"))
    rows = []
    for bundle in _records(bundles):
        client = bundle.get("client") if isinstance(bundle.get("client"), Mapping) else {}
        cid = client.get("id", client_id)
        if bundle.get("analysis") is None:
            continue
        href = "/app/report/" + path_id(cid)
        actions = '<div class="p-actions">' + button("Anteprima", href + "/anteprima", symbol="file") + button("Scarica PDF", href + "/pdf", symbol="download") + '</div>'
        rows.append((esc("Riepilogo fascicolo · " + _name(client)), badge("Esito disponibile", "blue"), actions))
    body = table(("Elaborato", "Disponibilità", "Azioni"), rows, "Elaborati relativi ai fascicoli consultabili", "Nessun elaborato disponibile nella vista autorizzata.")
    body += '<p class="p-print-note">Ogni anteprima consente la stampa e il download. La scelta della cartella dipende dal browser e dalle impostazioni del dispositivo.</p>'
    return panel("Report e PDF", body)


def finance_view(items=None, *, loaded=False, **kwargs):
    # No institution compatibility is reconstructed from a practice title or
    # invented from static platform rankings. Controller must provide verified
    # canonical records if this capability becomes available.
    records = _records(items) if loaded else []
    if not records:
        return panel("Finanziatori", empty("Valutazioni da consultare nel MASTER", "Nel collegamento attuale non sono disponibili valutazioni strutturate dei finanziatori. La scheda della pratica riporta l’istituto quando registrato.", button("Apri le pratiche", "/app/pratiche", "quiet", "folder"), "bank"))
    rows = [(esc(_text(item.get("name"), "Non indicato")), esc(_text(item.get("product"), "Non indicato")), badge(item.get("status")), esc(_text(item.get("source"), "Non indicata"))) for item in records]
    return panel("Finanziatori dal MASTER", table(("Finanziatore", "Prodotto", "Stato", "Fonte"), rows, "Informazioni ricevute dal sistema autorevole"))
