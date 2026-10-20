"""Browser forms for the existing MASTER client-activity command API.

The canonical gateway owns scope checks, the durable command queue and the
MASTER writeback.  The website sends explicit create/update commands only;
it never sends email, calendar invitations or external messages here.
"""
from __future__ import annotations

from datetime import datetime
import json
import re
from urllib.parse import parse_qs, urlencode
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from master_gateway import GatewayError
from portal_data import positive_id, items
from portal_ui import badge, button, empty, esc, icon, notice, panel, path_id, table


KINDS = {"document_request": "Richiesta di integrazione documentale", "call": "Call", "vcall": "VCall"}
STATUSES = {
    "document_request": ("Non evasa", "Parziale", "Evasa"),
    "call": ("Programmato", "Eseguito", "Annullato"),
    "vcall": ("Programmato", "Eseguito", "Annullato"),
}
COMMAND_LABELS = {
    "PENDING": ("In coda al MASTER", "amber"),
    "COMPLETED": ("Completata", "green"),
    "CONFLICT": ("Conflitto da verificare", "amber"),
    "FAILED": ("Non completata", "red"),
    "ERROR": ("Errore da verificare", "red"),
}
MAX_FORM_BYTES = 128 * 1024
MAX_COMMAND_BYTES = 16_384


def _command_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise HTTPException(422, "Riferimento del comando non valido. Riapri il modulo.")
    return str(UUID(value))


def _target_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:crm|timeline):[1-9][0-9]*", value):
        raise HTTPException(404, "Attività non disponibile.")
    return value


def _date_value(value, *, time_required=False):
    """Convert a Rome wall-clock form value to the existing gateway format."""
    if not isinstance(value, str):
        raise HTTPException(422, "Data non valida.")
    value = value.strip()
    if not value:
        if time_required:
            raise HTTPException(422, "Indica la data e l’ora dell’appuntamento.")
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::00)?)?", value):
        raise HTTPException(422, "Usa una data valida e, per gli appuntamenti, l’ora di Roma al minuto.")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, "La data o l’ora indicata non esiste.") from None
    if len(value) == 10:
        if time_required:
            raise HTTPException(422, "Indica anche l’ora dell’appuntamento.")
        return value
    return value[:10] + " " + value[11:16] + ":00"


def normalize_activity_form(form, client_id, *, existing=None):
    """Validate the explicit command without deriving business information."""
    client_id = positive_id(client_id)
    command_id = _command_id(form.get("command_id"))
    if form.get("confirmed") != "yes":
        raise HTTPException(422, "Conferma il riepilogo prima di registrare il comando.")
    action, kind = form.get("action"), form.get("kind")
    if action not in {"create", "update"} or kind not in KINDS:
        raise HTTPException(422, "Operazione non disponibile.")
    description = form.get("description", "")
    if not isinstance(description, str) or not description.strip() or len(description) > 8000:
        raise HTTPException(422, "Inserisci una descrizione da 1 a 8.000 caratteri.")
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in description):
        raise HTTPException(422, "La descrizione contiene caratteri non consentiti.")
    status = form.get("status")
    if status not in STATUSES[kind]:
        raise HTTPException(422, "Seleziona uno stato valido per il tipo di attività.")
    target_id = expected = None
    practice_id = None
    if action == "update":
        target_id = _target_id(form.get("target_id"))
        expected = form.get("expected")
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise HTTPException(422, "Versione dell’attività non valida. Riapri il modulo.")
        if existing is None or existing.get("id") != target_id or str(existing.get("client_id")) != str(client_id):
            raise HTTPException(404, "L’attività non appartiene al fascicolo autorizzato.")
        if existing.get("kind") != kind:
            raise HTTPException(422, "Il tipo di un’attività esistente non può essere cambiato da questo modulo.")
        if existing.get("fingerprint") != expected:
            raise HTTPException(409, "L’attività è cambiata. Riapri la scheda e controlla i dati aggiornati.")
        practice_id = existing.get("practice_id")
        if practice_id is not None:
            practice_id = positive_id(practice_id)
    elif form.get("target_id") or form.get("expected") or form.get("practice_id"):
        raise HTTPException(422, "La nuova attività deve essere riferita all’azienda selezionata.")
    if kind == "document_request" and practice_id is not None:
        raise HTTPException(422, "Le integrazioni documentali di questo canale sono riferite all’azienda.")
    if action == "update" and not target_id.startswith("crm:" if kind == "document_request" else "timeline:"):
        raise HTTPException(422, "Identificativo non coerente con il tipo di attività.")
    event_date = _date_value(form.get("event_date", ""), time_required=kind != "document_request")
    due_date = _date_value(form.get("due_date", ""))
    command = {
        "command_id": command_id, "confirmed": True, "action": action, "kind": kind,
        "target_id": target_id, "expected": expected, "practice_id": practice_id,
        "description": description.strip(), "status": status,
        "event_date": event_date, "due_date": due_date,
    }
    if len(json.dumps(command, ensure_ascii=False).encode("utf-8")) > MAX_COMMAND_BYTES:
        raise HTTPException(422, "Il testo supera la dimensione accettata dal servizio. Riduci la descrizione.")
    return command


