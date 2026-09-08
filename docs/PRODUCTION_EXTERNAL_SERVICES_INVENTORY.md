# Inventarul serviciilor externe

Fiecare aplicație, serviciu, API și cont din afara ContaCRM de care depinde
platforma. Lista este **derivată din cod**, nu din memorie: din adresele găsite în
surse, din dependențele declarate, din variabilele de mediu pe care le citește
`Settings`, și din `docker-compose.yml`. Ce nu apare aici nu este chemat de
nicăieri.

**Cum se citește starea de verificare:**

| Stare | Înseamnă |
|---|---|
| `VERIFIED LIVE` | S-a rulat împotriva serviciului real, cu credențiale reale. |
| `VERIFIED SANDBOX` | S-a rulat împotriva mediului de test al furnizorului. |
| `MOCK VERIFIED` | S-au verificat parsarea, erorile, izolarea și starea din baza noastră, împotriva unui dublu scris după documentație. Protocolul rămâne o presupunere. |
| `NOT VERIFIED — CREDENTIALS REQUIRED` | Nu s-a putut rula: lipsește credențiala. |
| `NOT VERIFIED — PROVIDER ACCESS REQUIRED` | Lipsește un drept, nu o cheie: înregistrare, aprobare, certificat. |
| `NOT IMPLEMENTED` | Nu există cod. |
| `NOT APPLICABLE` | Nu se aplică. |

**Niciun serviciu extern nu este `VERIFIED LIVE`.** Nu s-a primit nicio
credențială externă pe durata construcției.

---

## 1. PostgreSQL

### Purpose
Baza de date a aplicației. Toate datele structurate: cabinete, utilizatori,
clienți, documente, perioade, declarații, tranzacții bancare, jurnal de audit.

### Provider
Oricare furnizor de PostgreSQL **17** (server propriu, Supabase, Neon, RDS,
DigitalOcean). Nu este legată de niciun furnizor anume.

### Integration Type
Conexiune de bază de date (SQLAlchemy 2.0 + `psycopg` 3).

### Used By
`backend/app/core/db.py`, toate repository-urile și serviciile; `alembic/`.

### Environment Variables
```text
DATABASE_URL
DB_ECHO
DB_POOL_SIZE
DB_MAX_OVERFLOW
DB_EXTERNAL_POOLER
```
Pentru stiva Docker locală, `docker-compose.yml` mai citește:
```text
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
POSTGRES_PORT
```

### Account Required
Da.

### Account Type
Găzduire PostgreSQL 17, sau server propriu.

### Credentials Required
Utilizator și parolă, în `DATABASE_URL`. Utilizatorul aplicației **nu** trebuie
să fie `postgres`.

### Webhooks
Nu.

### Production URL / Endpoint
Adresa instalării. Nu există una implicită în cod dincolo de cea de development.

### Sandbox/Test Environment
Da — baza de test locală și `contacrm_e2e`, recreată la fiecare rulare E2E.

### Production Verification Status
`MOCK VERIFIED` pentru instalarea de producție (nu există una încă);
**verificat rulând** local: migrări de la zero pe bază goală (44 de tabele),
suita întreagă pe PostgreSQL real, copie și restaurare completă.

### Setup Steps
1. creează baza și un utilizator dedicat;
2. pune `DATABASE_URL`;
3. `alembic upgrade head` **înainte** de a porni versiunea nouă;
4. închide accesul din internet.

Dacă `DATABASE_URL` arată către un pooler în mod tranzacție (PgBouncer, Supabase
pe `:6543`), pune `DB_EXTERNAL_POOLER=true` — altfel instrucțiunile pregătite se
rup tăcut.

### Renewal / Expiration
Nu expiră. Parola se rotește după politica cabinetului.

### Billing
Depinde de furnizor.

### Data Sent
Toate datele aplicației.

### Data Received
Idem.

### Failure Impact
Aplicația nu pornește; `/health/ready` răspunde cu eroare.

