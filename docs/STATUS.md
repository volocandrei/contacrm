# STATUS — ContaCRM

Starea proiectului la **31.08.2026**. Documentul acesta răspunde la trei întrebări:
cum pornești pe o mașină nouă, ce este construit și ce urmează.

Pentru arhitectură, schema de bază de date și registrul de riscuri, vezi
[ARCHITECTURE.md](ARCHITECTURE.md). Pentru deciziile de fond, [adr/](adr/).

---

## 1. Pornire pe o mașină nouă

### Ce trebuie instalat

| Unealtă | Versiune | De ce |
|---|---|---|
| Node.js | 24+ | frontend |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | aduce singur Python 3.13 — nu e nevoie de Python în sistem |
| PostgreSQL | 17 | backend |
| Git | oricare | — |

Docker este opțional: `docker compose up -d` ridică Postgres + Redis. **Pe Windows
ARM64 Docker Desktop nu ridică engine-ul** (clientul primește 500 chiar și la
`docker version`), de aceea mașina curentă rulează un PostgreSQL nativ.

### Pași

```bash
git clone https://github.com/volocandrei/contacrm.git
cd contacrm
```

**Frontend** — funcționează imediat, fără backend și fără bază de date:

```bash
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Implicit rulează pe backendul simulat din browser (`VITE_API_MODE=mock`).
Autentificare: `admin@contacrm.test`, orice parolă.

**Backend** — are nevoie de PostgreSQL:

```bash
# dacă Postgres nu e instalat (Windows):
winget install --id PostgreSQL.PostgreSQL.17 --silent \
  --custom "--superpassword contacrm_dev_password --serverport 5432"

psql -U postgres -c "CREATE ROLE contacrm LOGIN PASSWORD 'contacrm_dev_password' CREATEDB;"
psql -U postgres -c "CREATE DATABASE contacrm OWNER contacrm;"

cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.cli seed-dev            # organizație + 5 conturi
uv run uvicorn app.main:app --reload         # http://localhost:8000
```

Conturi de development, parola `contacrm-dev`:
`admin@` (ADMIN) · `contabil@` (ACCOUNTANT) · `operator@` (OPERATOR) ·
`verificator@` (REVIEWER) · `vizitator@` (VIEWER, **dezactivat** intenționat, ca
fluxul „cont dezactivat" să fie testabil) — toate pe domeniul `contacrm.test`.

Ca frontend-ul să vorbească cu API-ul real în loc de cel simulat, creează
`frontend/.env.local`:

```
VITE_API_MODE=http
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

> Atenție: în modul `http` funcționează autentificarea, administrarea
> utilizatorilor și CRM-ul (clienți, contacte, note, sarcini). Ecranele de
> documente, perioade și rapoarte vor da 404 până la M5–M7.

### Verificări

```bash
cd frontend && npm test && npm run lint && npm run build
cd backend  && uv run pytest && uv run ruff check . && uv run mypy app
```

### Ce NU este în repo (și de ce)

| Lipsește | Cum îl obții |
|---|---|
| `node_modules/`, `.venv/` | `npm install`, `uv sync` |
| `.env` | copiază `.env.example`; valorile implicite merg pentru development |
| baza de date | `alembic upgrade head` + `app.cli seed-dev` |
| `storage/`, `ARHIVA/` | se creează la prima rulare (documentele nu se comit niciodată) |

Nu există niciun secret în repo. Singurele valori „secrete" comise sunt cele două
placeholdere evidente din `.env.example`.

---

## 2. Ce s-a construit

```
frontend  7.909 linii sursă +   411 linii teste   →  38 teste
backend   3.140 linii sursă + 1.722 linii teste   → 123 teste
migrări     548 linii
```

Toate verificările trec: **161 teste**, lint curat, `mypy --strict` curat, build curat.

### Frontend — complet, pe backend simulat ✅

Toate cele **22 de rute** sunt ecrane reale, nu placeholdere:

| Zonă | Ecrane |
|---|---|
| Panou principal | KPI, inbox recent, „necesită atenție", perioade, cronologie |
| CRM | listă clienți (filtre + paginare), detaliu client, contacte, sarcini (kanban) |
| Documente | inbox, în procesare, verificare, arhivă, **ecranul de verificare** |
| Contabilitate | perioade cu checklist, documente lipsă |
| Comunicare | mesaje, șabloane, remindere |
| Rapoarte | agregări peste documente |
| Administrare | utilizatori, roluri, setări, jurnal audit |

Piesa centrală este **ecranul de verificare**: facsimilul documentului lângă
câmpurile extrase, fiecare câmp cu proveniența lui (`AI 81%`, „corectat manual",
„lipsă") și bordură colorată pe praguri de încredere. Scurtături `Alt+S` / `Alt+A`.

**Backendul simulat** (`src/api/mock/`, ~1.600 linii) implementează 29 de rute cu
aceleași căi, paginare, filtrare, permisiuni și coduri de eroare ca API-ul real.
Comutarea se face din `VITE_API_MODE` — restul aplicației nu știe cine răspunde.

Alte lucruri gata: temă light/dark persistată, filtre în URL (o listă filtrată se
poate trimite unui coleg), sidebar colapsabil cu contoare live, accesibilitate
consecventă (`scope`, `role="alert"`, `sr-only`, `aria-label`).

### Backend — M2 + M3 + M4 ✅

**M2 — schelet**
- FastAPI cu fabrică `create_app()`, fără efecte secundare la import
- `Settings` peste `.env`, cu verificări care **opresc pornirea**: CORS refuză
  caracterul universal, producția refuză `SECRET_KEY` implicit, `/docs` dispare
  în producție
- Logging structurat (structlog), un `request_id` care leagă logurile, antetul
  `X-Request-ID` și câmpul `requestId` din erori
- Coduri de eroare identice cu `API_ERROR_CODES` din frontend — verificat automat
- Contract JSON **camelCase** în ambele direcții
- Health `live` / `ready` / `info`, cu `connect_timeout` ca readiness să nu atârne
- Alembic, Dockerfile multi-stage rulat neprivilegiat, `docker compose` cu profil `api`

**M3 — autentificare**
- `POST /auth/login` întoarce `CurrentUser` și pune tokenurile în cookie-uri
  **httpOnly, SameSite=Lax**, `Secure` în afara development-ului. Un token pe care
  JavaScript-ul paginii nu-l poate citi nu poate fi furat printr-un XSS.
  `Authorization: Bearer` rămâne acceptat pentru clienți programatici.
- **Refresh rotativ cu familii**: fiecare reîmprospătare emite un token nou și îl
  revocă pe cel folosit. Dacă un token deja rotit reapare, presupunem furt și
  revocăm toată familia.
- Refresh tokenurile se stochează **doar hash-uite**.
- Argon2id, cu rehash automat când parametrii se întăresc.
- Email inexistent ≡ parolă greșită: același mesaj, aproximativ același timp.
- RBAC: `app/domain/permissions.py` este sursa de adevăr; un test citește
  fișierele TypeScript ale frontend-ului și cade dacă cele două se despart.
- Filtrarea pe `organization_id` trăiește în repository (R10), cu teste negative.
- `audit_logs` append-only prin convenție; ștergerea unui utilizator nu șterge
  urma acțiunilor lui (FK `SET NULL`).

**M4 — CRM**
- `GET /clients` (paginat, filtre `q`/`status`/`accountantId`), `/clients/{id}`,
  `/clients/{id}/contacts`, `/clients/{id}/notes`, `GET /tasks`, `PATCH /tasks/{id}`
- Căutare și sortare insensibile la diacritice, prin `unaccent` + un wrapper
  IMMUTABLE și un index GIN trigram. Metacaracterele LIKE din input sunt escapate.
- Ștergere logică peste tot; unicitatea CUI-ului este un index **parțial**, ca un
  client șters să nu blocheze reînregistrarea aceleiași firme.
- Invariant în baza de date: o sarcină este `DONE` dacă și numai dacă are
  `completed_at`.

**Testele rulează acum pe migrări, nu pe `create_all`.** Baza de test se
construiește cu `alembic upgrade head`, deci extensiile, funcțiile, constrângerile
`CHECK` și indexurile parțiale — care există doar în migrări — sunt prezente și
exercitate. Un test compară modelele cu schema migrată și cade la primul derapaj.

Rute reale existente: 14 endpoint-uri (auth ×3, `/me`, `/users`, CRM ×6,
health ×3).

### Verificat pe date reale, nu doar în teste

- Toate cele trei migrări se aplică **și se dau înapoi** curat
- Flux HTTP complet: parolă greșită → 401, login → `CurrentUser`, cookie-uri
  `HttpOnly`, `/me`, `/users` ca ADMIN, refresh, logout, `/me` după logout → 401
- În baza de date: audit cu `ip` și `request_id`, `timestamptz` cu offset,
  refresh tokenurile arată rotația (primul înlocuit de al doilea, aceeași familie)

### Defecte găsite și reparate pe parcurs

Merită reținute, pentru că niciunul nu era vizibil citind codul:

| Defect | Cum a fost găsit |
|---|---|
| `sanitizeSegment` nu elimina backslash-ul — separator de cale pe Windows | citind `lib/filename.ts` cu atenție la regex |
| Byte-uri de control brute (NUL, 0x1F) în sursă, invizibile pentru grep | `file` raporta fișierul ca binar |
| `filename.ts` era cod mort; regula bună nu rula niciodată | căutare de utilizări |
| Documente „Client neidentificat" care aveau client | **rulând aplicația** |
| Perioade „Documente complete" cu documente obligatorii lipsă | **rulând aplicația** |
| `EmailStr` respingea toate conturile `.test` + făcea DNS la fiecare login | **rulând testele pe DB reală** |
| `Mapped[datetime]` se mapa fără fus orar, deși coloanele sunt `timestamptz` | **rulând testele pe DB reală** |
| CLI-ul crăpa pe consolă cp1252 și dădea înapoi tranzacția | **rulând CLI-ul** |
| `%` din căutare era tratat ca joker LIKE, nu ca text | test scris din contractul mock-ului |
| Constrângerile `CHECK` existau doar în migrări, nu în modele | testul de derapaj modele↔migrări |
| `Mapped[TaskStatus]` întorcea `str` din baza de date, nu enum-ul | **rulând serverul real** |

---

## 3. Ce mai este de făcut

### Golul concret

Frontend-ul consumă **29 de rute**. Backendul real implementează **10** dintre ele
(plus `/auth/refresh` și health). **Rămân 19.**

| Rută | Milestone |
|---|---|
| `GET /dashboard`, `GET /dashboard/counts` | M7 |
| ~~`GET /clients`, `/clients/:id`, `/clients/:id/{contacts,notes}`~~ | ✅ M4 |
| `GET /clients/:id/periods` | M7 |
| `GET /clients/:id/messages` | Faza 2 |
| `GET /documents`, `/documents/:id`, `PATCH /documents/:id` | M5 |
| `GET /documents/next-review`, `POST /documents/:id/{assign-client,approve,reject,duplicate,reprocess}`, `POST /documents/bulk` | M6 |
| `GET /document-types` | M5 |
| `GET /periods`, `GET /periods/missing` | M7 |
| ~~`GET /tasks`, `PATCH /tasks/:id`~~ | ✅ M4 |
| `GET /messages` | Faza 2 |
| `GET /audit-logs` | M3 (ecran) / M7 |

Contractul fiecăreia este deja definit: `frontend/src/types/domain.ts` spune exact
ce câmpuri, iar `frontend/src/api/mock/store.ts` spune exact ce semantică
(filtrare, paginare, permisiuni, coduri de eroare). **Backendul nu trebuie proiectat,
ci portat.**

### Milestones

| M | Conținut | Stare |
|---|---|---|
| M0 | Inspecție, plan, ADR-uri | ✅ |
| M1 | Frontend scaffold + shell | ✅ |
| M1.5 | Toate ecranele pe backend simulat | ✅ |
| M2 | Schelet backend | ✅ |
| M3 | Auth, RBAC, audit | ✅ |
| M4 | CRM: clients, contacts, notes, tags, tasks | ✅ |
| **M5** | **Documents: upload, StorageProvider, SHA-256, duplicate, FilenameGenerator, preview securizat** | ⏳ **urmează** |
| M6 | Processing: Celery + Redis, MockOCRProvider, clasificare, extracție, confidence, review | |
| M7 | Perioade + checklist + dashboard KPI + ecran audit | |
| M8 | Notificări, teste E2E, CI | |
| Faza 2 | Microsoft Graph, WhatsApp, OCR/AI real, remindere, export ZIP | |
| Faza 3 | Integrare software contabil, rapoarte avansate, detecție anomalii | |

**MVP = M1–M8.**

### De ce M5 este următorul

Ecranul de verificare — piesa centrală a produsului — este complet pe date
sintetice, deci contractul e definit până la ultimul câmp. De construit:

1. `Document` + `DocumentField` cu proveniență (`AI`/`OCR`/`MANUAL`/`EMPTY`) și
   scor de încredere per câmp
2. Upload cu limită de dimensiune și listă albă de MIME, hash SHA-256 pentru
   detecția duplicatelor (§13)
3. `StorageProvider` (ADR-004) cu implementare locală, plus
   `FilenameGeneratorService` — regulile există deja testate în
   `frontend/src/lib/filename.ts`, care trebuie **portat identic** în Python
4. Preview autorizat: `<img>`/`<object>` nu trimit antetul `Authorization`, deci
   endpointul trebuie să accepte cookie de sesiune. Decizia se ia aici.

Cea mai mare capcană: numele venit de la expeditor nu are voie să ajungă
nemodificat într-o cale de filesystem (R3, R7). Testele din `filename.test.ts`
sunt specificația executabilă — aceleași cazuri trebuie să treacă în Python.

---

## 4. Decizii deschise

Necesită input uman, nu sunt de rezolvat în cod:

1. **Regula de `reference_period`** — cum se decide luna contabilă când
   `document_date` cade în altă lună? `document_date ≠ reference_month` și nu se
   deduc una din alta fără o regulă configurată.
   *TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION*
2. **Când este o perioadă „completă"?** Implementarea actuală cere ca **fiecare**
   item din checklist să fie satisfăcut (varianta conservatoare). Alternativa —
   un prag pe total — a fost respinsă pentru că poate declara luna închisă cu
   documente obligatorii lipsă. *Necesită confirmarea unui contabil.*
3. **Provider OCR/AI real** pentru Faza 2 și dacă politica firmei permite
   trimiterea documentelor în afara UE (GDPR, R2).
4. **Software-ul contabil țintă** pentru export — determină formatul.
5. **Tenant unic vs. multi-firmă** de la lansare. Schema suportă ambele;
   `organization_id` există peste tot de la început.

---

## 5. Datorie tehnică cunoscută

Niciuna nu blochează M4.

| Element | Notă |
|---|---|
| `QueryBoundary` (`components/page.tsx`) | scris ca să elimine triada `isLoading/error/empty`, dar nefolosit — cele 8 pagini o repetă manual |
| `useNextReviewDocument` + `/documents/next-review` | lanț implementat pe 4 straturi, folosit de nimeni; `ReviewQueuePage` (`/documente/verificare/coada`) e un stub nelegat din navigație |
| `react-hook-form`, `zod`, `@hookform/resolvers` | instalate, nefolosite |
| primitivele shadcn (`button`, `card`, `badge`, `separator`) | importate doar de componenta de demo; aplicația scrie Tailwind brut. Ori le adoptăm, ori recunoaștem că nu le folosim |
| `"2026-08"` hardcodat în 6 locuri | merge azi; din septembrie panoul principal arată o lună goală |
| `document-preview.tsx:16` | hardcodează `/api/v1/...`, ocolind `VITE_API_BASE_URL`; `<img>`/`<object>` nu trimit `Authorization`, deci endpointul de preview va trebui să accepte cookie de sesiune (decizie de luat la M5) |
| `client_ip()` (`api/deps.py`) | ignoră `X-Forwarded-For` — corect acum, dar trebuie citit din proxy-uri de încredere când apare un reverse proxy |
| lipsă `.gitattributes` | Git raportează conversii LF↔CRLF; un `* text=auto eol=lf` previne diff-uri false dacă intră cineva pe Linux/Mac |
| `oxlint`: 2 warning-uri | `only-export-components` pe fișiere shadcn generate — cosmetic |