async def _form(request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Formato del modulo non supportato.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FORM_BYTES:
            raise HTTPException(413, "Il modulo supera la dimensione consentita.")
    try:
        fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=20, errors="strict")
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Modulo non valido.") from None
    if any(len(values) != 1 for values in fields.values()):
        raise HTTPException(400, "Il modulo contiene campi duplicati.")
    return {name: values[0] for name, values in fields.items()}


def _display_date(value):
    if not value:
        return "Non indicata"
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.strftime("%d/%m/%Y · %H:%M") + " (Roma)" if len(str(value)) > 10 else parsed.strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _hidden(name, value):
    return f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'


def _date_control(name, label, value, *, appointment=False, required=False):
    value = str(value or "")
    timed = appointment or len(value) > 10
    kind = "datetime-local" if timed else "date"
    formatted = value.replace(" ", "T")[:16] if timed else value[:10]
    return f'<div class="p-field"><label for="activity-{name}">{esc(label)}</label><input type="{kind}" id="activity-{name}" name="{name}" value="{esc(formatted)}"' + (' required' if required else '') + (' step="60"' if timed else '') + '></div>'


def _status_badge(status):
    text, tone = COMMAND_LABELS.get(str(status), ("Stato da verificare: " + str(status or "non disponibile"), "neutral"))
    return badge(text, tone)


