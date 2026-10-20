# FinancePlus.tech · Web 4.1.0

Vetrina pubblica, dashboard amministrativa e Cliente 360 collegati ai servizi autorizzati di SMART F+ / LELE_K_PLUS.

Il MASTER resta il sistema di riferimento per clienti, pratiche, documenti, analisi e assegnazioni. Questa versione sostituisce i precedenti percorsi dimostrativi di scoring con letture e comandi delle API correnti. I dati storici locali sono preservati, ma non vengono usati come un secondo archivio finanziario.

## Funzioni

- Vetrina responsive, servizi, piattaforma e collegamenti LELE_K_PLUS.
- Dashboard, elenchi aziende/pratiche e Cliente 360 secondo i permessi dell'account operativo.
- Filtri realmente disponibili, anteprima di stampa e PDF completi/filtrati con controllo della copertura.
- Originali documentali, caricamenti tracciati e assegnazione esplicita.
- Analisi salvate e riepiloghi dal MASTER; preparazione del fascicolo SPECIAL ONE tramite preflight.
- Richieste documentali, Call e VCall tramite comandi canonici con ricevuta riletta.
- Gestione editoriale della home: bozza, anteprima, pubblicazione e ripristino versionato.

Lo stato delle funzioni, i contratti verificati e i limiti attuali sono descritti in [docs/WEB_4_1_RELEASE.md](docs/WEB_4_1_RELEASE.md). Il gateway non espone ancora l'avvio di nuove analisi finanziarie, la creazione di pratiche o tutte le classificazioni/associazioni richieste: la UI non simula queste operazioni.

## Avvio per sviluppo locale

Richiede Python 3.12 e un ambiente isolato. Impostare credenziali locali esplicite e un database di test prima dell'avvio. Le API operative restano protette dall'account LELE_K_PLUS; non sono forniti account operativi dimostrativi.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

Su Windows usare gli equivalenti eseguibili in `.venv\Scripts`. `SEED_DEMO` è disattivato nel codice della versione 4.1: non crea clienti o score di esempio.

## Collaudo isolato

```bash
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
```

La suite usa database temporanei e gateway sintetici. Nessun account reale è necessario.

## Anteprima grafica sintetica

```bash
python scripts/build_visual_preview.py
```

Genera `preview-dist` da moduli di presentazione e fixture esplicitamente dimostrative, senza importare l'applicazione o contattare database/gateway. Il risultato può essere pubblicato come normale sito statico di staging. Moduli e connessioni operative sono disabilitati. `index.html` raccoglie le viste; `mobile.html` mostra le larghezze 390 e 360 px.

## Produzione

Il rilascio usa il servizio Render esistente e PostgreSQL/Neon del sito. Sono richiesti `APP_ENV=production`, `SECRET_KEY` stabile di almeno 32 caratteri, `DATABASE_URL` PostgreSQL e `ADMIN_PASSWORD` amministrativa non dimostrativa. Nessun valore segreto va committato.

`MASTER_API_BASE_URL` deve indicare l'origine HTTPS del gateway corrente verificato. L'account operativo usa lo stesso login di LELE_K_PLUS. La voce “Amministrazione del sito” mantiene l'accesso editoriale locale per gli amministratori già presenti.

La versione supporta una sola istanza e un solo worker. I token operativi sono effimeri in memoria per un massimo di 15 minuti; scadenza e riavvio richiedono un nuovo login. Prima di scalare occorre predisporre lo stato di sessione condiviso.

Per fonte di rilascio, rollback e verifiche successive consultare [il registro della versione](docs/WEB_4_1_RELEASE.md). Le guide 4.0 conservate nel repository sono storiche; per le funzioni della versione attuale prevale questo documento.