### Recovery
Automată la revenirea bazei. Poolul se reface singur.

---

## 2. Stocarea documentelor — disc local **sau** S3

### Purpose
Fișierele propriu-zise: originalele încărcate, copiile din arhivă, fișierele
însoțitoare ale facturilor electronice.

### Provider
- `STORAGE_PROVIDER=local` — discul serverului (implicit);
- `STORAGE_PROVIDER=s3` — orice serviciu compatibil S3: AWS S3, Cloudflare R2,
  Supabase Storage, MinIO.

**Acesta este singurul loc din aplicație unde se alege între doi furnizori.**
Restul codului nu află niciodată care este activ (ADR-004).

### Integration Type
Filesystem, respectiv SDK S3 (`boto3`).

### Used By
`backend/app/services/storage/` (`local.py`, `s3.py`, `factory.py`).

### Environment Variables
```text
STORAGE_PROVIDER
STORAGE_PATH
ARCHIVE_ROOT
MAX_UPLOAD_SIZE_MB
ALLOWED_MIME_TYPES
S3_BUCKET
S3_ENDPOINT_URL
S3_REGION
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
S3_PREFIX
```

### Account Required
Numai pentru `s3`. Pe `local`, nu.

### Account Type
Cont la un furnizor de stocare compatibil S3.

### Credentials Required
`S3_ACCESS_KEY_ID` și `S3_SECRET_ACCESS_KEY`, plus numele bucket-ului.

### Webhooks
Nu.

### Production URL / Endpoint
`S3_ENDPOINT_URL` gol înseamnă AWS. Pentru R2/Supabase/MinIO se pune adresa lor —
o dă furnizorul, nu este scrisă în cod.

### Sandbox/Test Environment
Da: testele rulează pe `moto` (S3 simulat) și pe disc temporar.

### Production Verification Status
- disc local: **verificat rulând** — încărcare, descărcare, arhivare, copie și
  restaurare cu conținut identic pe octet;
- S3: `MOCK VERIFIED` (`moto`).

### Setup Steps
1. alege `local` sau `s3`;
2. pentru `local`: un volum **persistent**, nu în containerul care se recreează;
3. pentru `s3`: creează bucket-ul, **nepublic**, cu chei dedicate;
4. include stocarea în copia de siguranță — vezi [RUNBOOK.md](RUNBOOK.md).

### Renewal / Expiration
Cheile S3 se rotesc după politica furnizorului.

### Billing
Da, pentru S3.

### Data Sent
**Documentele contabile ale clienților**, integral.

### Data Received
Aceleași fișiere, la citire.

### Failure Impact
Încărcarea și descărcarea eșuează; documentele deja înregistrate rămân în bază,
dar nu se pot deschide.

### Recovery
Imediată la revenire. `python -m app.cli check-storage` spune dacă baza și
fișierele sunt din același moment.

---

## 3. ANAF — SPV / e-Factura

### Purpose
Preluarea automată a facturilor electronice ale clienților din Spațiul Privat
Virtual, și transformarea XML→PDF pentru facsimil.

### Provider
ANAF (Agenția Națională de Administrare Fiscală).

### Integration Type
OAuth 2.0 (authorization code) + REST.

### Used By
`backend/app/services/anaf/` (`client.py`, `sync.py`, `archive.py`, `runner.py`),
`backend/app/api/v1/anaf.py`.

### Environment Variables
```text
ANAF_CLIENT_ID
ANAF_CLIENT_SECRET
ANAF_REDIRECT_URI
ANAF_ENVIRONMENT
ANAF_SYNC_BATCH
ANAF_LOOKBACK_DAYS
DRIVE_TOKEN_KEY
```
`DRIVE_TOKEN_KEY` criptează refresh tokenul înainte de bază; este comună cu
Microsoft, deliberat (o singură cheie de criptare la repaus).

### Account Required
Da.

### Account Type
Cont SPV al cabinetului **plus** aplicație înregistrată în portalul OAuth ANAF.

