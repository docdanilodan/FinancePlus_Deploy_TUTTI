# Pubblicazione FinancePlus.tech

## Architettura
- Dominio e posta: Aruba
- Applicazione: Render, regione Frankfurt
- Database: FinancePlus Cloud / Neon PostgreSQL

## 1. Repository GitHub
Caricare questa cartella in un repository privato o pubblico, ma NON inserire `.env`, password, `DATABASE_URL`, backup o documenti cliente.

## 2. Neon
Nel progetto FinancePlus Cloud creare/verificare il database applicativo e copiare la connection string PostgreSQL SSL.
Usare il formato SQLAlchemy:

`postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require`

## 3. Render
Creare un Web Service collegato al repository.

Con Docker:
- Runtime: Docker
- Region: Frankfurt
- Health Check: `/health`

Oppure senza Docker:
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## 4. Variabili ambiente Render
Impostare:
- `APP_ENV=production`
- `DATABASE_URL=...`
- `SECRET_KEY=...`
- `ADMIN_EMAIL=d.dangelo@financeplus.tech`
- `ADMIN_PASSWORD=...`
- `CONTACT_EMAIL=d.dangelo@financeplus.tech`
- `PHONE=+39 329 113 5692`
- `BASE_URL=https://financeplus.tech`
- `SEED_DEMO=0`
- `MAX_UPLOAD_MB=20`

## 5. Test sul dominio temporaneo Render
Verificare:
- `/health`
- Home
- Servizi
- Contatti
- Registrazione
- Login
- Dashboard privata
- Nuovo Cliente
- Scoring Piattaforme
- Generazione PDF

## 6. Custom Domain
Su Render aggiungere:
- `financeplus.tech`
- `www.financeplus.tech`

Render mostrerà i record DNS da impostare.

## 7. DNS Aruba
Nel pannello DNS Aruba modificare SOLO i record web richiesti da Render (A/AAAA/CNAME).
NON modificare i record MX della posta. Conservare SPF/DKIM/DMARC esistenti salvo interventi specifici sulla posta.

## 8. HTTPS
Attendere propagazione DNS e certificato TLS. Verificare entrambi i domini e impostare un dominio canonico.

## 9. Collaudo
Prima dell'apertura generale:
- creare un cliente pilota
- caricare documenti non sensibili di test
- eseguire analisi e scoring
- generare PDF
- testare permessi e logout
- verificare log e backup

## 10. Hardening successivo
Per dati reali e crescita del servizio:
- object storage privato S3 con URL temporanei
- 2FA amministratori
- antivirus upload
- rate limiting login
- audit log esteso
- email/WhatsApp ufficiali
- OCR/IDP con fonte, pagina, confidenza e validazione umana
