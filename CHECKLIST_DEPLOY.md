# Checklist deploy FinancePlus Streamlit

## Prima di caricare su GitHub

- [ ] Il file principale si chiama `app.py`.
- [ ] Il file dipendenze si chiama `requirements.txt`.
- [ ] `.streamlit/config.toml` è presente.
- [ ] `.streamlit/secrets.toml` reale NON è presente.
- [ ] Database, report, documenti cliente, allegati, email e backup reali non sono inclusi.
- [ ] Il logo è presente in root e in `assets/`.
- [ ] Avvio locale verificato con `streamlit run app.py`.

## Test funzionali minimi

- [ ] Dashboard aperta senza errori.
- [ ] Creazione cliente test.
- [ ] Upload documento test.
- [ ] Controllo duplicati hash.
- [ ] Generazione report PDF.
- [ ] Backup ZIP.
- [ ] Test IMAP solo con account dedicato o ambiente controllato.

## Streamlit Cloud

- [ ] Repository collegato.
- [ ] Branch corretto selezionato.
- [ ] Main file path impostato a `app.py`.
- [ ] Secrets compilati nel pannello Streamlit Cloud.
- [ ] Nessun import Tkinter nella versione cloud.