### Credentials Required
- `client_id` și `client_secret` de la înregistrarea aplicației;
- **certificat digital calificat**, prezentat de browser la autorizare;
- împuternicire în SPV pentru fiecare client ale cărui facturi se preiau.

### Webhooks
Nu. Preluarea este prin interogare periodică (pull), pornită de cron.

### Production URL / Endpoint
Confirmate din cod (`app/services/anaf/client.py`):
```text
https://logincert.anaf.ro/anaf-oauth2/v1        (autorizare — cere certificatul)
https://api.anaf.ro/prod/FCTEL/rest             (producție)
https://api.anaf.ro/test/FCTEL/rest             (test)
https://webservicesp.anaf.ro/prod/FCTEL/rest/transformare/FACT1   (XML→PDF, public)
```

### Sandbox/Test Environment
Da: `ANAF_ENVIRONMENT=test`. **Bază complet separată** la ANAF — o factură din
test nu există în producție. O instalare lăsată pe `test` raportează „nicio
factură" la nesfârșit, fără nicio eroare.

### Production Verification Status
`NOT VERIFIED — PROVIDER ACCESS REQUIRED`

Cer un certificat calificat și înregistrarea aplicației. Ce **s-a** verificat:
parsarea UBL 2.1 / RO_CIUS cu linii și cote de TVA pe linie, dezarhivarea cu
apărare împotriva zip-slip și a arhivelor umflate, reînnoirea și expirarea
tokenului, erorile ANAF, izolarea pe organizație și serializarea prin
`pg_advisory_xact_lock`, și că un eșec de preluare nu marchează documente ca
eșuate.

### Setup Steps
1. cabinetul obține certificat digital calificat;
2. înregistrează aplicația în portalul OAuth ANAF, cu `ANAF_REDIRECT_URI` identic
   cu cel configurat;
3. pune `ANAF_CLIENT_ID` / `ANAF_CLIENT_SECRET`, `ANAF_ENVIRONMENT=prod`;
4. un administrator parcurge autorizarea din *Administrare → e-Factura*, cu
   certificatul în calculator;
5. adaugă împuternicirea pentru fiecare client.

### Renewal / Expiration
- **certificatul calificat**: 1–3 ani, după emitent;
- **refresh tokenul ANAF**: aproximativ un an, apoi autorizarea se reface manual,
  tot cu certificatul. O intervenție umană pe an.

### Billing
Certificatul calificat se plătește emitentului. API-ul ANAF nu se plătește.

### Data Sent
CUI-urile clienților împuterniciți și fereastra de timp interogată.

### Data Received
Lista mesajelor și arhivele ZIP cu facturile electronice (XML + semnătură).

### Failure Impact
Facturile electronice nu se mai preiau. Nimic altceva nu se oprește; documentele
pot fi încărcate manual.

### Recovery
Turul următor continuă de unde a rămas. Un eșec nu marchează documente ca eșuate.

### Ce NU face aplicația
**Nu depune nimic la ANAF** și nu trimite facturi în SPV. Vezi
[DECLARATIONS.md](DECLARATIONS.md).

---

## 4. Microsoft Graph — OneDrive / SharePoint și email

### Purpose
Preluarea automată a documentelor din dosarele clienților (OneDrive/SharePoint)
și din cutiile poștale ale cabinetului. **O singură conexiune, două surse.**

### Provider
Microsoft (Entra ID + Microsoft Graph).

### Integration Type
OAuth 2.0 (authorization code, cu `offline_access`) + REST.

### Used By
`backend/app/services/microsoft/` (`graph.py`, `drive_sync.py`, `mail_sync.py`,
`runner.py`), `backend/app/api/v1/integrations.py`.

### Environment Variables
```text
MS_CLIENT_ID
MS_CLIENT_SECRET
MS_TENANT_ID
MS_REDIRECT_URI
DRIVE_TOKEN_KEY
DRIVE_SYNC_BATCH
MAIL_SYNC_BATCH
```

