# SITO_FINANCE+TECH - FinancePlus Platform ULTIMATE 4.0 consolidata

Questa e la cartella eseguibile del progetto CHAT MASTER del 09/09/2026. Il brand pubblico resta **FinancePlus.tech**. Per la procedura completa usare `../02_GUIDE/Guida_Pubblicazione_SITO_FINANCE+TECH.pdf`.

**Architettura unica della release:** Aruba = dominio/posta; Render Frankfurt = applicazione; FinancePlus Cloud / Neon = PostgreSQL.

---

Versione unica del sito FinancePlus.tech + Area Privata + gestionale + pre-fattibilita Invoice Trading AI.

## Contenuto

### Sito pubblico
- Home premium FinancePlus.tech
- Servizi
- Metodo
- Piattaforma
- Insights
- Chi siamo
- Contatti con acquisizione lead
- Registrazione Area Clienti con approvazione
- Login protetto

### Area privata / gestionale
Grafica progettata sul modello delle schermate fornite: sidebar blu notte, pannelli bianchi, accenti rame, badge di stato, KPI e workflow.

- Dashboard
- Nuovo Cliente
- Clienti Salvati
- Documenti
- Analisi AI
- Scoring Piattaforme
- Report
- Impostazioni

### Invoice Trading Pre-Fattibilita AI
- caricamento documenti multiplo
- classificazione documentale per nome/tipologia
- score per Cedente, Debitore, Fattura, Centrale Rischi e Documentazione
- ranking piattaforme
- motivazione AI dimostrativa
- punti di forza / elementi di attenzione
- report PDF scaricabile

## Avvio locale

### Windows
1. installare Python 3.12+
2. estrarre la cartella
3. eseguire `START_WINDOWS.bat`
4. aprire `http://127.0.0.1:8000`

### Manuale
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Anteprima locale
Con `SEED_DEMO=1`:
- email: `d.dangelo@financeplus.tech`
- password: `FinancePlusDemo2026!`

La password demo e solo per test locale. In produzione impostare `SEED_DEMO=0` e definire `ADMIN_PASSWORD` come variabile ambiente.

## Produzione
Architettura consigliata del progetto:
- Aruba: dominio e posta
- Render (Frankfurt): applicazione FastAPI
- FinancePlus Cloud / Neon: PostgreSQL

Vedi `DEPLOY_RENDER_ARUBA_NEON.md`.

## Sicurezza prima di usare dati reali
Questa release e pronta per collaudo tecnico e pubblicazione controllata. Prima di caricare documenti reali:
- `APP_ENV=production`
- HTTPS attivo
- `SECRET_KEY` casuale e lunga
- `ADMIN_PASSWORD` diversa dalla demo
- PostgreSQL/Neon via SSL
- backup verificato
- object storage privato S3 per documenti, se si supera l'MVP iniziale
- 2FA almeno per gli amministratori
- policy privacy, retention e audit definite

## Nota sulle piattaforme Invoice Trading
I nomi e gli score presenti nella demo sono configurabili e servono a rappresentare il motore di ranking. Prima dell'uso commerciale, requisiti, disponibilita, pricing e regole di ammissibilita delle singole piattaforme devono essere aggiornati con fonti ufficiali.
