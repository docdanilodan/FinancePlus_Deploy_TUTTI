# FinancePlus.tech — configurazione produzione

- Sito e Area Clienti: FastAPI su Render, regione Frankfurt.
- Database: Neon `FinancePlus Cloud`, database `financeplus`.
- Email amministratore e contatti: `d.dangelo@financeplus.tech`.
- Dominio e posta restano su Aruba.
- Per collegare il dominio al web service cambiare solo i record web (`@`/`www` secondo le istruzioni Render); NON modificare MX, SPF, DKIM o record mail Aruba.
- I documenti del pilot sono memorizzati come dati binari nel database Neon; limite applicativo 10 MB/file. Per produzione a volume elevato passare a object storage privato S3.
- Variabili segrete da impostare su Render: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_PASSWORD`. SMTP Aruba opzionale: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.
- `SESSION_HTTPS_ONLY=1` in produzione.

## Avvio

`uvicorn app:app --host 0.0.0.0 --port $PORT`

## Health check

`/health`