### Account Required
Da.

### Account Type
Tenant Microsoft 365 / Entra ID, cu o aplicație înregistrată.

### Credentials Required
`client_id`, `client_secret`, `tenant_id`. Consimțământul îl dă un utilizator al
cabinetului, o singură dată.

### Webhooks
Nu. Sincronizarea este prin interogare periodică, pornită de cron.

### Production URL / Endpoint
Confirmate din cod (`app/services/microsoft/graph.py`):
```text
https://graph.microsoft.com/v1.0
https://login.microsoftonline.com
```
Scopes cerute: `offline_access User.Read Files.Read.All Mail.Read` — **numai
citire**.

### Sandbox/Test Environment
Nu există un sandbox separat; se poate folosi un tenant de test.

### Production Verification Status
`NOT VERIFIED — CREDENTIALS REQUIRED`

Ce **s-a** verificat (`test_drive_sync.py`, `test_mail_sync.py`, `drive_fake.py`):
parcurgerea dosarelor, paginarea, delta-tokenul, descărcarea și așezarea pe
clientul potrivit, criptarea refresh tokenului înainte de bază, deconectarea, și
că o sincronizare eșuată pe o organizație nu oprește restul.

### Setup Steps
1. Azure Portal → Entra ID → App registrations → New registration;
2. adaugă `MS_REDIRECT_URI` **identic** cu cel configurat, altfel consimțământul
   eșuează cu o eroare opacă;
3. adaugă permisiunile delegate de mai sus;
4. generează un client secret;
5. un administrator conectează contul din *Administrare → Surse documente*.

### Renewal / Expiration
**Client secretul Entra ID expiră** — implicit la 6, 12 sau 24 de luni, după cum
a fost creat. Este cea mai frecventă cauză de „nu mai vin documente". Notează
data.

### Billing
Inclus în abonamentul Microsoft 365 al cabinetului.

### Data Sent
Cereri de listare și descărcare. Nu se trimite conținut.

### Data Received
Fișierele din dosarele urmărite și atașamentele mesajelor.

### Failure Impact
Documentele nu mai sosesc din OneDrive și din email. Ecranul spune de ce.

### Recovery
Automată la revenire; delta-tokenul reia de unde a rămas.

---

## 5. Server IMAP (cutie poștală obișnuită)

### Purpose
Aceeași preluare din email, pentru cabinetele care nu sunt pe Microsoft 365:
Gmail, Yahoo, găzduire proprie.

### Provider
Oricare server IMAP.

### Integration Type
IMAP peste SSL, prin `imaplib` din biblioteca standard. **Fără dependență nouă.**

### Used By
`backend/app/services/imap/` (`client.py`, `sync.py`, `runner.py`),
`backend/app/api/v1/integrations.py`.

### Environment Variables
```text
IMAP_SYNC_BATCH
DRIVE_TOKEN_KEY
```
Serverul, utilizatorul și parola **nu sunt variabile de mediu**: se configurează
per cabinet, din interfață, iar parola se criptează cu `DRIVE_TOKEN_KEY` înainte
de bază.

### Account Required
Da — cutia poștală a cabinetului.

### Account Type
Orice cont de email cu IMAP activ.

### Credentials Required
Gazdă, port, utilizator, parolă. Pentru Gmail și Yahoo: **parolă de aplicație**,
nu parola contului.

### Webhooks
Nu.

### Production URL / Endpoint
Gazda o dă furnizorul de email. Nu există una în cod.

### Sandbox/Test Environment
Nu.

### Production Verification Status
`NOT VERIFIED — CREDENTIALS REQUIRED`

Ce **s-a** verificat (`test_imap_sync.py`, `test_imap_runner.py`, `imap_fake.py`):
citirea mesajelor, atașamentele, tipurile MIME, recunoașterea expeditorului ca
client, marcarea ca citit, și serializarea per organizație — reparată la auditul
anterior, ca două rulări simultane să nu importe același atașament de două ori.

