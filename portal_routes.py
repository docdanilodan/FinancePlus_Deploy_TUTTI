"""Website controllers over the current SMART F+ gateway; no core DB writes."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from urllib.parse import quote, urlencode

from fastapi import Request, HTTPException, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, func

from master_gateway import GatewayError, MAX_FILE_BYTES
from portal_data import STAFF_ROLES, snapshot, client_bundle, capabilities, filter_snapshot, parse_filters, positive_id, items
from portal_ui import esc, badge, button, panel, empty, notice, table, stat, icon
from portal_views import dashboard_view, companies_view, practices_view, client_view, documents_view, analytics_view, reports_view, agenda_view, finance_view
from portal_pdf import list_pdf, source_report

DOCUMENT_KINDS = {
    "visura_camerale": "Visura camerale", "cr_36_mesi": "Centrale Rischi · 36 mesi",
    "bilancio_2025": "Bilancio 2025", "bilancio_2024": "Bilancio 2024",
    "bozza_bilancio": "Bozza di bilancio", "altro": "Altro · da classificare nel MASTER",
}


def register_portal(app, context):
    render = context["app_page"]
    require_user = context["require_user"]
    require_admin = context["require_admin"]
    csrf_token = context["csrf_token"]
    verify_csrf = context["verify_csrf"]

    def access(request, staff=False):
        user = require_user(request)
        if getattr(user, "auth_source", "") != "master":
            raise GatewayError(428, "MASTER_LOGIN_REQUIRED", "Accedi con il tuo account LELE_K_PLUS per consultare clienti e pratiche autorizzati dal MASTER.")
        if staff and user.role not in STAFF_ROLES:
            raise HTTPException(403)
        return user, request.state.master_token, user.principal, context["gateway"]

    def read_snapshot(request):
        user, token, principal, gateway = access(request)
        if not hasattr(request.state, "portal_snapshot"):
            request.state.portal_snapshot = snapshot(gateway, token, principal)
        return request.state.portal_snapshot

    def cap(request):
        user, token, principal, gateway = access(request)
        if not hasattr(request.state, "portal_capabilities"):
            request.state.portal_capabilities = capabilities(gateway, token, principal)
        return request.state.portal_capabilities

    def view_args(request):
        user, token, principal, gateway = access(request)
        c = cap(request)
        return {"role": user.role, "can_upload": principal.get("can_upload") is True and c.get("intake") is True, "can_create_client": c.get("client_creation") is True, "can_create_practice": False}

    def field(request):
        return f'<input type="hidden" name="csrf_token" value="{esc(csrf_token(request))}">'

    from portal_activities import register_activities
    register_activities(app, {"access": access, "render": render, "field": field, "verify_csrf": verify_csrf})
    from portal_special_one import register_special_one
    register_special_one(app, {"access": access, "render": render, "field": field, "verify_csrf": verify_csrf})

    @app.exception_handler(GatewayError)
    async def gateway_problem(request: Request, exc: GatewayError):
        action = button("Accedi con LELE_K_PLUS", "/login", "primary") if exc.code == "MASTER_LOGIN_REQUIRED" or exc.status == 401 else button("Torna alla panoramica", "/app", "secondary")
        body = notice("Operazione non completata", exc.message, "warning", action)
        user = getattr(request.state, "financeplus_user", None)
        if user:
            response = render("Verifica il collegamento", "Nessun dato viene sostituito con risultati dimostrativi.", body, request, "/app/impostazioni")
            response.status_code = exc.status if exc.status in {400, 401, 403, 404, 409, 413, 415, 422, 428, 429, 502, 503} else 503
            return response
        return HTMLResponse(f'<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Collegamento FinancePlus</title><link rel="stylesheet" href="/static/portal.css"></head><body><main class="p-content"><h1>Verifica il collegamento</h1>{body}</main></body></html>', status_code=503)

    @app.get("/app")
    def dashboard(request: Request):
        user = require_user(request)
        if getattr(user, "auth_source", "") != "master":
            if user.role != "admin":
                raise HTTPException(403)
            with context["SessionLocal"]() as db:
                count = db.scalar(select(func.count(context["Lead"].id))) or 0
            content = notice("Collega la tua area operativa", "Usa l'account di LELE_K_PLUS per vedere clienti, pratiche, documenti e report con gli stessi permessi del MASTER.", action=button("Accedi al MASTER", "/login", "primary"))
            content += '<div class="p-stats">' + stat("Richieste dal sito", count, "/app/richieste-sito", "users") + stat("Gestione contenuti", "Apri", "/app/gestione-sito", "settings", "amber") + '</div>'
            content += panel("Gestisci il tuo sito", '<div class="p-actions">' + button("Modifica la home", "/app/gestione-sito", symbol="settings") + button("Visita la vetrina", "/", symbol="arrow") + '</div>')
            return render("Amministrazione del sito", "Contenuti, richieste e accesso alla tua area operativa.", content, request, "/app")
        data = read_snapshot(request)
        filters = parse_filters(request.query_params)
        if data.get("pending"):
            content = notice("La tua area personale è pronta", "Puoi caricare i documenti. Le pratiche saranno visibili dopo la verifica e l'assegnazione dello studio.", action=button("Carica documenti", "/app/carica-documenti", "primary"))
            return render("Benvenuto in FinancePlus", "Il tuo percorso con lo studio inizia qui.", content, request, "/app")
        return render("Panoramica operativa", "Clienti, richieste e prossime attività.", dashboard_view(filter_snapshot(data, filters), filters, **view_args(request)), request, "/app")

    @app.get("/app/clienti")
    def clients(request: Request):
        data = read_snapshot(request)
        filters = parse_filters(request.query_params)
        return render("Clienti e aziende", "Un fascicolo per ogni azienda, con le sue singole richieste.", companies_view(filter_snapshot(data, filters), filters, **view_args(request)), request, "/app/clienti")

    @app.get("/app/pratiche")
    def practices(request: Request):
        data = read_snapshot(request)
        filters = parse_filters(request.query_params)
        return render("Pratiche e richieste", "Finalità, importi, documenti e stato di ogni richiesta.", practices_view(filter_snapshot(data, filters), filters, **view_args(request)), request, "/app/pratiche")

    def export_data(request, kind):
        data = read_snapshot(request)
        if not data.get("complete"):
            raise GatewayError(409, "INCOMPLETE_EXPORT", "Il servizio ha restituito una parte dei dati. L'esportazione è sospesa per evitare un elenco incompleto.")
        scope = request.query_params.get("scope", "filtered")
        if scope not in {"filtered", "all"}:
            raise HTTPException(422, "Ambito di stampa non valido.")
        filters = parse_filters(request.query_params) if scope == "filtered" else {}
        selected = filter_snapshot(data, filters)
        if kind == "clienti":
            headers = ["Azienda", "Partita IVA", "Settore", "Pratiche nella vista"]
            rows = [[c.get("name", ""), c.get("vat") or "Non disponibile", c.get("sector") or "Non disponibile", str(sum(1 for p in selected["practices"] if p.get("client_id") == c["id"]))] for c in selected["companies"]]
        else:
            headers = ["Azienda", "Richiesta", "Finalità", "Importo", "Stato", "Istituto"]
            rows = [[p.get("client_name", ""), p.get("title", ""), p.get("purpose") or "Non indicata", str(p.get("amount")) if p.get("amount") is not None else "Non disponibile", p.get("status", ""), p.get("institution") or "Non indicato"] for p in selected["practices"]]
        return data, filters, scope, headers, rows

    @app.get("/app/{kind}/stampa")
    def print_list(kind: str, request: Request):
        if kind not in {"clienti", "pratiche"}:
            raise HTTPException(404)
        data, filters, scope, headers, rows = export_data(request, kind)
        query = dict(filters, scope=scope)
        pdf_url = f"/app/{kind}/pdf?" + urlencode(query)
        label = "Elenco completo autorizzato" if scope == "all" else "Vista filtrata autorizzata"
        content = '<div class="p-actions"><button class="p-button p-primary" type="button" data-print>' + icon("print") + 'Stampa</button>' + button("Scarica PDF", pdf_url, symbol="download") + button("Torna all'elenco", f"/app/{kind}?" + urlencode(filters), "quiet") + '</div>'
        content += f'<div class="p-print-heading"><h1>{label} · {esc(kind)}</h1><p>{len(rows)} righe · Fonte: {esc(data["source"])}</p><p>Filtri: {esc("; ".join(f"{k}: {v}" for k, v in filters.items() if v) or "Nessun filtro")}</p></div>'
        content += '<p class="p-print-note">Il pulsante Scarica PDF genera il file. La cartella di destinazione dipende dalle impostazioni del browser e del dispositivo. Nel dialogo Stampa puoi scegliere anche Salva come PDF.</p>'
        content += table(headers, [[esc(v) for v in row] for row in rows], f"{len(rows)} righe nel perimetro autorizzato")
        return render("Anteprima di stampa", label, content, request, f"/app/{kind}")

    @app.get("/app/{kind}/pdf")
    def export_pdf(kind: str, request: Request):
        if kind not in {"clienti", "pratiche"}:
            raise HTTPException(404)
        data, filters, scope, headers, rows = export_data(request, kind)
        user = require_user(request)
        content = list_pdf("Clienti e aziende" if kind == "clienti" else "Pratiche e richieste", headers, rows, filters, user.role, data["source"], "Elenco completo autorizzato" if scope == "all" else "Vista filtrata autorizzata")
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="FinancePlus_{kind}_{scope}.pdf"'})

    @app.get("/app/clienti/{client_id}")
    def client_detail(client_id: int, request: Request, tab: str = "sintesi", practice: str = ""):
        user, token, principal, gateway = access(request)
        bundle = client_bundle(gateway, token, principal, client_id)
        if practice and not any(str(p.get("id")) == practice for p in bundle.get("requests", [])):
            raise GatewayError(404, "NOT_FOUND", "Pratica non disponibile per questo cliente.")
        if tab not in {"sintesi", "pratiche", "documenti", "analisi", "attivita", "report"}:
            raise HTTPException(404)
        args = view_args(request)
        args["can_prepare_analysis"] = args.pop("can_create_client", False) and user.role == "admin"
        return render("Cliente 360", "Il fascicolo autorizzato, con fonti e stato delle attività.", client_view(bundle, tab, selected_practice=practice or None, **args), request, "/app/clienti")

    @app.get("/app/documenti")
    def documents(request: Request):
        user, token, principal, gateway = access(request)
        if user.role not in STAFF_ROLES:
            return RedirectResponse("/app/carica-documenti", 303) if principal.get("can_upload") else render("Documenti", "Perimetro autorizzato", documents_view([], loaded=False), request, "/app/documenti")
        data = read_snapshot(request)
        content = documents_view(data["documents"], loaded=data["documents_loaded"], can_upload=view_args(request)["can_upload"])
        return render("Documenti", "Originali, categorie e stato della verifica.", content, request, "/app/documenti")

    @app.get("/app/analisi")
    def analyses(request: Request):
        access(request, staff=True)
        data = read_snapshot(request)
        return render("Analisi e Centrale Rischi", "Esiti trasmessi dal MASTER, senza nuove elaborazioni nel sito.", analytics_view(data["bundles"]), request, "/app/analisi")

    @app.get("/app/scoring")
    def legacy_scoring(request: Request, client: int | None = None):
        access(request, staff=True)
        if client is None:
            return RedirectResponse("/app/analisi", 303)
        user, token, principal, gateway = access(request)
        client_bundle(gateway, token, principal, client)
        return RedirectResponse(f"/app/clienti/{client}?tab=analisi", 303)

    @app.get("/app/finanziatori")
    def lenders(request: Request):
        access(request, staff=True)
        return render("Finanziatori", "Valutazioni di compatibilità dal sistema autorevole.", finance_view(), request, "/app/finanziatori")

    @app.get("/app/report")
    def reports(request: Request):
        access(request, staff=True)
        return render("Report e riepiloghi", "Anteprima, stampa e PDF del fascicolo consultabile.", reports_view(read_snapshot(request)["bundles"]), request, "/app/report")

    @app.get("/app/report/{client_id}/anteprima")
    def report_preview(client_id: int, request: Request):
        user, token, principal, gateway = access(request, staff=True)
        bundle = client_bundle(gateway, token, principal, client_id)
        if bundle.get("analysis") is None:
            raise GatewayError(404, "ANALYSIS_UNAVAILABLE", "Nessuna analisi disponibile per questo cliente.")
        body = '<div class="p-actions">' + button("Scarica PDF", f"/app/report/{client_id}/pdf", "primary", "download") + button("Apri PDF per stampa", f"/app/report/{client_id}/contenuto", symbol="print") + '</div><p class="p-print-note">La stampa è disponibile anche nel visualizzatore PDF. Il salvataggio della cartella dipende dal browser.</p>'
        body += f'<iframe class="p-doc-frame" title="Riepilogo Cliente 360 di {esc(bundle["client"].get("name", ""))}" src="/app/report/{client_id}/contenuto"></iframe>'
        return render("Anteprima del riepilogo", "Informazioni ricevute dal MASTER; nessun nuovo score calcolato.", body, request, "/app/report")

    @app.get("/app/report/{client_id}/pdf")
    @app.get("/app/report/{client_id}/contenuto")
    def report_content(client_id: int, request: Request):
        user, token, principal, gateway = access(request, staff=True)
        bundle = client_bundle(gateway, token, principal, client_id)
        if bundle.get("analysis") is None:
            raise GatewayError(404, "ANALYSIS_UNAVAILABLE", "Nessuna analisi disponibile per questo cliente.")
        disposition = "inline" if request.url.path.endswith("/contenuto") else "attachment"
        return Response(source_report(bundle), media_type="application/pdf", headers={"Content-Disposition": f'{disposition}; filename="FinancePlus_Cliente360_{client_id}.pdf"'})

    @app.get("/app/agenda")
    def agenda(request: Request):
        data = read_snapshot(request)
        return render("Agenda e attività", "Prossime attività presenti nei fascicoli autorizzati.", agenda_view(data["tasks"], loaded=data["tasks_loaded"]), request, "/app/agenda")

    @app.get("/app/impostazioni")
    def settings(request: Request):
        user = require_user(request)
        connected = getattr(user, "auth_source", "") == "master"
        state = badge("Account MASTER collegato", "green") if connected else badge("Accesso al sito", "blue")
        body = panel("Il tuo accesso", state + '<p class="p-print-note">Ogni richiesta verifica nuovamente i permessi sul servizio. Alla scadenza della sessione di LELE_K_PLUS occorre accedere di nuovo.</p>' + ('' if connected else button("Accedi con LELE_K_PLUS", "/login", "primary")))
        cards = [("MASTER", "Clienti, pratiche, documenti, analisi e assegnazioni sono letti dal servizio attuale di SMART F+."), ("App LELE_K_PLUS", "Sito e app usano lo stesso account operativo e i relativi permessi."), ("Richieste dal sito", "I contatti sono acquisiti dal sito e importati dal collegamento esistente nel MASTER. La registrazione non invia automaticamente messaggi.")]
        body += '<div class="p-connection-grid">' + ''.join(f'<section class="p-connection-card">{icon("shield")}<h3>{esc(t)}</h3><p>{esc(d)}</p></section>' for t, d in cards) + '</div>'
        if user.role == "admin":
            body += panel("Gestione della vetrina", button("Bozze e pubblicazione", "/app/gestione-sito", symbol="settings"))
        return render("Collegamenti e impostazioni", "Lo stato dei tuoi strumenti FinancePlus.", body, request, "/app/impostazioni")

    @app.get("/app/richieste-sito")
    def site_requests(request: Request):
        require_admin(request)
        with context["SessionLocal"]() as db:
            leads = list(db.scalars(select(context["Lead"]).order_by(context["Lead"].created_at.desc()).limit(200)))
        rows = [[esc(p.name), esc(p.company), esc(p.email), esc(p.phone), esc(p.service), esc(p.message), esc(p.created_at.strftime("%d/%m/%Y %H:%M"))] for p in leads]
        body = notice("Richieste acquisite dal sito", "Questa vista mostra la ricezione sul sito. Lo stato di importazione e lavorazione va verificato nel MASTER; non equivale a un messaggio inviato.")
        body += panel("Ultime richieste", table(["Nome", "Azienda", "Email", "Telefono", "Servizio", "Messaggio", "Ricevuta UTC"], rows, "Ultime 200 richieste acquisite"))
        return render("Richieste dal sito", "Contatti e fabbisogni comunicati dalle imprese.", body, request, "/app/richieste-sito")

    @app.get("/app/nuovo-cliente")
    def new_client(request: Request):
        access(request, staff=True)
        if cap(request).get("client_creation") is not True:
            raise HTTPException(403)
        key = str(uuid.uuid4())
        body = notice("La registrazione avviene nel MASTER", "Il sito prepara la richiesta. L'azienda apparirà in elenco quando il MASTER avrà assegnato il suo identificativo; puoi seguire l'esito nella coda.")
        body += panel("Dati della nuova azienda", f'<form method="post" class="p-form-grid">{field(request)}<input type="hidden" name="idempotency_key" value="{key}"><div class="p-field p-form-wide"><label for="new-name">Ragione sociale</label><input id="new-name" name="name" minlength="2" maxlength="180" autocomplete="organization" required></div><div class="p-field"><label for="new-vat">Partita IVA italiana</label><input id="new-vat" name="vat" inputmode="numeric" pattern="[0-9]{{11}}" maxlength="11" required></div><div class="p-field"><label for="new-sector">Settore</label><input id="new-sector" name="sector" maxlength="180"></div><label class="p-form-wide"><input type="checkbox" name="confirmed" value="true" required> Ho verificato i dati e confermo la richiesta di registrazione nel MASTER.</label><div class="p-form-actions p-form-wide"><button type="submit" class="p-button p-primary">Conferma richiesta al MASTER</button>{button("Annulla", "/app/clienti", "quiet")}{button("Richieste in attesa", "/app/richieste-clienti", "quiet")}</div></form>')
        return render("Nuova azienda", "Identità unica e registrazione controllata.", body, request, "/app/clienti")

    @app.post("/app/nuovo-cliente")
    def new_client_submit(request: Request, name: str = Form(...), vat: str = Form(...), sector: str = Form(""), confirmed: str = Form(""), idempotency_key: str = Form(""), csrf_token: str = Form("")):
        user, token, principal, gateway = access(request, staff=True)
        verify_csrf(request, csrf_token)
        if cap(request).get("client_creation") is not True:
            raise HTTPException(403)
        if confirmed != "true" or len(name.strip()) < 2 or len(name) > 180 or len(sector) > 180 or not re.fullmatch(r"[0-9]{11}", vat) or not re.fullmatch(r"[0-9a-fA-F-]{36}", idempotency_key):
            raise HTTPException(422, "Verifica i dati e conferma la richiesta.")
        receipt = gateway.post("/v1/client-requests", token, {"confirmed": True, "name": name.strip(), "vat": vat, "sector": sector.strip(), "idempotency_key": idempotency_key})
        if not receipt.get("id") or receipt.get("status") not in {"PENDING", "COMPLETED", "IMPORTED", "DUPLICATE", "FAILED", "REJECTED"}:
            raise GatewayError(502, "RECEIPT_MISSING", "Non è disponibile una ricevuta valida. Controlla la coda prima di riprovare.")
        return RedirectResponse("/app/richieste-clienti", 303)

    @app.get("/app/richieste-clienti")
    def client_requests(request: Request):
        user, token, principal, gateway = access(request, staff=True)
        if cap(request).get("client_creation") is not True:
            raise HTTPException(403)
        rows = items(gateway.get("/v1/client-requests", token))
        cells = [[esc(r.get("name", "")), badge(r.get("status"), "neutral"), esc(r.get("master_client_id") or "In attesa"), esc(r.get("reason") or "Attendi l'elaborazione del MASTER"), esc(r.get("id"))] for r in rows]
        body = panel("Ricevute del MASTER", table(["Azienda", "Stato", "ID cliente MASTER", "Esito", "Ricevuta"], cells, "Ultime 50 richieste dell'account"), button("Aggiorna", "/app/richieste-clienti"))
        return render("Richieste di registrazione", "Lo stato PENDING indica ricezione in coda, non registrazione conclusa.", body, request, "/app/clienti")

    @app.get("/app/carica-documenti")
    def upload_page(request: Request, ok: int = 0, client: str = ""):
        user, token, principal, gateway = access(request)
        if principal.get("can_upload") is not True:
            raise HTTPException(403)
        upload_allowed = cap(request).get("intake") is True
        options = ''.join(f'<option value="{key}">{esc(label)}</option>' for key, label in DOCUMENT_KINDS.items())
        key = str(uuid.uuid4())
        body = notice("Ricevuta e verifica sono due passaggi distinti", "Il file viene acquisito nella coda del MASTER. L'azienda, la categoria e la validazione vanno confermate nel fascicolo; il sito non ricava dati finanziari dal nome del file.")
        if ok:
            body += notice("Caricamento acquisito", "La ricevuta effettiva è nella coda qui sotto. Controlla lo stato prima di procedere.")
        if upload_allowed:
            body += panel("Carica un documento", f'<form method="post" enctype="multipart/form-data" class="p-form-grid">{field(request)}<input type="hidden" name="idempotency_key" value="{key}"><div class="p-field"><label for="document-kind">Tipo di documento</label><select id="document-kind" name="document_kind">{options}</select></div><div class="p-field"><label for="document-file">File · massimo 16 MiB</label><input id="document-file" type="file" name="file" accept="application/pdf,image/png,image/jpeg" required><small>PDF, PNG e JPEG. Gli account in verifica possono caricare PDF.</small></div><div class="p-form-wide"><p class="p-print-note">Tessera sanitaria e Carta d’identità / CIE restano categorie distinte nel MASTER. Le relative classificazioni non sono ancora esposte da questo canale: usa Altro e completa la classificazione nel fascicolo.</p></div><div class="p-form-actions p-form-wide"><button type="submit" class="p-button p-primary">Carica nella coda</button>{button("Torna ai documenti", "/app/documenti", "quiet")}</div></form>')
        else:
            body += notice("Caricamento momentaneamente non disponibile", "Il servizio non ha abilitato l'archivio per questa sessione.", "warning")
        uploads = items(gateway.get("/v1/intakes", token))
        cells = []
        for row in uploads:
            ident = quote(str(row.get("id", "")), safe="")
            actions = button("Anteprima", f"/app/caricamenti/{ident}/anteprima", "quiet")
            if user.role in STAFF_ROLES and row.get("status") in {"UPLOADED", "PROPOSED", "NEEDS_REVIEW"}:
                actions += button("Verifica assegnazione", f"/app/caricamenti/{ident}/assegna", "quiet")
            cells.append([esc(row.get("filename", "")), badge(row.get("status"), "neutral"), esc(DOCUMENT_KINDS.get(row.get("document_kind"), row.get("document_kind") or "Non indicato")), esc(row.get("reason", "")), actions])
        body += panel("Coda dei caricamenti autorizzati", table(["Documento", "Stato ricevuto", "Tipo dichiarato", "Esito", "Azioni"], cells, "Ultimi 100 caricamenti disponibili"))
        return render("Carica documenti", "Acquisizione tracciata e conferma dell'assegnazione.", body, request, "/app/documenti")

    @app.post("/app/carica-documenti")
    async def upload_submit(request: Request, file: UploadFile = File(...), document_kind: str = Form("altro"), idempotency_key: str = Form(""), csrf_token: str = Form("")):
        user, token, principal, gateway = await run_in_threadpool(access, request)
        verify_csrf(request, csrf_token)
        if principal.get("can_upload") is not True or (await run_in_threadpool(cap, request)).get("intake") is not True:
            raise HTTPException(403)
        if document_kind not in DOCUMENT_KINDS or not re.fullmatch(r"[0-9a-fA-F-]{36}", idempotency_key):
            raise HTTPException(422, "Tipo documento o identificativo non valido.")
        filename = file.filename or ""
        if not filename or len(filename) > 180 or any(ord(c) < 32 for c in filename) or "/" in filename or "\\" in filename:
            raise HTTPException(422, "Nome file non valido.")
        data = bytearray()
        try:
            while chunk := await file.read(256 * 1024):
                data.extend(chunk)
                if len(data) > MAX_FILE_BYTES:
                    raise HTTPException(413, "Il file supera 16 MiB. Nessun file è stato trasferito al MASTER.")
        finally:
            await file.close()
        lower = filename.lower()
        valid = lower.endswith(".pdf") and data[:5] == b"%PDF-" or lower.endswith(".png") and data[:8] == b"\x89PNG\r\n\x1a\n" or lower.endswith((".jpg", ".jpeg")) and data[:3] == b"\xff\xd8\xff"
        if not valid:
            raise HTTPException(415, "Sono accettati PDF, PNG e JPEG con contenuto corrispondente.")
        if principal.get("status") == "pending" and not lower.endswith(".pdf"):
            raise HTTPException(415, "Per l'area personale in verifica carica un PDF.")
        # The exact existing API validates the live role, content hash, quotas,
        # receipt and retry key again. No metadata is committed to the site DB.
        receipt = await run_in_threadpool(gateway.post, "/v1/intakes", token, data=bytes(data), headers={"Content-Type": "application/octet-stream", "x-filename": quote(filename, safe=""), "x-idempotency-key": idempotency_key, "x-document-kind": document_kind})
        if not receipt.get("id") or not receipt.get("status"):
            raise GatewayError(502, "RECEIPT_MISSING", "Caricamento da verificare. Controlla la coda prima di riprovare.")
        return RedirectResponse("/app/carica-documenti?ok=1", 303)

    def original(request, ident, intake=False):
        user, token, principal, gateway = access(request, staff=not intake)
        if intake:
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", str(ident)):
                raise HTTPException(404)
            path = f"/v1/intakes/{quote(str(ident), safe='')}/content"
        else:
            try:
                value = int(ident)
            except ValueError:
                raise HTTPException(404) from None
            if value == 0 or abs(value) > 9007199254740991:
                raise HTTPException(404)
            path = f"/v1/documents/{value}/content"
        return gateway.request("GET", path, token, binary=True)

    @app.get("/app/documenti/{ident}/anteprima")
    @app.get("/app/caricamenti/{ident}/anteprima")
    def document_preview(ident: str, request: Request):
        intake = request.url.path.startswith("/app/caricamenti/")
        data, mime = original(request, ident, intake)
        base = ("/app/caricamenti/" if intake else "/app/documenti/") + quote(ident, safe="")
        clean_mime = mime.split(";", 1)[0].strip().lower()
        if clean_mime == "application/pdf" and data.startswith(b"%PDF-"):
            preview = f'<iframe class="p-doc-frame" title="Anteprima documento originale" src="{base}/contenuto"></iframe>'
            actions = button("Scarica PDF originale", base + "/scarica", "primary", "download") + button("Apri PDF per stampa", base + "/contenuto", symbol="print")
        elif clean_mime in {"image/png", "image/jpeg"}:
            preview = f'<img src="{base}/contenuto" alt="Documento originale" style="max-width:100%;height:auto">'
            actions = button("Scarica originale", base + "/scarica", "primary", "download") + '<button class="p-button" type="button" data-print>Stampa / Salva PDF</button>'
        else:
            preview = empty("Anteprima non disponibile per questo formato", "Puoi scaricare l'originale e aprirlo con il programma adatto.", button("Scarica originale", base + "/scarica"))
            actions = ""
        body = '<div class="p-actions">' + actions + '</div><p class="p-print-note">La stampa si apre nel visualizzatore del browser. Per le immagini scegli Salva come PDF nel dialogo di stampa. La cartella è gestita dal browser e dal dispositivo.</p>' + preview
        return render("Anteprima documento", "Contenuto originale autorizzato; nessuna assegnazione o validazione automatica.", body, request, "/app/documenti")

    @app.get("/app/documenti/{ident}/contenuto")
    @app.get("/app/documenti/{ident}/scarica")
    @app.get("/app/caricamenti/{ident}/contenuto")
    @app.get("/app/caricamenti/{ident}/scarica")
    def document_content(ident: str, request: Request):
        intake = request.url.path.startswith("/app/caricamenti/")
        data, mime = original(request, ident, intake)
        clean_mime = mime.split(";", 1)[0].strip().lower()
        supported = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}
        ext = supported.get(clean_mime, "bin")
        disposition = "inline" if request.url.path.endswith("/contenuto") and clean_mime in supported else "attachment"
        return Response(data, media_type=clean_mime if clean_mime in supported else "application/octet-stream", headers={"Content-Disposition": f'{disposition}; filename="FinancePlus_documento_{ident}.{ext}"'})

    @app.get("/app/caricamenti/{ident}/assegna")
    def assign_preview(ident: str, request: Request):
        user, token, principal, gateway = access(request, staff=True)
        if cap(request).get("approval_queue") is not True:
            raise HTTPException(403)
        rows = items(gateway.get("/v1/intakes", token))
        item = next((r for r in rows if str(r.get("id")) == ident), None)
        if not item:
            raise HTTPException(404)
        clients = items(gateway.get("/v1/clients", token))
        choices = '<option value="">Seleziona l’azienda verificata</option>' + ''.join(f'<option value="{c["id"]}">{esc(c.get("name"))} · {esc(c.get("vat"))}</option>' for c in clients)
        body = notice("Conferma soltanto dopo aver verificato l'originale", "Questa operazione assegna il documento nel fascicolo cloud. La validazione professionale e l'allineamento sul PC restano passaggi distinti.")
        body += panel("Documento da assegnare", f"""<p><strong>{esc(item.get("filename"))}</strong></p>{button("Apri originale", f"/app/caricamenti/{quote(ident, safe='')}/anteprima", symbol="file")}<form method="post" class="p-form-grid">{field(request)}<input type="hidden" name="expected_revision" value="{esc(item.get("revision"))}"><div class="p-field p-form-wide"><label for="assignment-client">Azienda</label><select id="assignment-client" name="client_id" required>{choices}</select></div><label class="p-form-wide"><input type="checkbox" name="confirmed" value="true" required> Ho verificato l'originale e l'azienda destinataria.</label><div class="p-form-actions p-form-wide"><button class="p-button p-primary" type="submit">Conferma assegnazione</button></div></form>""")
        return render("Verifica assegnazione", "L'identità dell'azienda va confermata esplicitamente.", body, request, "/app/documenti")

    @app.post("/app/caricamenti/{ident}/assegna")
    def assign_submit(ident: str, request: Request, client_id: int = Form(...), expected_revision: int = Form(...), confirmed: str = Form(""), csrf_token: str = Form("")):
        user, token, principal, gateway = access(request, staff=True)
        verify_csrf(request, csrf_token)
        if cap(request).get("approval_queue") is not True:
            raise HTTPException(403)
        if confirmed != "true" or expected_revision < 1 or not re.fullmatch(r"[0-9a-fA-F-]{36}", ident):
            raise HTTPException(422, "Conferma esplicitamente documento e azienda.")
        positive_id(client_id)
        gateway.post(f"/v1/intakes/{ident}/approve", token, {"confirmed": True, "client_id": client_id, "expected_revision": expected_revision})
        return RedirectResponse("/app/carica-documenti", 303)
