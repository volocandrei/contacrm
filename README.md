# ContaCRM

CRM + ERP de document management pentru firme de contabilitate.
Clienți → Email/WhatsApp → intake → identificare client → OCR/AI → validare →
review uman → standardizare → arhivare → dashboard/audit.

> **Pornești pe o mașină nouă sau vrei starea completă a proiectului?**
> [`docs/STATUS.md`](docs/STATUS.md) — ce e construit, ce urmează, cum pornești de la zero.

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
| Infrastructură dev: PostgreSQL + API + worker prin Docker | ✅ `docker-compose.yml` |
| Documente, procesare (M5–M6) | ⏳ urmează |

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
│   ├── FINAL_PRODUCTION_AUDIT.md
│   └── adr/                # ADR-001 … ADR-008
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