### Setup Steps
1. activează IMAP în contul de email;
2. generează o parolă de aplicație dacă furnizorul o cere;
3. adaugă cutia din *Administrare → Surse documente*.

### Renewal / Expiration
Parola de aplicație se poate revoca de la furnizor.

### Billing
Nu, dincolo de contul de email.

### Data Sent
Comenzi IMAP. Nu se trimite conținut.

### Data Received
Mesaje și atașamente.

### Failure Impact
Documentele nu mai sosesc de pe email. Ecranul spune de ce.

### Recovery
Automată; UID-ul ține minte unde a rămas.

---

## 6. Server SMTP

### Purpose
Trimiterea solicitărilor de documente către clienți, a linkurilor de încărcare, a
memento-urilor și a rezumatului zilnic către cabinet.

### Provider
Oricare server SMTP: cel al găzduirii, Microsoft 365, Google Workspace, sau un
serviciu tranzacțional (SendGrid, Mailgun, Postmark) — codul folosește SMTP
standard, deci oricare dintre ele merge fără modificări.

### Integration Type
SMTP cu STARTTLS (implicit, port 587) sau SMTPS (port 465).

### Used By
`backend/app/services/mail/` (`smtp.py`, `disabled.py`, `base.py`),
`document_request.py`, `reminders.py`, `daily_digest.py`.

### Environment Variables
```text
NOTIFICATIONS_ENABLED
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
SMTP_FROM
SMTP_STARTTLS
DAILY_DIGEST_ENABLED
CLIENT_REMINDERS_ENABLED
```

### Account Required
Da.

### Account Type
O cutie poștală sau un cont de serviciu tranzacțional.

### Credentials Required
Gazdă, port, utilizator, parolă.

### Webhooks
Nu.

### Production URL / Endpoint
Gazda o dă furnizorul.

### Sandbox/Test Environment
Fără `SMTP_HOST`, aplicația folosește `services/mail/disabled.py`, care **spune**
că trimiterea nu este configurată în loc să pretindă că a trimis.

### Production Verification Status
`NOT VERIFIED — CREDENTIALS REQUIRED`

Ce **s-a** verificat (`test_mail.py`, `test_daily_digest.py`): compunerea
mesajelor, adresele, șabloanele, comportamentul la eșec, și că un memento nu
pleacă de două ori (blocare per organizație).

### Setup Steps
1. pune `SMTP_*`;
2. pune `NOTIFICATIONS_ENABLED=true` — comutatorul principal, oprit implicit, ca
   o bază de test importată să nu scrie clienților adevărați;
3. configurează **SPF, DKIM și DMARC** pe domeniul expeditor, altfel mesajele
   ajung în spam;
4. trimite un test către o adresă a cabinetului înainte de a scrie unui client.

### Renewal / Expiration
Parola de aplicație, dacă furnizorul o cere.

### Billing
Depinde de furnizor.

### Data Sent
Adresa clientului, numele lui, luna, lista documentelor lipsă, linkul de
încărcare. **Nu se trimit documente ca atașament.**

### Data Received
Nimic. Nu există procesare a răspunsurilor (bounce-uri).

### Failure Impact
Solicitările și memento-urile nu pleacă. Ecranul spune că trimiterea nu este
configurată.

### Recovery
Manuală: se reîncearcă din ecranul de remindere.

---

## 7. Anthropic — citirea documentelor fotografiate

### Purpose
Extragerea datelor din **poze și scanuri**, adică din documentele fără strat de
text. PDF-urile emise de un ERP se citesc **local**, fără rețea (ADR-005).

### Provider
Anthropic.

### Integration Type
REST (HTTP direct, fără SDK).

### Used By
`backend/app/services/extraction/vision.py` și `hybrid.py`.

