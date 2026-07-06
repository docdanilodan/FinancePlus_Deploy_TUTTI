# FinancePlus Streamlit Cartella Deploy

Cartella pronta per GitHub e Streamlit Cloud della **FinancePlus Master Suite PRO**.

## File principali

| File / cartella | Funzione |
|---|---|
| `app.py` | File principale Streamlit. Contiene dashboard, Cliente 360, documenti, Cerca Azienda, scoring, Business Plan, note/calendario, report e backup. |
| `requirements.txt` | Dipendenze Python da installare prima dell'avvio o richieste da Streamlit Cloud. |
| `.streamlit/config.toml` | Tema grafico blu/rame, layout e impostazioni server. |
| `.streamlit/secrets.toml.example` | Modello credenziali senza password reali. Copiare in `secrets.toml` solo in locale; su cloud usare Settings > Secrets. |
| `assets/` | Logo FinancePlus in formato PNG/ICO. |
| `financeplus_data/` | Cartella dati locale creata/gestita dall'app: database, clienti, report, backup, log. Non caricare dati reali su repository pubblico. |
| `uploads/`, `reports/`, `data/` | Cartelle compatibili con le versioni Streamlit precedenti e con deploy ordinato. |
| `.gitignore` | Protegge database, dati riservati, cache Python e secrets reali. |

## Avvio locale

```bash
cd FinancePlus_Streamlit_Cartella
python -m pip install -r requirements.txt
streamlit run app.py
```

## Deploy Streamlit Cloud

1. Creare un repository GitHub.
2. Caricare `app.py`, `requirements.txt`, `.streamlit/config.toml`, `.gitignore`, `README.md`, `assets/` e logo.
3. Non caricare database, documenti riservati, cartelle piene di file cliente o `secrets.toml` reale.
4. Su Streamlit Cloud scegliere **New app**.
5. Impostare **Main file path**: `app.py`.
6. Inserire eventuali credenziali in **Settings > Secrets**.

## Moduli inclusi nell'app

- Dashboard professionale blu/rame con KPI e azioni rapide.
- Cliente 360 con anagrafica, fascicolo, documenti, note, richieste e stato pratica.
- Import documenti con hash SHA-256 anti-duplicato e cartella temporanea da verificare.
- Cerca Azienda su mail, allegati, oggetto e testo documento.
- Archivio cliente/mese/tipologia con log operativo.
- Centrale Rischi, PHANTOM score, MCC/DSCR e Business Plan sintetico.
- Report PDF, export CSV e backup ZIP.

## Nota di sicurezza

Prima dell'uso su dati reali vanno verificati: connessioni IMAP, gestione credenziali, backup, log, privacy, ruoli utente e policy di conservazione documentale.
