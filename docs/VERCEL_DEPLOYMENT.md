# Deploy pe Vercel

Cum se pune **aplicația reală** pe Vercel: arhitectură, ce trebuie procurat
înainte, variabile, migrări, cron, rollback.

Pentru varianta de demonstrație (fără backend, fără bază de date), vezi
secțiunea corespunzătoare din [DEPLOY.md](DEPLOY.md). Cele două sunt **proiecte
Vercel diferite** și nu au voie să se amestece.

> **Stare la data acestui document: deploy-ul de producție nu a fost executat.**
> Lipsesc PostgreSQL, stocarea S3 și domeniul. Ce urmează este procedura
> verificată pe cod și configurare; ce nu s-a putut rula este marcat ca atare în
> [VERCEL_DEPLOYMENT_REPORT.md](VERCEL_DEPLOYMENT_REPORT.md).

---

## Arhitectura

```
                          Vercel (un singur proiect)
   utilizator ──▶ ┌────────────────────────────────────┐
                  │  /api/*  →  serviciul „backend"    │──▶ PostgreSQL (extern)
                  │             FastAPI, app.main:app  │──▶ S3 (extern)
                  ├────────────────────────────────────┤
                  │  /*      →  serviciul „frontend"   │
                  │             Vite, static           │
                  └────────────────────────────────────┘
                          Vercel Cron ──▶ /api/v1/internal/run-queue
```

Un proiect, două servicii, **aceeași origine**. Configurarea stă în
`vercel.json` de la rădăcina repo-ului și folosește cheia `services`, care este
sintaxa curentă Vercel pentru mai multe servicii într-un proiect.

**Root Directory rămâne rădăcina repo-ului**, nu `frontend/`: serviciile își
declară singure rădăcinile.

### De ce aceeași origine

Sesiunea trăiește într-un cookie `HttpOnly` cu `SameSite=Lax`. Un cookie `Lax`
**nu însoțește cererile pornite de `<img>` sau `<object>`** de pe altă origine:
cu API-ul pe alt domeniu, autentificarea ar merge și **previzualizarea
documentelor ar returna 401** — un defect care nu apare în niciun test și se vede
abia când cineva deschide o factură.

De aceea frontendul nu primește `VITE_API_BASE_URL`: folosește calea relativă
`/api/v1`, care este exact ce trebuie.

---

## Ce trebuie procurat înainte

Vercel rulează codul. **Nu ține nici baza de date, nici documentele.**

| Ce | De ce nu poate fi pe Vercel | Recomandare |
|---|---|---|
| **PostgreSQL 17** | funcțiile sunt fără stare | Neon, Supabase, RDS — orice PostgreSQL 17 accesibil public, cu TLS |
| **Stocare S3** | **filesystemul funcției dispare între cereri** | Cloudflare R2, Supabase Storage, AWS S3 |
| **Domeniu + TLS** | cookie-urile sunt `Secure` în producție | orice registrar; TLS îl face Vercel |
| **Monitor extern** | aplicația nu alertează singură | vezi [PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md) |

### Stocarea: regula care nu se negociază

Pe Vercel, fiecare invocare primește un filesystem propriu, aruncat la final.
`STORAGE_PROVIDER=local` acolo **nu eșuează zgomotos**: scrierea în `/tmp`
reușește, documentul primește rând în baza de date și apare pe ecran. Abia la
invocarea următoare fișierul nu mai există — iar atunci există deja un rând care
spune că există.

De aceea aplicația **refuză să pornească** pe o platformă cu filesystem efemer
dacă `STORAGE_PROVIDER` nu este `s3`. Verificarea rulează **indiferent de
`ENVIRONMENT`**, fiindcă discul este efemer oricum l-am numi
(`assert_storage_is_persistent`, `backend/tests/test_ephemeral_storage_guard.py`).

### Baza de date: poolerul

Funcțiile serverless apar și dispar odată cu cererile. Dacă `DATABASE_URL` arată
către un pooler în mod tranzacție (PgBouncer, Supabase pe `:6543`, Neon pooled),
pune:

```text
DB_EXTERNAL_POOLER=true
```

Fără el se rup tăcut două lucruri: instrucțiunile pregătite (sesiunea din spate
se schimbă între cereri) și rostul poolului propriu.

---

## Pasul 1 — proiectul Vercel