### Environment Variables
```text
OCR_PROVIDER
AI_PROVIDER
AI_API_KEY
AI_MODEL
PROMPT_VERSION
CONFIDENCE_AUTO_THRESHOLD
CONFIDENCE_REVIEW_THRESHOLD
```

### Account Required
Numai dacă `OCR_PROVIDER` este `vision` sau `hybrid`. Pe `local` — **nu**.

### Account Type
Cont Anthropic Console cu credit.

### Credentials Required
`AI_API_KEY`.

### Webhooks
Nu.

### Production URL / Endpoint
Confirmat din cod: `https://api.anthropic.com/v1/messages` (versiune API
`2023-06-01`).

### Sandbox/Test Environment
Nu. `OCR_PROVIDER=mock` produce date sintetice și este **refuzat în producție**.

### Production Verification Status
`NOT VERIFIED — CREDENTIALS REQUIRED`

Ce se verifică **fără nicio cheie**, fiindcă nu are nevoie de model: citirea
locală a PDF-urilor cu text (`test_extraction_pdf_text.py`) — calea implicită și
recomandată. Ce este verificat pe un dublu (`test_extraction_vision.py`):
trimiterea, limita de mărime a imaginii, plafonul de tokeni, răspunsurile
incomplete, și plafonarea încrederii sub pragul de aprobare, ca nimic citit de un
model să nu se aprobe singur.

### Setup Steps
1. cont pe console.anthropic.com, cu credit;
2. `AI_API_KEY`;
3. `OCR_PROVIDER=hybrid` — local întâi, model doar unde nu e nimic de citit;
4. `AI_PROVIDER=anthropic`.

Fără cheie, `OCR_PROVIDER=vision|hybrid` **oprește pornirea în producție**.

### Renewal / Expiration
Cheia nu expiră singură; se revocă din consolă.

### Billing
**Da, pe utilizare.** Costul unei cereri este mărginit de `MAX_TOKENS` (4000).
Nu există un plafon zilnic în aplicație — dacă cabinetul îl vrea, se pune în
contul furnizorului.

### Data Sent
**Imaginea documentului** (poză sau scan) și instrucțiunea de extragere. Adică
documente contabile ale clienților părăsesc sediul. Este o decizie pe care
cabinetul o ia explicit; implicit rămâne `local`, care nu trimite nimic.

### Data Received
Câmpurile citite, cu scoruri de încredere.

### Failure Impact
Pozele rămân necitite și ajung la verificare cu câmpurile goale. PDF-urile cu
text se citesc mai departe, local.

### Recovery
Reprocesare, din ecranul documentului.

---

## 8. Anthropic — asistentul din aplicație (opțional, separat)