def register_activities(app, context):
    """Register the website adapter; imports/registration have no side effects."""
    access = context["access"]
    render = context["render"]
    field = context["field"]
    verify_csrf = context["verify_csrf"]

    def admin_access(request):
        user, token, principal, gateway = access(request, staff=True)
        if user.role != "admin" or principal.get("status") != "active":
            raise HTTPException(403, "Solo l’amministratore può registrare o modificare queste attività.")
        return user, token, principal, gateway

    def read_activities(gateway, token, client_id):
        result = items(gateway.get(f"/v1/portal/clients/{client_id}/activities", token))
        if any(str(row.get("client_id")) != str(client_id) for row in result):
            raise GatewayError(502, "INVALID_ACTIVITY_SCOPE", "Le attività ricevute non corrispondono al fascicolo richiesto.")
        return result

    def get_target(gateway, token, client_id, target_id):
        target_id = _target_id(target_id)
        current = next((row for row in read_activities(gateway, token, client_id) if row.get("id") == target_id), None)
        if current is None:
            raise HTTPException(404, "Attività non disponibile nel fascicolo autorizzato.")
        return current

    def base(client_id):
        return f"/app/clienti/{client_id}/attivita"

    def form_page(request, client_id, kind, existing=None):
        client_id = positive_id(client_id)
        if kind not in KINDS:
            raise HTTPException(422, "Tipo di attività non disponibile.")
        existing = existing or {}
        updating = bool(existing)
        status = existing.get("status", STATUSES[kind][0])
        status_options = "".join(f'<option value="{esc(s)}"' + (' selected' if status == s else '') + f'>{esc(s)}</option>' for s in STATUSES[kind])
        if updating and status not in STATUSES[kind]:
            status_options = '<option value="" selected>Seleziona uno stato valido</option>' + status_options
        action = "update" if updating else "create"
        hidden = field(request) + _hidden("command_id", str(uuid4())) + _hidden("action", action) + _hidden("kind", kind)
        if updating:
            hidden += _hidden("target_id", existing["id"]) + _hidden("expected", existing.get("fingerprint", ""))
        date_fields = _date_control("event_date", "Data e ora dell’appuntamento · Roma" if kind != "document_request" else "Data della richiesta", existing.get("event_date"), appointment=kind != "document_request", required=kind != "document_request")
        date_fields += _date_control("due_date", "Scadenza / data di verifica", existing.get("due_date"), appointment=False)
        description = esc(existing.get("description", ""))
        title = ("Modifica · " if updating else "Nuova · ") + KINDS[kind]
        submit_label = "Conferma modifica al MASTER" if updating else "Conferma registrazione nel MASTER"
        scope_note = "La richiesta documentale è riferita all’intera azienda." if kind == "document_request" else (f"L’appuntamento mantiene l’associazione alla pratica {existing['practice_id']}." if existing.get("practice_id") else "L’appuntamento è riferito all’azienda selezionata.")
        body = f'<div class="p-breadcrumb"><a href="/app/clienti/{client_id}">Cliente 360</a> / <a href="{base(client_id)}">Attività</a></div>'
        body += notice("Registrazione di un’attività", scope_note + " La conferma registra un comando nella coda del MASTER; non invia email o inviti calendario.")
        form_html = f'''<form method="post" action="{base(client_id)}" class="p-form-grid">{hidden}
<div class="p-field p-form-wide"><label for="activity-description">Descrizione · massimo 8.000 caratteri</label><textarea id="activity-description" name="description" rows="7" maxlength="8000" required>{description}</textarea></div>
<div class="p-field"><label for="activity-status">Stato dell’attività</label><select id="activity-status" name="status" required>{status_options}</select></div>{date_fields}
<div class="p-form-wide"><p class="p-print-note">Gli orari sono espressi in Europe/Rome, ora di Roma. Controlla descrizione, date e stato prima di confermare.</p><label class="p-check-label"><input type="checkbox" name="confirmed" value="yes" required><span>Ho verificato il riepilogo e confermo la registrazione del comando nel MASTER.</span></label></div>
<div class="p-form-actions p-form-wide"><button class="p-button p-primary" type="submit">{submit_label}</button>{button("Annulla", base(client_id), "quiet")}</div></form>'''
        body += panel(title, form_html, subtitle="Azienda " + str(client_id))
        return render(title, "Preparazione e conferma di un comando tracciabile.", body, request, "/app/clienti")

    @app.get("/app/clienti/{client_id}/attivita")
    def activity_list(client_id: int, request: Request, command_id: str = ""):
        client_id = positive_id(client_id)
        user, token, principal, gateway = access(request)
        records = read_activities(gateway, token, client_id)
        is_admin = user.role == "admin" and principal.get("status") == "active"
        commands = items(gateway.get(f"/v1/admin/clients/{client_id}/activity-commands", token)) if is_admin else []
        body = f'<div class="p-breadcrumb"><a href="/app/clienti/{client_id}">Cliente 360</a> / Attività</div>'
        actions = button("Aggiorna attività e ricevute", base(client_id) + ("?" + urlencode({"command_id": command_id}) if command_id else ""), symbol="clock")
        if is_admin:
            actions = "".join(button(label, base(client_id) + "/nuova?" + urlencode({"kind": kind}), "primary" if kind == "document_request" else "secondary", "plus") for kind,label in (("document_request", "Richiedi integrazione"), ("call", "Nuova Call"), ("vcall", "Nuova VCall"))) + actions
        body += '<div class="p-actions">' + actions + '</div>'
        if command_id and is_admin:
            receipt_id = _command_id(command_id)
            receipt = next((row for row in commands if str(row.get("id")) == receipt_id), None)
            if receipt is None:
                body += notice("Ricevuta da verificare", "Il riferimento non compare nelle ultime 30 ricevute di questo account. Aggiorna lo storico e verifica prima di ripetere la registrazione.", "warning")
            else:
                status = str(receipt.get("status", ""))
                if status == "COMPLETED":
                    text = "La ricevuta riletta dal servizio indica che il comando è completato. Le attività sotto riportano i dati disponibili al momento della lettura."
                    title, tone = "Comando completato", "info"
                elif status == "PENDING":
                    text = "Il comando è in coda al MASTER. La registrazione dell’attività non risulta ancora completata: usa Aggiorna attività e ricevute per verificarne l’esito."
                    title, tone = "Comando in attesa", "warning"
                else:
                    text = "Il servizio non indica un completamento riuscito. Controlla lo stato nella ricevuta e riapri l’attività prima di preparare una nuova modifica."
                    title, tone = "Esito da verificare", "warning"
                body += notice(title, text + " Riferimento: " + receipt_id, tone)
        rows = []
        for row in records:
            kind = str(row.get("kind", ""))
            description = str(row.get("description") or "")
            text = esc(description[:220])
            if len(description) > 220:
                text += '<details class="p-details"><summary>Leggi la descrizione completa</summary><p class="p-activity-description">' + esc(description) + '</p></details>'
            action = button("Modifica", base(client_id) + "/" + path_id(row["id"]) + "/modifica", "quiet") if is_admin and kind in KINDS else ""
            rows.append((esc(KINDS.get(kind, kind or "Attività")), '<div class="p-activity-description">' + text + '</div>', badge(row.get("status")), esc(_display_date(row.get("event_date"))), esc(_display_date(row.get("due_date"))), action))
        body += panel("Integrazioni e Call/VCall", table(("Tipo", "Descrizione", "Stato", "Data / ora", "Scadenza", ""), rows, f"{len(records)} attività autorizzate", "Nessuna attività disponibile nel perimetro autorizzato."), subtitle="Registrazioni del MASTER. Nessun invio email o invito calendario viene eseguito da questa pagina.")
        if is_admin:
            command_rows = [(esc(row.get("id")), _status_badge(row.get("status")), esc(row.get("result") or "In attesa di risultato")) for row in commands]
            body += panel("Ricevute dei comandi", table(("Riferimento", "Stato del comando", "Risultato"), command_rows, "Ultime 30 ricevute di questo account per l’azienda", "Nessun comando registrato da questo account."), subtitle="In coda e completata sono stati distinti; una richiesta accettata non prova la scrittura nel MASTER.")
        return render("Attività Cliente 360", "Integrazioni documentali, Call e VCall del fascicolo autorizzato.", body, request, "/app/clienti")

    @app.get("/app/clienti/{client_id}/attivita/nuova")
    def new_activity(client_id: int, request: Request, kind: str = "document_request"):
        client_id = positive_id(client_id)
        user, token, principal, gateway = admin_access(request)
        # Confirm the canonical read scope before showing a command form.
        read_activities(gateway, token, client_id)
        return form_page(request, client_id, kind)

    @app.get("/app/clienti/{client_id}/attivita/{target_id}/modifica")
    def edit_activity(client_id: int, target_id: str, request: Request):
        client_id = positive_id(client_id)
        user, token, principal, gateway = admin_access(request)
        current = get_target(gateway, token, client_id, target_id)
        return form_page(request, client_id, current.get("kind"), current)

    @app.post("/app/clienti/{client_id}/attivita")
    async def submit_activity(client_id: int, request: Request):
        client_id = positive_id(client_id)
        user, token, principal, gateway = admin_access(request)
        form = await _form(request)
        verify_csrf(request, form.get("csrf_token", ""))
        existing = await run_in_threadpool(get_target, gateway, token, client_id, form.get("target_id")) if form.get("action") == "update" else None
        command = normalize_activity_form(form, client_id, existing=existing)
        receipt = await run_in_threadpool(gateway.post, f"/v1/admin/clients/{client_id}/activities", token, command)
        if receipt.get("id") != command["command_id"] or not isinstance(receipt.get("status"), str):
            raise GatewayError(502, "RECEIPT_UNVERIFIED", "Ricevuta non verificata. Controlla lo storico delle attività prima di riprovare.")
        # Always re-read the durable receipt on GET. HTTP 202 or the immediate
        # response alone is never turned into a completed-MASTER assertion.
        return RedirectResponse(base(client_id) + "?" + urlencode({"command_id": command["command_id"]}), status_code=303)

    return {"activity_list": activity_list, "new_activity": new_activity, "edit_activity": edit_activity, "submit_activity": submit_activity}
