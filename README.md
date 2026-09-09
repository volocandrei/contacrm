# ContaCRM

CRM + management de documente pentru cabinete de contabilitate.

Documentele clienților ajung din mai multe locuri — încărcate de operator,
trimise de client printr-un link, luate de pe email sau din OneDrive, descărcate
din SPV-ul ANAF — și trec toate prin același drum: identificarea clientului,
citirea datelor, verificarea de către un om, arhivarea. Plus ce ține de asta:
termenele de depunere, extrasele bancare, rapoartele și jurnalul de audit.

> **Pornești pe o mașină nouă?** [`docs/STATUS.md`](docs/STATUS.md)
> **Pui aplicația în producție?** [`docs/README.md`](docs/README.md) — indexul
> documentației, cu ce fișier răspunde la ce întrebare.

## Stare curentă

| Componentă | Stare |
|---|---|
| Plan tehnic, schemă DB, riscuri, ADR-uri | ✅ `docs/ARCHITECTURE.md`, `docs/adr/` |
| Frontend: Vite + React 19 + TS strict + Tailwind v4 | ✅ |
| Shell aplicație: sidebar colapsabil (§51), topbar, temă persistată | ✅ |
| Ecrane: panou principal, clienți, documente, verificare, perioade, sarcini, rapoarte, administrare | ✅ pe date sintetice |
| Backend simulat în browser (`api/mock`), cu aceleași rute ca API-ul real | ✅ |
| Backend M2: FastAPI, settings, logging structurat, erori, health, Alembic | ✅ `backend/` |
| Backend M3: auth JWT + refresh rotativ, Argon2id, RBAC, audit log | ✅ `backend/app/services/auth.py` |
| Backend M4: CRM — clienți, contacte, note, etichete, sarcini | ✅ `backend/app/api/v1/clients.py` |
| Backend M5–M6: documente, stocare, procesare, verificare, arhivare, perioade, audit | ✅ `backend/app/services/` |
| Backend M7–M8: rapoarte, setări reale, extracție din PDF și e-Factura, CI, teste E2E | ✅ |
| Backend M9–M10: preluare automată din OneDrive/SharePoint și din email | ✅ `backend/app/services/microsoft/` |
| Backend M11: e-Factura — preluarea din SPV-ul ANAF, cu toate trei fișierele | ✅ `backend/app/services/anaf/` |
| Infrastructură dev: PostgreSQL + API + worker prin Docker | ✅ `docker-compose.yml` |

## Rulare

### Frontend

```bash
cd frontend && npm install && npm run dev
```

Pornește pe http://localhost:5173. Implicit rulează pe backend-ul simulat
(`VITE_API_MODE=mock`), deci nu are nevoie de nimic altceva.

### Backend

Are nevoie de un PostgreSQL 17. Prin Docker:

```bash
docker compose up -d                        # doar postgres
cd backend && uv sync
uv run alembic upgrade head
uv run python -m app.cli seed-dev           # organizație + conturi de development
uv run uvicorn app.main:app --reload        # http://localhost:8000
```

Conturile de development au parola `contacrm-dev` (`admin@contacrm.test`,
`contabil@`, `operator@`, `verificator@`).

Dacă Docker nu pornește — pe Windows ARM64 nu ridică engine-ul — un PostgreSQL
nativ merge la fel de bine:

```bash
winget install --id PostgreSQL.PostgreSQL.17 --silent \
  --custom "--superpassword contacrm_dev_password --serverport 5432"
psql -U postgres -c "CREATE ROLE contacrm LOGIN PASSWORD 'contacrm_dev_password' CREATEDB;"
psql -U postgres -c "CREATE DATABASE contacrm OWNER contacrm;"
```

Sau totul în containere:

```bash
docker compose --profile api up -d --build
```

Ca frontend-ul să vorbească cu API-ul real, în loc de cel simulat:

```bash
# frontend/.env.local
VITE_API_MODE=http
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

### Verificări

```bash
cd frontend && npm test && npm run lint && npm run build
cd backend  && uv run pytest && uv run ruff check . && uv run mypy app
```

## Rute disponibile

| Rută | Conținut |
|---|---|
| `/` | Panou principal — KPI, documente recente, „necesită atenție", perioade, activitate |
| `/crm/clienti`, `/crm/clienti/:id`, `/crm/contacte`, `/crm/sarcini` | CRM |
| `/documente/inbox`, `/procesare`, `/verificare`, `/verificare/:id`, `/arhiva` | Documente și ecranul de verificare |
| `/contabilitate/perioade`, `/contabilitate/lipsa` | Perioade contabile și documente lipsă |
| `/comunicare/mesaje`, `/sabloane`, `/remindere` | Comunicare |
| `/rapoarte` | Agregări peste documente |
| `/administrare/utilizatori`, `/roluri`, `/setari`, `/audit` | Administrare |

## Pentru producție

Aplicația este pregătită să ruleze pe date reale ale unui cabinet. Documentația
operațională, în ordinea în care se citește:

| Întrebare | Fișier |
|---|---|
| Ce conturi îmi trebuie? | [`docs/PRODUCTION_SETUP_ACCOUNTS.md`](docs/PRODUCTION_SETUP_ACCOUNTS.md) |
| Ce trebuie să fie adevărat înainte de primul client? | [`docs/PRODUCTION_LAUNCH_CHECKLIST.md`](docs/PRODUCTION_LAUNCH_CHECKLIST.md) |
| Ce fac în ziua deployului? | [`docs/PRODUCTION_RELEASE_GATE.md`](docs/PRODUCTION_RELEASE_GATE.md) |
| Ce servicii externe folosește, exact? | [`docs/PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md`](docs/PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md) |
| Ce monitorizare trebuie configurată? | [`docs/PRODUCTION_MONITORING.md`](docs/PRODUCTION_MONITORING.md) |
| Ceva s-a stricat. Ce fac? | [`docs/PRODUCTION_INCIDENT_RUNBOOK.md`](docs/PRODUCTION_INCIDENT_RUNBOOK.md) |
| Este gata de lansare? | [`docs/FINAL_PRODUCTION_BUILD.md`](docs/FINAL_PRODUCTION_BUILD.md) |

Indexul complet: [`docs/README.md`](docs/README.md).

## Integrări

Fiecare este opțională: fără ea, ecranul ei **spune că nu este configurată** — nu
se oferă și apoi eșuează. Aplicația este utilă și fără niciuna.

| Integrare | Ce face | Stare de verificare |
|---|---|---|
| PostgreSQL 17 | baza de date | verificat rulând |
| Stocare pe disc / S3 | fișierele documentelor | disc verificat rulând; S3 pe dublu |
| Microsoft Graph | OneDrive/SharePoint **și** email, un singur consimțământ | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| IMAP | cutie poștală obișnuită, alternativă la Graph | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| SMTP | solicitări și memento-uri către clienți | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| ANAF / SPV | **descărcarea** facturilor electronice | `NOT VERIFIED — PROVIDER ACCESS REQUIRED` |
| Anthropic | citirea pozelor și scanurilor (PDF-urile cu text se citesc local) | `NOT VERIFIED — CREDENTIALS REQUIRED` |

„Verificat rulând" înseamnă rulat împotriva lucrului real. Restul au cod și teste
pe un dublu scris după documentație — ceea ce **nu** este același lucru. Detalii:
[`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

## Ce NU face, deliberat

Ca să nu deschizi conturi degeaba și să nu aștepți funcții care nu vin:

| | De ce |
|---|---|
| **Nu depune** declarații la ANAF | descarcă facturi din SPV; nu trimite nimic |
| **Nu calculează** TVA, totaluri, sume | le **citește** de pe document; un total pus de sistem ar arăta identic cu unul citit |
| **Nu are API de WhatsApp** | butonul deschide `wa.me` pe telefon; preluarea automată ar cere cont WhatsApp Business și număr aprobat de Meta |
| **Nu exportă în SAGA** | formatul de import nu este public; unul ghicit ar pune cifre greșite în contabilitate |
| **Nu se leagă** la bănci | extrasele se încarcă din fișier (CSV din internet banking) |
| **Nu șterge** nimic automat | nicio retenție automată; ce se păstrează și cât este decizia cabinetului |
| **Nu aprobă** documente singură | nici peste pragul de încredere |
| **Nu trimite** alerte singură | expune `/health/ready` și `/health/workers`; monitorul este extern |
| **Nu folosește** Redis, Sentry, analytics, plăți, OpenAI, Twilio, AWS Textract | verificat prin căutare în tot codul |

## Structură

```
CONTACRM/
├── frontend/
│   └── src/
│       ├── api/            # client, endpoints, hooks + mock/ (backend simulat)
│       ├── components/
│       │   ├── layout/     # app-shell, app-sidebar
│       │   ├── page.tsx    # PageHeader, Panel, stările de încărcare/eroare/gol
│       │   └── form-controls.tsx
│       ├── features/       # un folder per modul: auth, clients, documents, …
│       ├── hooks/          # use-theme, use-filter-params
│       ├── lib/            # navigation, format, filename, utils(cn)
│       └── types/          # statusuri și tipuri de domeniu (§53)
├── backend/                # FastAPI — vezi backend/README.md
│   ├── app/{api,core,models,schemas,services,repositories,domain}/
│   ├── alembic/versions/
│   └── tests/
├── docs/
│   ├── ARCHITECTURE.md     # arhitectură, schemă DB, riscuri, roadmap
│   ├── DEPLOY.md           # punerea în funcțiune
│   ├── RUNBOOK.md          # operare, copii de siguranță, restaurare, incidente
│   ├── STATUS.md           # starea proiectului, pornire pe o mașină nouă
│   ├── FINAL_PRODUCTION_AUDIT.md   # audit de producție (2 runde, defecte + verdict)
│   ├── ULTIMATE_APPLICATION_FUNCTIONAL_AUDIT.md
│   ├── CREDENTIALE.md      # ce credențiale se adună și de la cine
│   ├── SAGA.md
│   └── adr/                # ADR-001 … ADR-010
├── docker-compose.yml      # postgres (+ migrate, backend, worker pe profilul `api`)
├── .env.example            # toate variabilele de configurare (fără valori reale)
└── .claude/launch.json
```

## Adăugarea de componente shadcn/ui

Aplicația scrie Tailwind brut. Primitivele generate (`button`, `card`, `badge`,
`separator`) au fost scoase la auditul de producție: nimic nu le importa, iar
cinci dependențe existau doar pentru ele. `components.json` rămâne configurat
(style `new-york`, base color `neutral`, alias `@/components/ui`), deci se pot
aduce înapoi oricând chiar sunt necesare:

```bash
cd frontend && npx shadcn@latest add table dialog dropdown-menu select
```

## Convenții

- Limba implicită a interfeței: **română**. Afișare dată `DD.MM.YYYY`, API în ISO 8601,
  fus orar `Europe/Bucharest` — configurabil, nu presupus în logică.
- Sumele: `Decimal`/`NUMERIC` în backend, `string` prin API, conversie doar la afișare
  (`lib/format.ts`). Niciodată `float`.
- Contractul JSON este **camelCase** în ambele direcții.
- Statusurile trăiesc într-un singur loc (`types/domain.ts`), oglindind backend-ul.
  Codurile de eroare la fel — `backend/tests/test_contract.py` verifică asta automat.
- Denumirea și calea de arhivă se calculează **numai** prin `lib/filename.ts`
  (§10, §11). Numele venit de la expeditor nu ajunge niciodată nemodificat pe disc.
- Secretele: doar în variabile de mediu. `.env` nu se comite niciodată.
- În development nu se folosesc date reale (CUI-uri, emailuri, documente, tokenuri).
- Nicio regulă fiscală nu se hardcodează. Unde este neclar:
  `TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION`.