1. Instalează **Vercel GitHub App** pentru repo: https://github.com/apps/vercel
2. [vercel.com/new](https://vercel.com/new) → *Import Git Repository* →
   `volocandrei/contacrm`
3. **Root Directory: rădăcina repo-ului** (nu `frontend/`)
4. Restul vine din `vercel.json`. Nu suprascrie build command-ul.

## Pasul 2 — variabilele de mediu

Se pun în *Project Settings → Environment Variables*, pentru **Production**.
Numele complete și explicate:
[PRODUCTION_ENVIRONMENT_VARIABLES.md](PRODUCTION_ENVIRONMENT_VARIABLES.md).

**Fără acestea pornirea se oprește** (`assert_production_ready`):

```text
ENVIRONMENT=production
DATABASE_URL
SECRET_KEY                  # >= 32 caractere, generat pentru ACEASTA instalare
PUBLIC_BASE_URL             # https://domeniul-real — nu preview, nu localhost
CORS_ALLOWED_ORIGINS        # aceeasi origine; `*` este refuzat de validator
OCR_PROVIDER=local          # `mock` este refuzat in productie
STORAGE_PROVIDER=s3         # `local` este refuzat pe Vercel
S3_BUCKET
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
S3_ENDPOINT_URL             # gol = AWS; adresa furnizorului pentru R2/Supabase
```

**Necesare pentru funcționare completă:**

```text
DRIVE_TOKEN_KEY             # cripteaza tokenurile integrarilor
CRON_SECRET                 # gol = rutele interne refuza orice
DEFAULT_TIMEZONE=Europe/Bucharest
TRUSTED_PROXY_COUNT=1       # Vercel este proxy-ul din fata
DB_EXTERNAL_POOLER=true     # daca DATABASE_URL arata catre un pooler
WORKER_HEARTBEAT_TIMEOUT_SECONDS=90
```

**Frontend, la build:**

```text
VITE_API_MODE=http
```

Cum se generează cele trei secrete:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"                  # SECRET_KEY, CRON_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # DRIVE_TOKEN_KEY
```

> `TRUSTED_PROXY_COUNT=1`: fără el, jurnalul de audit notează adresa platformei
> la fiecare acțiune, **și limitarea autentificării ar număra toate încercările
> la aceeași adresă** — adică ar bloca tot cabinetul la câteva parole greșite.

## Pasul 3 — migrările

Vercel **nu** rulează migrări. Se rulează o singură dată, de pe mașina ta, către
baza de producție, **înainte** de primul deploy:

```bash
cd backend
DATABASE_URL="postgresql+psycopg://..." uv run alembic upgrade head
DATABASE_URL="postgresql+psycopg://..." uv run alembic current   # trebuie: head
```

Niciodată `create_all()`. La fiecare release cu migrări noi, se repetă pasul
**înainte** de a promova versiunea.

## Pasul 4 — primul administrator

Tot de pe mașina ta, către baza de producție:

```bash
cd backend
DATABASE_URL="postgresql+psycopg://..." uv run python -m app.cli sync-roles
DATABASE_URL="postgresql+psycopg://..." uv run python -m app.cli create-admin
```

Parola se cere la tastatură și trece prin politica completă a aplicației. Nu
există parolă implicită și nicio cale prin interfață de a crea primul cont.

## Pasul 5 — preview, apoi producție

**Întâi preview.** Fiecare push pe o ramură produce un preview. Verifică-l cu
lista din [PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md).

> **Atenție la `PUBLIC_BASE_URL` în preview:** linkurile trimise clienților se
> compun cu el. Într-un preview, pune-l pe URL-ul de preview **și nu trimite
> mesaje reale** — sau lasă `NOTIFICATIONS_ENABLED=false`.

Producția se face prin push pe `main` (sau `vercel deploy --prod`).

## Pasul 6 — domeniul

*Project Settings → Domains*. După ce domeniul e activ:

- `PUBLIC_BASE_URL=https://domeniul-real`
- `CORS_ALLOWED_ORIGINS=https://domeniul-real`
- actualizează `MS_REDIRECT_URI` și `ANAF_REDIRECT_URI` **și la furnizor**

Domeniul **nu** se scrie nicăieri în cod. Un URL temporar de Vercel lăsat în
`PUBLIC_BASE_URL` produce linkuri care mor la următorul deploy.

---

## Cron

`vercel.json` declară:

```json
"crons": [{ "path": "/api/v1/internal/run-queue", "schedule": "*/5 * * * *" }]
```

Vercel trimite `Authorization: Bearer <CRON_SECRET>` — exact ce așteaptă ruta.
Fără secret, ruta răspunde **404**, nu 401: un 401 ar confirma că ruta există.

Un tur face muncă **mărginită**, deliberat: 5 documente din coadă, 3 fișiere per
sursă externă. Ce nu apucă rămâne în coadă pentru turul următor —
`document_processing_jobs` este durabil, nu memorie.

`maxDuration: 60` este declarat pentru serviciul de backend. Dacă un tur
depășește, jobul rămâne `PENDING` și se reia; nimic nu se pierde.

### Ce NU acoperă cronul

| Sarcină | Pe Vercel |
|---|---|
| coada de procesare | **da**, prin cron la 5 minute |
| sincronizarea surselor externe | **da**, în același tur |
| rezumatul zilnic | **de adăugat** un cron pe `/api/v1/internal/daily-digest` |
| memento-urile | **de adăugat** un cron pe `/api/v1/internal/reminders` |
| workerul continuu | **nu există** pe Vercel — vezi mai jos |

## Workerul

Aplicația poate rula workerul în două feluri:

1. **proces continuu** (`python -m app.worker`) — pe un server obișnuit;
2. **tur cerut din afară** (`--once`, sau ruta de cron) — pe Vercel.

**Pe Vercel funcționează varianta a doua, și este suficientă.** Nu încerca să
ții un proces viu într-o funcție: nu supraviețuiește răspunsului.

Consecință de operare: **semnul de viață al workerului bate la fiecare tur de
cron**, deci `/health/workers` rămâne un semnal valid și pe Vercel. Cu cron la 5
minute, pune `WORKER_HEARTBEAT_TIMEOUT_SECONDS` peste intervalul cronului —
`400` (≈ 6–7 minute) este o valoare potrivită; implicitul de 90 de secunde este
pentru un worker continuu și ar da alarme false.

> Încărcarea unui document programează procesarea și printr-un `BackgroundTask`.
> Pe Vercel acela **poate să nu ruleze** — funcția e înghețată după răspuns. Nu
> este o problemă: rândul `PENDING` s-a scris deja în aceeași tranzacție cu
> documentul, iar cronul îl ia. Exact pentru asta coada este un outbox.

---

## Copiile de siguranță

**Vercel nu este o copie de siguranță.** Nu ține nici baza, nici documentele.

Procedura rămâne cea din [RUNBOOK.md](RUNBOOK.md), executată împotriva bazei și a
bucketului:

1. `pg_dump` al bazei externe (T1);
2. copierea/versionarea bucketului S3 (T2 > T1);
3. restaurare, apoi `check-storage` — **fără el, restaurarea nu este terminată**.

Pentru S3, pasul 2 este versionarea bucketului sau o replicare, cu aceeași regulă
de ordine.

---

## Rollback

**Aplicația:** *Deployments* → deployment-ul anterior bun → **Promote to
Production**. Instant, fără build.

**Baza de date — separat, și nu automat.** Vezi tabelul pe tipuri de migrare din
[PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md). Pe scurt: o migrare
care adaugă o tabelă sau o coloană nullable **nu se dă înapoi** (versiunea veche
o ignoră); una care șterge ceva **nu se poate da înapoi** — se restaurează din
copie.

**Stocarea:** documentele urcate după deploy rămân în bucket. Dacă restaurezi
baza la o stare anterioară, `check-storage` le va raporta ca fișiere în plus —
inofensive.

---

## Verificări după deploy

Pe lângă lista din [PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md),
trei verificări specifice Vercel:

```bash
# 1. API-ul raspunde de pe aceeasi origine
curl -sS https://domeniul-real/api/v1/health/ready

# 2. Workerul: dupa primul tur de cron trebuie sa devina 200
curl -sS https://domeniul-real/api/v1/health/workers

# 3. Rutele interne sunt inchise fara secret
curl -s -o /dev/null -w "%{http_code}" https://domeniul-real/api/v1/internal/run-queue
# trebuie: 404
```

### Verificarea care prinde cea mai periculoasă greșeală

**Autentifică-te cu o parolă greșită.** Trebuie să fii refuzat.

Dacă intri, frontendul a fost construit în modul **demonstrație**
(`VITE_API_MODE=mock`): backendul simulat din browser acceptă orice parolă și
lucrează pe date inventate. Aplicația arată identic. Singurele semne sunt banda
de demonstrație din capul paginii și faptul că orice parolă intră.

Cauza obișnuită: proiectul a fost importat cu Root Directory = `frontend/`, deci
a folosit `frontend/vercel.json`, al cărui `buildCommand` fixează `mock`
deliberat. **Root Directory trebuie să fie rădăcina repo-ului.**

### Ce trebuie să lipsească din jurnale

*Deployments → Runtime Logs*. Nu au voie să apară: parole, tokenuri, chei,
conținut de documente, `postgresql://`. Fiecare linie poartă `request_id`.

---

## Limitări cunoscute pe Vercel

| Limitare | Consecință | Ce se face |
|---|---|---|
| Filesystem efemer | documentele **trebuie** să stea pe S3 | garda oprește pornirea cu `local` |
| Fără proces continuu | workerul rulează doar prin cron | interval de 5 minute; coada este durabilă |
| Interval minim de cron | latență de până la 5 minute la procesare | acceptabil pentru un cabinet |
| `maxDuration` | un tur lung se poate întrerupe | lucrul este mărginit; ce rămâne se reia |
| Fără migrări automate | `alembic upgrade head` se rulează manual | pasul 3, înainte de fiecare promovare |
| Deploy cu întrerupere | 5–15 minute la release cu migrări | fereastră anunțată |