### Purpose
Răspunsuri la întrebări despre datele cabinetului („ce lipsește la clientul X").

### Provider
Anthropic.

### Integration Type
REST.

### Used By
`backend/app/services/assistant/language_model.py`.

### Environment Variables
```text
ASSISTANT_PROVIDER
ASSISTANT_API_KEY
ASSISTANT_MODEL
ASSISTANT_MAX_TOOL_ROUNDS
```

### Account Required
Numai dacă `ASSISTANT_PROVIDER=anthropic`. Implicit este `rules`, care răspunde
din unelte deterministe, **fără nicio credențială și fără să trimită nimic**.

### Account Type
Cont Anthropic Console.

### Credentials Required
`ASSISTANT_API_KEY`.

**Este o variabilă separată de `AI_API_KEY`, deliberat:** un cabinet poate vrea un
asistent care răspunde la întrebări fără ca documentele clienților să plece
nicăieri. Aceeași cheie se poate pune în amândouă, dar alegerea rămâne a lui.

### Webhooks
Nu.

### Production URL / Endpoint
`https://api.anthropic.com/v1/messages`.

### Sandbox/Test Environment
`ASSISTANT_PROVIDER=rules` — funcțional, fără cont.

### Production Verification Status
`NOT VERIFIED — CREDENTIALS REQUIRED` pentru motorul cu model.
Motorul `rules` este **verificat rulând**, inclusiv limita de 20 de întrebări pe
minut per utilizator.

### Setup Steps
Opțional. Fără cheie, `ASSISTANT_PROVIDER=anthropic` oprește pornirea în
producție — ca nimeni să nu creadă că modelul răspunde când, de fapt, răspund
regulile.

### Renewal / Expiration
Se revocă din consolă.

### Billing
Da, pe utilizare, dacă este pornit.

### Data Sent
Întrebarea și rezultatele uneltelor chemate — nu documente.

### Data Received
Răspunsul în text.

### Failure Impact
Asistentul nu răspunde. Nimic altceva.

### Recovery
Imediată.

---

## 9. WhatsApp

### Purpose
Clientul trimite pozele bonurilor pe WhatsApp.

### Provider
Niciunul. **Nu există integrare.**

### Integration Type
`NOT IMPLEMENTED`.

Ce există: un **link** `https://wa.me/<număr>?text=...`
(`frontend/src/lib/whatsapp.ts`), care deschide conversația în aplicația
WhatsApp a utilizatorului, cu mesajul scris dinainte. Nu este un API, nu cere
cont și nu trimite nimic prin server.

Documentele primite pe WhatsApp se încarcă **manual**, cu proveniența declarată —
vezi [DOCUMENT_PROCESSING.md](DOCUMENT_PROCESSING.md).

### Environment Variables
`.env.example` enumeră `WHATSAPP_PROVIDER`, `WHATSAPP_TOKEN`,
`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`
— **toate marcate `NEIMPLEMENTAT`** și necitite de niciun modul. Marcajul este
verificat de un test (`test_env_example_contract.py`).

### Account Required
**Nu.** Nu deschide un cont Meta Business pentru asta.

### Production Verification Status
`NOT IMPLEMENTED`

### Setup Steps
Niciunul azi. Pentru preluare automată ar fi nevoie de un cont WhatsApp Business
și un număr aprobat de Meta — o înregistrare de firmă, nu o setare.

### Failure Impact
Niciunul.

---

## 10. SAGA

### Purpose
Predarea datelor către programul de contabilitate al cabinetului.

### Provider
SAGA Software.

### Integration Type
`NOT IMPLEMENTED` — deliberat.

### Used By
Nimic. Nu există cod de conversie.

### Environment Variables
Niciuna.

### Account Required
Nu, pentru aplicație. Cabinetul are deja SAGA.

### Production Verification Status
`NOT IMPLEMENTED`

### Setup Steps
Ce lipsește ca să se poată face: **un fișier real exportat din SAGA** de la
cabinet, sau documentația formatului de import de la producător. Formatul nu este
public, iar unul ghicit ar produce fișiere care se încarcă și pun cifre greșite
în contabilitate — cel mai scump fel de eșec, fiindcă nu se vede. Vezi
[SAGA.md](SAGA.md).

### Ce există în loc, și este util imediat
`GET /api/v1/reports/register.csv` — registrul lunii, un rând pe document, în
formatul pe care Excel-ul românesc îl deschide corect (separator `;`, BOM, CRLF,
virgulă zecimală).

---

## 11. Găzduirea aplicației

### Purpose
Rularea API-ului, a workerului și a frontendului.

### Provider
Oricare. `docker-compose.yml` ridică stiva întreagă (Postgres, migrări, backend,
worker). `frontend/vercel.json` există pentru varianta de **demonstrație** —
build cu `VITE_API_MODE=mock`, adică fără backend deloc.

### Integration Type
Containere, sau procese pe un server.

### Environment Variables
```text
ENVIRONMENT
PUBLIC_BASE_URL
CORS_ALLOWED_ORIGINS
SECRET_KEY
TRUSTED_PROXY_COUNT
BACKEND_PORT
LOG_LEVEL
DEFAULT_TIMEZONE
```

### Account Required
Da.

### Credentials Required
Accesul la platformă.

### Production URL / Endpoint
`PUBLIC_BASE_URL` — adresa reală a instalării. Linkurile trimise clienților se
compun cu ea; lăsată pe `localhost`, **pornirea în producție se oprește**.

### Production Verification Status
`NOT VERIFIED — PROVIDER ACCESS REQUIRED` — nu există încă o instalare de
producție. Stiva Docker și pornirea sunt verificate local.

### Setup Steps
Vezi [DEPLOY.md](DEPLOY.md) și
[PRODUCTION_LAUNCH_CHECKLIST.md](PRODUCTION_LAUNCH_CHECKLIST.md).

### Renewal / Expiration
**Certificatul TLS** al domeniului — reînnoire automată dacă folosești Let's
Encrypt sau platforma o face singură.

### Billing
Da.

---

## 12. Planificatorul (cron)

### Purpose
Pornește turele de sincronizare, memento-urile și rezumatul zilnic.

### Provider
Cron-ul sistemului, planificatorul platformei, sau orice serviciu care poate
chema o adresă HTTP la interval.

### Integration Type
HTTP GET către rutele interne, cu un secret în antet.

### Used By
`backend/app/api/v1/internal.py`: `/run-queue`, `/daily-digest`, `/reminders`.

### Environment Variables
```text
CRON_SECRET
```

### Account Required
Nu, dacă folosești cron-ul serverului.

### Credentials Required
`CRON_SECRET`. **Gol înseamnă oprit**: rutele refuză orice, inclusiv o cerere
corectă. Fără secret ele răspund **404, nu 401** — un 401 ar confirma că ruta
există.

### Webhooks
Rutele interne **sunt** un fel de webhook de intrare, dar se cheamă de un
planificator al cabinetului, nu de un furnizor extern.

### Production Verification Status
**Verificat rulând**: rutele, secretul, refuzul fără el, și izolarea per
organizație.

### Setup Steps
1. generează `CRON_SECRET`;
2. programează apelurile — intervalele recomandate în [DEPLOY.md](DEPLOY.md).

### Failure Impact
Nimic nu se mai preia automat și memento-urile nu pleacă. **Nu se vede pe niciun
ecran** dacă nimeni nu se uită: vezi capitolul de monitorizare din
[PRODUCTION_LAUNCH_CHECKLIST.md](PRODUCTION_LAUNCH_CHECKLIST.md).

---

## 13. GitHub (dezvoltare, nu producție)

### Purpose
Cod și integrare continuă.

### Provider
GitHub.

### Integration Type
Git + GitHub Actions.

### Used By
`.github/workflows/ci.yml`.

### Account Required
Da, pentru dezvoltare. **Aplicația în funcțiune nu depinde de el.**

### Production Verification Status
`NOT APPLICABLE` pentru rulare; CI-ul este verificat la fiecare push.

### Failure Impact
Niciunul asupra unei instalări care rulează.

---

## Ce **nu** folosește aplicația

Verificat prin căutare în tot codul, ca nimeni să nu deschidă conturi degeaba:

- **niciun serviciu de plăți** — nu există integrare de plată;
- **niciun serviciu de analytics sau telemetrie** — nicio urmă către un terț;
- **niciun CDN, font extern sau script din afară** în frontend;
- **niciun Redis / broker de mesaje** — coada este un tabel PostgreSQL
  (`document_processing_jobs`), deliberat (ADR-003);
- **niciun serviciu de monitorizare** — `SENTRY_DSN` și
  `OTEL_EXPORTER_OTLP_ENDPOINT` există în `.env.example` **marcate
  `NEIMPLEMENTAT`** și nu sunt citite de niciun modul;
- **niciun OCR extern în afară de Anthropic** — nu există cod pentru Google
  Vision, AWS Textract sau Azure;
- **niciun furnizor de model în afară de Anthropic** — `openai` și
  `azure_openai` au stat enumerate în `.env.example` fără să existe în cod;
  câmpul are de acum un validator care oprește pornirea la o valoare
  neimplementată.
