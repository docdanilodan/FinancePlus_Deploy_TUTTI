"""Owner-only preparation of a MASTER dossier using the existing preflight API.

The canonical SPECIAL ONE endpoints only read saved data and verify document
membership.  This adapter does not execute analyses, calculate scores, persist
financial decisions or send messages.  A successful preflight is deliberately
presented as DOCUMENTS_VERIFIED with new_analysis:false.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from master_gateway import GatewayError
from portal_data import positive_id
from portal_ui import badge, button, empty, esc, notice, panel, table


SECTIONS = {
    "preistruttoria": "Preistruttoria",
    "bilanci": "Bilanci",
    "centrale_rischi": "Centrale Rischi",
    "rating_mcc": "Rating MCC",
    "dscr": "DSCR",
    "swot": "SWOT",
    "finanziatori": "Finanziatori",
    "dossier": "Dossier",
}
MAX_DOCUMENTS = 150
MAX_SELECTION = 80
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_FORM_BYTES = 16_384


def _canonical_integer(value):
    """Accept integer/string bigint IDs without bool, float or exponent coercion."""
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9][0-9]{0,19})", value):
        return int(value)
    return None


def _contract_error():
    return GatewayError(
        502, "SPECIAL_ONE_CONTRACT_INVALID",
        "Il fascicolo ricevuto non rispetta il contratto della preparazione. Riapri la scheda quando il servizio sarà disponibile.",
    )


def validated_bundle(response, client_id):
    """Validate the read scope and preserve only records from the requested client."""
    if not isinstance(response, dict):
        raise _contract_error()
    client = response.get("client")
    documents = response.get("documents")
    capabilities = response.get("capabilities")
    if (
        not isinstance(client, dict)
        or _canonical_integer(client.get("id")) != client_id
        or not isinstance(documents, list)
        or len(documents) > MAX_DOCUMENTS
        or not isinstance(capabilities, dict)
        or capabilities.get("new_analysis") is not False
        or capabilities.get("saved_analysis") is not True
        or "analysis" not in response
    ):
        raise _contract_error()
    normalized, seen = [], set()
    for document in documents:
        if not isinstance(document, dict):
            raise _contract_error()
        document_id = _canonical_integer(document.get("id"))
        if (
            document_id is None
            or document_id in seen
            or _canonical_integer(document.get("client_id")) != client_id
        ):
            raise _contract_error()
        seen.add(document_id)
        normalized.append({**document, "id": document_id, "client_id": client_id})
    return {
        "client": {**client, "id": client_id},
        "documents": normalized,
        "analysis": response["analysis"],
        "capabilities": dict(capabilities),
    }


async def _form(request):
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Formato del modulo non supportato.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FORM_BYTES:
            raise HTTPException(413, "Il modulo supera la dimensione consentita.")
    try:
        fields = parse_qs(
            body.decode("utf-8"), keep_blank_values=True, strict_parsing=True,
            max_num_fields=96, errors="strict",
        )
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Modulo non valido.") from None
    if set(fields) - {"csrf_token", "confirmed", "document_ids", "sections"}:
        raise HTTPException(400, "Il modulo contiene campi non previsti.")
    if any(len(fields.get(name, [])) > 1 for name in ("csrf_token", "confirmed")):
        raise HTTPException(400, "Il modulo contiene campi di conferma duplicati.")
    return fields


def normalize_selection(form, client_id):
    """Mirror the canonical preflight selection, without financial calculations."""
    if form.get("confirmed") != ["yes"]:
        raise HTTPException(422, "Conferma i documenti e le sezioni da verificare.")
    raw_ids = form.get("document_ids", [])
    if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= MAX_SELECTION:
        raise HTTPException(422, "Seleziona da 1 a 80 documenti univoci del cliente.")
    document_ids = []
    for value in raw_ids:
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", value):
            raise HTTPException(422, "Uno degli identificativi dei documenti non è valido per questa verifica.")
        document_id = int(value)
        if document_id > MAX_SAFE_INTEGER:
            raise HTTPException(422, "Uno degli identificativi dei documenti supera il limite del servizio.")
        document_ids.append(document_id)
    if len(set(document_ids)) != len(document_ids):
        raise HTTPException(422, "Ogni documento può essere selezionato una sola volta.")
    sections = form.get("sections", [])
    if (
        not isinstance(sections, list)
        or not 1 <= len(sections) <= len(SECTIONS)
        or any(not isinstance(section, str) or section not in SECTIONS for section in sections)
        or len(set(sections)) != len(sections)
    ):
        raise HTTPException(422, "Seleziona da 1 a 8 sezioni disponibili, senza duplicati.")
    return {
        "client_id": positive_id(client_id), "document_ids": document_ids,
        "sections": list(sections), "confirmed": True,
    }


def validated_preflight(response, selection):
    """Only a matching canonical result can be displayed as verified."""
    def invalid():
        return GatewayError(
            502, "PREFLIGHT_UNVERIFIED",
            "Il risultato ricevuto non permette di confermare la verifica della selezione. Riapri il fascicolo e controlla i dati disponibili.",
        )

    if not isinstance(response, dict):
        raise invalid()
    documents = response.get("selected_documents")
    if (
        response.get("status") != "DOCUMENTS_VERIFIED"
        or response.get("new_analysis") is not False
        or _canonical_integer(response.get("client_id")) != selection["client_id"]
        or response.get("sections") != selection["sections"]
        or not isinstance(documents, list)
        or len(documents) != len(selection["document_ids"])
    ):
        raise invalid()
    normalized, seen = [], set()
    for document in documents:
        if not isinstance(document, dict):
            raise invalid()
        document_id = _canonical_integer(document.get("id"))
        if (
            document_id not in selection["document_ids"]
            or document_id in seen
            or ("client_id" in document and _canonical_integer(document["client_id"]) != selection["client_id"])
        ):
            raise invalid()
        seen.add(document_id)
        normalized.append({**document, "id": document_id})
    if seen != set(selection["document_ids"]):
        raise invalid()
    return {**response, "selected_documents": normalized}


def _saved_data(bundle):
    client_id = bundle["client"]["id"]
    if bundle["analysis"] is None:
        return panel(
            "Analisi già salvate",
            empty("Nessuna analisi salvata disponibile", "Il MASTER non restituisce un’analisi salvata per questa azienda.", symbol="chart"),
        )
    return panel(
        "Analisi già salvate",
        '<p class="p-print-note">Il fascicolo contiene dati di analisi già salvati e sincronizzati dal MASTER. Puoi consultarli nella scheda azienda.</p>'
        + '<div class="p-actions">' + button("Consulta l’analisi salvata", f"/app/clienti/{client_id}?tab=analisi", symbol="chart") + '</div>',
        subtitle="La verifica della selezione non aggiorna questi dati.",
    )


def _client_heading(bundle):
    client = bundle["client"]
    fields = (
        ("Azienda", client.get("name") or "Nome non disponibile"),
        ("Partita IVA", client.get("vat") or "Non disponibile"),
        ("Settore", client.get("sector") or "Non disponibile"),
        ("Fonte", bundle["capabilities"].get("source") or "Dati sincronizzati dal MASTER"),
    )
    detail = '<dl class="p-kv">' + ''.join(f'<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>' for label, value in fields) + '</dl>'
    return panel("Fascicolo dell’azienda", detail)


def _selection_page(bundle, csrf_field):
    client_id = bundle["client"]["id"]
    documents = bundle["documents"]
    selectable = [document for document in documents if 1 <= document["id"] <= MAX_SAFE_INTEGER]
    body = f'<div class="p-breadcrumb"><a href="/app/clienti/{client_id}">Cliente 360</a> / Preparazione del fascicolo</div>'
    body += notice(
        "Prepara la selezione del fascicolo",
        "Scegli i documenti e le sezioni di interesse. Il servizio verifica che i documenti selezionati siano registrati per questa azienda; la verifica non valuta il contenuto o la completezza dei file.",
    )
    body += '<p class="p-print-note">Nuove analisi disabilitate · <code>new_analysis:false</code>. Nessuna nuova valutazione viene prodotta.</p>'
    body += _client_heading(bundle)
    rows = []
    for document in documents:
        document_id = document["id"]
        title = document.get("title") or "Documento senza titolo"
        if 1 <= document_id <= MAX_SAFE_INTEGER:
            select = f'<label class="p-check-label" for="special-document-{document_id}"><input type="checkbox" id="special-document-{document_id}" name="document_ids" value="{document_id}" aria-describedby="special-documents-help"><span>{esc(title)}</span></label>'
        else:
            select = f'<label class="p-check-label"><input type="checkbox" disabled><span>{esc(title)}<small>Identificativo non selezionabile per questa verifica.</small></span></label>'
        preview = button("Apri documento", f"/app/documenti/{document_id}/anteprima", "quiet", "file") if document_id != 0 and abs(document_id) <= MAX_SAFE_INTEGER else "—"
        rows.append((select, esc(document.get("category") or "Non indicata"), esc(document.get("date") or "Non indicata"), preview))
    documents_html = '<p id="special-documents-help" class="p-print-note">Seleziona da 1 a 80 documenti. L’elenco mostra fino a 150 documenti restituiti dal servizio per questa azienda.</p>'
    if len(documents) == MAX_DOCUMENTS:
        documents_html += notice("Limite dell’elenco raggiunto", "Sono visualizzati 150 documenti. L’archivio può contenerne altri: questa pagina verifica solo i documenti presenti nell’elenco.", "warning")
    documents_html += table(("Selezione e documento", "Categoria", "Data", "Consultazione"), rows, f"{len(documents)} documenti ricevuti · {len(selectable)} selezionabili", "Nessun documento disponibile per questa azienda.")
    if not selectable:
        body += panel("Documenti del fascicolo", documents_html)
        body += notice("La selezione non è ancora disponibile", "Questo elenco non contiene documenti con un identificativo accettato dalla verifica. Riapri il fascicolo dopo la sincronizzazione dei documenti dal MASTER.", "warning")
        body += _saved_data(bundle)
        return body
    section_controls = ''.join(
        f'<label class="p-check-label" for="special-section-{key}"><input type="checkbox" id="special-section-{key}" name="sections" value="{key}"><span>{esc(label)}</span></label>'
        for key, label in SECTIONS.items()
    )
    form_html = f'''<form method="post" action="/app/clienti/{client_id}/prepara-analisi">{csrf_field}
<fieldset class="p-details"><legend>1. Documenti da verificare</legend>{documents_html}</fieldset>
<fieldset class="p-details" aria-describedby="special-sections-help"><legend>2. Sezioni di interesse</legend><p id="special-sections-help" class="p-print-note">Scegli da 1 a 8 sezioni per la preparazione. La selezione non avvia il calcolo di queste analisi.</p><div class="p-form-grid">{section_controls}</div></fieldset>
<label class="p-check-label"><input type="checkbox" name="confirmed" value="yes" required><span>Confermo i documenti e le sezioni selezionati per la sola verifica dell’appartenenza al fascicolo.</span></label>
<div class="p-form-actions p-actions"><button class="p-button p-primary" type="submit">Verifica la selezione</button>{button("Torna all’azienda", f"/app/clienti/{client_id}", "quiet")}</div></form>'''
    body += panel("Prepara il fascicolo FFPlus", form_html)
    body += _saved_data(bundle)
    return body


def _verified_page(bundle, result):
    client_id = bundle["client"]["id"]
    body = f'<div class="p-breadcrumb"><a href="/app/clienti/{client_id}">Cliente 360</a> / <a href="/app/clienti/{client_id}/prepara-analisi">Preparazione del fascicolo</a> / Verifica</div>'
    body += notice(
        "Appartenenza dei documenti verificata",
        "I documenti selezionati risultano registrati per questa azienda. Nessuna nuova analisi, rating o report è stato generato. Il contenuto e la completezza dei file non sono oggetto di questa verifica.",
    )
    body += '<div class="p-actions">' + badge("DOCUMENTS_VERIFIED", "green") + badge("new_analysis:false", "neutral") + '</div>'
    body += _client_heading(bundle)
    rows = [
        (
            esc(document.get("title") or "Documento senza titolo"),
            esc(document.get("category") or "Non indicata"),
            button("Apri documento", f'/app/documenti/{document["id"]}/anteprima', "quiet", "file"),
        )
        for document in result["selected_documents"]
    ]
    body += panel("Documenti della selezione verificata", table(("Documento", "Categoria", "Consultazione"), rows, f'{len(rows)} documenti verificati per l’azienda'))
    sections_html = '<ul class="p-list">' + ''.join('<li><strong>' + esc(SECTIONS[section]) + '</strong></li>' for section in result["sections"]) + '</ul>'
    body += panel("Sezioni selezionate", sections_html, subtitle="Selezione preparata; nessuna nuova analisi eseguita.")
    body += '<div class="p-actions">' + button("Prepara un’altra selezione", f"/app/clienti/{client_id}/prepara-analisi", "primary") + button("Torna all’azienda", f"/app/clienti/{client_id}") + '</div>'
    body += _saved_data(bundle)
    return body


def register_special_one(app, context):
    """Register the read/preflight UI using the existing portal context contract."""
    access, render = context["access"], context["render"]
    field, verify_csrf = context["field"], context["verify_csrf"]

    def owner_access(request):
        user, token, principal, gateway = access(request, staff=True)
        if user.role != "admin" or not isinstance(principal, dict) or principal.get("status") != "active":
            raise HTTPException(403, "La preparazione del fascicolo è riservata all’amministratore proprietario abilitato.")
        capabilities = gateway.get("/v1/capabilities", token)
        if not isinstance(capabilities, dict):
            raise _contract_error()
        if capabilities.get("client_creation") is not True:
            raise HTTPException(403, "Il servizio non abilita questo account alla preparazione del fascicolo.")
        return user, token, principal, gateway

    def read_bundle(gateway, token, client_id):
        # This owner-only GET remains authoritative even when a capability is true.
        result = gateway.get(f"/v1/admin/special-one/clients/{client_id}", token)
        return validated_bundle(result, client_id)

    @app.get("/app/clienti/{client_id}/prepara-analisi")
    def prepare_dossier(client_id: int, request: Request):
        client_id = positive_id(client_id)
        user, token, principal, gateway = owner_access(request)
        bundle = read_bundle(gateway, token, client_id)
        return render(
            "Prepara il fascicolo FFPlus", "Documenti, sezioni di interesse e dati già salvati nel MASTER.",
            _selection_page(bundle, field(request)), request, "/app/clienti",
        )

    @app.post("/app/clienti/{client_id}/prepara-analisi")
    async def verify_dossier(client_id: int, request: Request):
        client_id = positive_id(client_id)
        user, token, principal, gateway = await run_in_threadpool(owner_access, request)
        form = await _form(request)
        verify_csrf(request, form.get("csrf_token", [""])[0])
        selection = normalize_selection(form, client_id)
        # Read again at submission: never rely on IDs or scope from the browser.
        bundle = await run_in_threadpool(read_bundle, gateway, token, client_id)
        available = {document["id"] for document in bundle["documents"] if 1 <= document["id"] <= MAX_SAFE_INTEGER}
        if not set(selection["document_ids"]).issubset(available):
            raise HTTPException(422, "Uno o più documenti non sono disponibili nel fascicolo aggiornato di questa azienda. Riapri la selezione.")
        response = await run_in_threadpool(gateway.post, "/v1/admin/special-one/preflight", token, selection)
        result = validated_preflight(response, selection)
        return await run_in_threadpool(
            render, "Selezione del fascicolo verificata", "Esito della verifica dei documenti selezionati.",
            _verified_page(bundle, result), request, "/app/clienti",
        )
