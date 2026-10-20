# FinancePlus Web 4.1.0

## Scopo della versione

Vetrina pubblica rinnovata, workspace amministrativo e portale Cliente 360, sulla base della proposta visiva approvata il 20 ottobre 2026. Il sito usa i contratti attuali di SMART F+ / LELE_K_PLUS. Non introduce un secondo archivio clienti, un motore finanziario o una copia delle credenziali MASTER.

## Funzioni implementate

- Home, servizi e piattaforma con asset ufficiale attuale, navigazione responsive, struttura semantica e schede servizio dedicate.
- Login operativo con lo stesso account di LELE_K_PLUS; accesso editoriale del sito separato.
- Dashboard, clienti, pratiche e fascicolo Cliente 360; permessi riletti sul gateway a ogni richiesta, collaboratori limitati al perimetro autorizzato.
- Filtri azienda, ricerca, stato e collaboratore quando trasmesso dal servizio. Gestore disponibile soltanto se presente nel payload; segnalatore non ricostruito.
- Elenchi completi o filtrati in anteprima, stampa e PDF, con controllo dei limiti dell'API. La scelta della cartella rimane una funzione del browser.
- Documenti originali in anteprima/download; acquisizione PDF, PNG e JPEG entro 16 MiB. Ricevuta di acquisizione, assegnazione cloud e validazione professionale restano stati distinti.
- Analisi salvate riportate dal MASTER e riepilogo Cliente 360 in PDF. Nessun punteggio, DSCR, rating o ranking viene ricalcolato sul sito.
- Preparazione SPECIAL ONE del fascicolo: selezione di documenti e sezioni, verifica canonica dell'appartenenza e risultato DOCUMENTS_VERIFIED. Funzione riservata al proprietario abilitato; new_analysis:false rimane esplicito.
- Richiesta di nuova azienda tramite il comando canonico riservato al proprietario; ricevuta in coda fino all'esito del MASTER.
- Richieste documentali, Call e VCall: preparazione, conferma e invio del comando canonico; modifica con fingerprint e rilettura della ricevuta. Nessun invio automatico di email o inviti calendario.
- CMS append-only per contenuti della home: bozza, anteprima, pubblicazione separata e ripristino come nuova revisione. Protezione da bozze concorrenti e anteprime scadute.
- Collegamenti App Store, Smart App Banner e Universal Links LELE del commit precedente preservati.

## Architettura e ambiti

Il solo MASTER resta “SMART F+ aggiornato - Aruba e Coda”. Il sito accede al gateway corrente tramite MASTER_API_BASE_URL; i token rimangono in memoria lato server, mai nel cookie, nel DOM, nell'URL o nel database del sito. Il cookie contiene solo un riferimento casuale alla sessione e dati editoriali non sensibili. Alla scadenza massima di 15 minuti è richiesto un nuovo accesso operativo.

La versione supporta una sola istanza e un solo processo Uvicorn, come il servizio Render corrente; Docker e il blueprint alternativo impongono --workers 1. Un'eventuale espansione a più istanze richiede prima uno store condiviso appropriato per le sessioni effimere.

Le tabelle storiche locali clients/documents/analyses sono conservate per compatibilità e rollback, ma non sono usate dalle nuove operazioni finanziarie. La tabella leads e il contratto del bridge di importazione nel MASTER sono preservati. L'unica tabella nuova del sito è site_content_revisions; la sua creazione è additiva. Non sono state modificate tabelle o funzioni del gateway, del MASTER o dell'app.

## Contratti verificati

- Sito base: https://github.com/docdanilodan/FinancePlus_Deploy_TUTTI/commit/75b6cd4808e8f5229048263b31a8744e649f3e87
- Gateway/app, sorgente di riferimento: https://github.com/docdanilodan/SMARTFPLUS-MOBILE-IOS/tree/9735081b8d77e6938e61d37d41e9d32bafa8de85
- Neon Functions smartfmobile, ramo br-quiet-wildflower-b2ltifhj: deployment 27 completato il 20 ottobre 2026; health verificato. L'identità byte-per-byte fra bundle deployato e sorgente Git non è stata attestata.
- Manifest MASTER verificato in sola lettura il 20 ottobre; nessun file desktop modificato.

Le verifiche delle API autenticate sono svolte con doppi di test aderenti ai contratti; non sono state usate password né anagrafiche reali per simulare operazioni. L'uso reale richiede l'account operativo autorizzato dell'utente.

## Limiti da completare nel collegamento MASTER

1. Nuove analisi professionali, DSCR, rating MCC, finanziatori e dossier: il gateway dichiara new_analysis/new_credit_analysis false. La consultazione degli esiti salvati è disponibile; i motori devono essere collegati dalla chat che lavora sull'integrazione.
2. Nuova pratica: non è disponibile un comando canonico verificato; il pulsante non simula la creazione.
3. Gestore e segnalatore: il modello corrente non espone tutte le associazioni. Il sito abilita un filtro soltanto quando il campo è realmente trasmesso.
4. Tessera sanitaria e carta d'identità/CIE: il gateway non offre ancora categorie distinte. Non viene attribuita una categoria inesistente né dichiarata la validazione.
5. Paginazione: /v1/clients restituisce al massimo 500 aziende; un fascicolo espone fino a 100 documenti/richieste/attività, /v1/admin/practices fino a 2.000 righe. Quando la copertura non è dimostrabile, gli elenchi sono marcati parziali e la stampa completa è sospesa.
6. La proiezione cloud dipende dalla sincronizzazione corrente del MASTER. Una risposta PENDING o una ricevuta di caricamento non dimostra completamento sul PC.

## Collaudo riproducibile

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
```

I test impostano database temporanei e gateway sintetici prima dell'import dell'applicazione. Una guardia impedisce l'utilizzo accidentale del gateway reale durante la suite di integrazione. Copertura: isolamento ruoli/clienti, revoca, sessioni, CSRF, PDF multipagina, limiti/categorie documenti, idempotenza, assenza di scritture finanziarie locali, pubblicazione/ripristino CMS e comandi attività.

## Anteprima grafica autonoma

```bash
python scripts/build_visual_preview.py
```

Produce preview-dist esclusivamente da moduli di presentazione e dati sintetici. Nessuna importazione di app.py, query al DB o chiamata al gateway. Tutte le pagine dichiarano che sono dimostrative; i moduli operativi sono disabilitati, gli URL esterni rimossi e la CSP vieta le connessioni. Questa build serve a verificare l'interfaccia e non attesta un'integrazione reale con i dati di produzione.

## Rilascio e ritorno alla versione precedente

Servizio esistente: financeplus-tech-test, srv-dak5c5m1egvs7395lc7g, ramo sito-finance-tech-master-2026-09-14. Prima di aggiornare, rileggere HEAD e deployment live per preservare il lavoro concorrente.

Versione di ritorno: commit 75b6cd4808e8f5229048263b31a8744e649f3e87, già live nel deployment dep-dbbpgf8n74is7398hqig. Copia del riferimento: backup/sito-prima-dashboard-20261020-1720. Il rollback del codice non richiede cancellazione della tabella editoriale né ripristino distruttivo del database.

Dopo il rilascio: verificare deployment LIVE, /health con versione 4.1.0, home/servizi/piattaforma, login e cookie Secure/HttpOnly, /app senza login, asset, App Store redirect e AASA. Il record finale riporterà SHA, deployment, esito HTTP e limiti residui; nessuna pubblicazione è dichiarata riuscita prima di questi controlli.
