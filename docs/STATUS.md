# STATUS — ContaCRM

Starea proiectului la **01.09.2026**. Documentul acesta răspunde la trei întrebări:
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
`frontend/.env.local` (pornind de la `frontend/.env.example`):

```
VITE_API_MODE=http
VITE_PROXY_TARGET=http://127.0.0.1:8000
```

**Lasă `VITE_API_BASE_URL` pe calea relativă implicită (`/api/v1`).** Serverul de
development proxy-ază `/api` către backend, deci browserul vede o singură origine.
Nu e comoditate: cookie-ul de sesiune este `SameSite=Lax`, iar de pe altă origine nu
ar fi trimis la cererile pornite de `<img>` sau `<object>` — adică exact la
previzualizarea documentului. Un token în URL nu este o alternativă (§27).

> În modul `http` funcționează autentificarea, administrarea utilizatorilor,
> CRM-ul (clienți, contacte, note, sarcini) și **tot fluxul de documente**: inbox,
> încărcare, procesare, ecranul de verificare, previzualizare, descărcare, arhivă.
> Panoul principal, perioadele și rapoartele încă dau 404 — vin cu M6–M7.
> Contoarele din bara laterală funcționează deja.

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
frontend  8.591 linii sursă +   672 linii teste   →  57 teste
backend   8.756 linii sursă + 7.640 linii teste   → 577 teste
migrări   1.229 linii
```

Toate verificările trec: **634 de teste**, lint curat, `mypy --strict` curat, build curat.

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

### Backend — M2 + M3 + M4 + M5 complet ✅ · M6 început

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

**M5 — documente (M5.1 → M5.6 gata; M5.7 și M5.8 rămân)**

- **M5.1 model și stocare.** `Document`, `DocumentVersion`, `DocumentFieldOverride`,
  `DocumentIntake`, `DocumentType`. `StorageProvider` (ADR-004) cu implementare
  locală: scriere atomică, cheie generată de sistem — **numele venit de la expeditor
  nu ajunge niciodată într-o cale de filesystem** (R3, R7).
- **M5.2 încărcare.** Tipul se stabilește din octeți (magic bytes), nu din ce declară
  clientul. Dimensiunea și SHA-256 se calculează **în timpul citirii**, ca un fișier
  peste limită să nu ajungă întreg în memorie. Duplicatele se recunosc după hash.
- **M5.3 API.** 12 rute, filtrare, sortare pe listă albă, paginare stabilă.
  Nicio cale de stocare nu iese printr-un răspuns (§73).
- **M5.4 preview și download.** Cereri autentificate, cu `Range`, `nosniff`,
  `default-src 'none'; sandbox` și `no-store`. Descărcarea se auditează —
  previzualizarea nu, ca volumul să nu înece intrările care contează.
- **M5.5 procesare.** Extracția stă în spatele unei interfețe (`DocumentExtractionProvider`)
  și primește doar fișierul, nu baza de date. Fiecare câmp are propriul scor de
  încredere. Idempotență la nivel de tabel, rândul blocat cu `FOR UPDATE`,
  **corecțiile manuale supraviețuiesc reprocesării**. Aprobarea automată există, dar
  este implicit oprită: a aproba o probă contabilă fără ca un om să se uite este o
  decizie de business, nu un implicit tehnic. Singura verificare numerică este
  `subtotal + TVA = total` — aritmetică pură. **Sistemul nu calculează niciodată TVA.**
- **M5.6 interfața de verificare pe API-ul real.** Ecranul existent a fost legat, nu
  rescris. Ce s-a adăugat:
  - **Serverul spune ce butoane sunt valide.** `availableActions` se calculează din
    aceeași mașină de stări pe care o folosesc și rutele, plus rolul utilizatorului.
    Interfața nu recalculează regulile ciclului de viață — o a doua copie ar rămâne
    în urmă tăcut, iar butoanele ar minți. Un test de contract compară tabelul de
    tranziții din backend cu cel din backendul simulat.
  - **`approvalBlockers` și `reprocessBlockedReason`** vin din exact aceleași funcții
    pe care rutele le folosesc ca să refuze. Un buton nu dispare fără explicație.
  - **Previzualizare autentificată prin `blob:`.** `<img>` și `<object>` nu trimit
    antetul `Authorization`, iar un token în query string este interzis (§27):
    conținutul se citește cu `fetch` și se dă elementului un URL de obiect, revocat
    la ieșire. Același drum pentru descărcare, cu numele standardizat de server.
  - **Sesiunea se reîmprospătează singură.** Tokenul de acces trăiește 15 minute; un
    operator stă mai mult pe același ecran. Un 401 declanșează un singur refresh
    (indiferent câte cereri așteaptă) și reîncearcă.
  - **Ecranul se actualizează singur** cât timp documentul este în procesare, și se
    oprește când ajunge într-o stare care așteaptă un om.
  - Rute noi: `GET /documents/next-review` (coada, cronologică) și
    `GET /dashboard/counts` (contoarele din bara laterală).

- **M5.7 arhivarea.** `frontend/src/lib/filename.ts` a fost portat identic în
  `app/domain/filenames.py`. Testul din Python **citește cazurile direct din
  `filename.test.ts`** și le rulează: dacă specificația se schimbă, portul cade, nu
  rămâne în urmă în tăcere. Aprobarea și arhivarea sunt un singur act — un document
  aprobat care nu a ajuns în arhivă nu este nicăieri — și se întâmplă în aceeași
  tranzacție: dacă scrierea în stocare eșuează, aprobarea se dă înapoi cu ea.
  Originalul nu se atinge (§16): arhiva este o copie, cu cheie proprie. Coliziunile
  de nume primesc sufix (`_2`, `_3`, …), dar unicitatea este garantată de un index
  parțial în baza de date — două arhivări simultane nu pot alege același nume,
  oricât de bine ar căuta fiecare înainte să scrie. Constrângerea
  `archived_has_filename` cere acum tot ce înseamnă „arhivat": moment, nume, cale
  și cheie.

**Întărire (prima parte din M5.8)** — cele trei probleme rămase la M5.7, rezolvate:

- **Cererea de procesare nu se mai poate pierde.** `document_processing_jobs` este
  acum un **outbox tranzacțional**: rândul `PENDING` se scrie în aceeași tranzacție
  cu documentul, deci ori se comit amândouă, ori niciunul. Cine execută doar
  revendică rândul (`PENDING → RUNNING` sub `FOR UPDATE`), deci doi executanți nu
  pot lua aceeași cerere. Ce rămâne pe drum se reia cu
  `python -m app.cli recover-processing`, iar documentele înțepenite apar pe panoul
  principal ca „Procesare întreruptă" — singurul mod în care o cădere de proces
  devine vizibilă cuiva. O cerere nouă de reprocesare readuce în coadă un job
  `RUNNING` rămas de la un proces mort, deci butonul deblochează și el.
- **Un document arhivat nu se mai editează pe loc.** Numele din arhivă codifică
  data, tipul, clientul, seria și numărul (§10): o corectură făcută direct l-ar
  lăsa să mintă despre conținut. Garda stă **în serviciu**, nu doar în lista de
  acțiuni. Drumul corect rămâne deschis și lasă urmă: reprocesare, corectură,
  aprobare din nou.
- **`GET /dashboard`** răspunde cu tot ce poate ști M5: indicatori pe documente și
  clienți, „necesită atenție", documente recente și cronologia din jurnalul de
  audit. `periods` este listă goală pentru că sistemul chiar nu are perioade — M6
  le umple.

Un al patrulea defect, găsit scriind testele de mai sus: **jurnalul de audit nu se
putea ordona**. `now()` întoarce în Postgres momentul de început al *tranzacției*,
deci toate intrările scrise într-o cerere aveau exact aceeași valoare, iar
istoricul unui document putea arăta arhivarea înaintea încărcării.
`clock_timestamp()` este ceasul real, evaluat la fiecare rând.

**Revizuirea de securitate și de volum (M5.8)**

Testele punctuale existau deja. Ce lipsea era o trecere **sistematică**: lista de
rute se citește din schema OpenAPI a aplicației, nu din memoria cuiva, iar fiecare
rută primește aceleași trei întrebări — cere sesiune? se oprește la granița
organizației? scapă ceva intern? Un sweep care nu descoperă nicio rută ar trece
oricând, așa că testul cade și dacă descoperirea returnează prea puțin.

Sweep-ul a găsit imediat ceva ce nicio verificare punctuală nu putea găsi:
**`api_router` era montat de două ori** — cu prefix și fără. Autorizarea era
aceeași pe ambele căi, deci nu se putea ajunge nicăieri în plus, dar un reverse
proxy configurat să protejeze `/api/*` ar fi lăsat descoperit exact același API pe
`/documents`, iar versionarea nu ar mai fi însemnat nimic. Acum doar health-ul stă
în afara prefixului, iar un test ține asta pe loc.

Volumul se măsoară în **interogări, nu în secunde**: un test cronometrat cade când
mașina e ocupată și trece când nu e. Regula verificată este că numărul de
interogări nu crește odată cu numărul de rânduri. Măsurat: o pagină de 50 de
documente costă 8 interogări, panoul 17, o încărcare 16 — toate fixe, indiferent
câte documente există deja.

Tot de acolo: `count(*)` pentru paginare se făcea peste o subinterogare care
proiecta **toate** coloanele documentului, textul OCR inclusiv (§64). Acum
proiectează doar cheia; join-urile și filtrele rămân neatinse, pentru că de ele
depinde căutarea după numele clientului.

**M6 (prima parte) — luna contabilă și perioadele**

Întrebarea deschisă de la §4.1 are acum un răspuns scris: [ADR-008](adr/ADR-008-reference-period.md).
Implicit, luna contabilă este **luna documentului**; `REFERENCE_PERIOD_STRATEGY=received_at`
o schimbă pe „luna primirii", pentru cabinetele care lucrează așa. Fără dată nu se
derivă nimic — o lună greșită este mai rea decât una absentă, pentru că absența se
vede. Corectura umană câștigă întotdeauna, iar reprocesarea nu o mai atinge.

Valoarea derivată nu se dă drept altceva: `FieldSource` are o a cincea valoare,
**`DERIVED`**, iar ecranul de verificare o arată ca „dedus". Un badge „AI 83%" pe o
valoare pe care modelul nu a produs-o ar fi exact minciuna pe care ecranul promite
să nu o spună.

**Perioadele nu stochează nimic ce se poate calcula.** Tabelele țin doar faptele
umane — cine a deschis o lună, cine a închis-o, ce se așteaptă de la fiecare client.
Contoarele și statusul se derivă la citire, dintr-o singură interogare grupată. Un
status ținut într-o coloană se desincronizează tăcut de contoarele lui: exact asta
s-a întâmplat în backendul simulat, unde perioade marcate „complete" aveau documente
obligatorii lipsă. Acum un document care își schimbă luna mută progresul instantaneu,
fără vreun pas de „recalculare" pe care cineva ar putea să-l uite.

Checklistul este **per client**, nu global: cabinetul știe că de la firma X vine un
extras de cont și de la firma Y nu. Un checklist identic pentru toți ar raporta
lipsuri inexistente, iar un raport care strigă degeaba ajunge să nu mai fie citit.

Închiderea lunii refuză un checklist incomplet — dar acceptă `force`. Există motive
legitime pe care sistemul nu le cunoaște; ce nu are voie este să treacă tăcut.

Rute noi: `GET /periods`, `GET /periods/missing`, `GET /clients/:id/periods`,
`POST /clients/:id/periods/:month/{close,reopen}`. Panoul principal are acum
perioade reale, iar lunile incomplete apar la „necesită atenție".

Rute reale existente: 33 de endpoint-uri (auth ×3, `/me`, `/users`, CRM ×6,
documente ×12, `/dashboard` ×2, perioade ×5, health ×3).

### Verificat pe date reale, nu doar în teste

- Toate cele opt migrări se aplică **și se dau înapoi** curat
- Flux HTTP complet: parolă greșită → 401, login → `CurrentUser`, cookie-uri
  `HttpOnly`, `/me`, `/users` ca ADMIN, refresh, logout, `/me` după logout → 401
- În baza de date: audit cu `ip` și `request_id`, `timestamptz` cu offset,
  refresh tokenurile arată rotația (primul înlocuit de al doilea, aceeași familie)
- Ciclul complet al unui document, pe server real: încărcare → procesare automată →
  `REVIEW_REQUIRED` cu proveniență per câmp → corecție manuală → reprocesare care
  **nu** calcă peste corecție → aprobare → descărcare cu numele corect; al doilea
  fișier identic devine duplicat legat de original; un OPERATOR primește 403
- **Interfața, în modul `http`, într-un browser real** (M5.6): login, reîncărcare cu
  sesiunea intactă, previzualizare PDF și imagine dintr-un `blob:` (fără token în
  URL), corectare și salvare, aprobare, descărcare cu numele de la server,
  reîmprospătarea automată a sesiunii după ștergerea cookie-ului de acces, butoanele
  care dispar corect pentru un OPERATOR, și ecranul care se actualizează singur cât
  timp documentul este reprocesat

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
| `api_router` era montat de două ori: tot API-ul răspundea și fără prefixul de versiune | sweep-ul de securitate care citește rutele din schema OpenAPI |
| jurnalul de audit nu se putea ordona: `now()` dă în Postgres timpul de **început al tranzacției**, deci toate intrările unei cereri aveau aceeași valoare | testul care cerea ca aprobarea să apară înaintea arhivării |
| `count(*)` pentru paginare proiecta toate coloanele, textul OCR inclusiv | testul care numără interogările |
| Filtrele de listă nu se legau deloc din query string — API-ul returna tot | **rulând serverul real** |
| `FOR UPDATE` pe partea nullable a unui outer join → 500 | **rulând serverul real** |
| Procesarea pornea pe o tranzacție încă necomisă; documentul rămânea tăcut în `RECEIVED` | **rulând serverul real** (testele împart sesiunea, deci nu puteau vedea) |
| Loggerul cădea pe consolă cp1252 exact când excepția avea diacritice | **rulând serverul real** |
| Tokenul fals `mock-session-…` era trimis și către API-ul real, unde `Bearer` are prioritate în fața cookie-ului → 401 la fiecare cerere | **rulând interfața în modul `http`** |
| `availableActions` oferea `reprocess` pe un document cu încercările epuizate; ruta răspundea 409 | **rulând interfața în modul `http`** |
| Reprocesarea răspundea 202 cu un document care arăta neatins, deci ecranul nu știa că mai are ce aștepta | **rulând interfața în modul `http`** |
| Suita de teste frontend își schimba comportamentul după `.env.local` | rulând testele după ce am creat `.env.local` |

---

## 3. Ce mai este de făcut

### Golul concret

Frontend-ul consumă **31 de rute**. Backendul real implementează **28** dintre ele
(plus `/auth/refresh` și health). **Rămân 3.**

| Rută | Milestone |
|---|---|
| ~~`GET /clients`, `/clients/:id`, `/clients/:id/{contacts,notes}`~~ | ✅ M4 |
| ~~`GET /tasks`, `PATCH /tasks/:id`~~ | ✅ M4 |
| ~~`GET /documents`, `/documents/:id`, `PATCH /documents/:id`, `/document-types`~~ | ✅ M5.3 |
| ~~`/documents/:id/{preview,download}`~~ | ✅ M5.4 |
| ~~`POST /documents/:id/{assign-client,approve,reject,duplicate,reprocess}`~~ | ✅ M5.3–M5.5 |
| ~~`GET /documents/next-review`, `GET /dashboard/counts`~~ | ✅ M5.6 |
| ~~`GET /dashboard`~~ | ✅ |
| ~~`GET /periods`, `GET /periods/missing`, `GET /clients/:id/periods`~~ | ✅ M6 |
| `POST /documents/bulk` | M6 (ecranul de listă) |
| `GET /audit-logs` | M6 (ecran) |
| `GET /messages`, `GET /clients/:id/messages` | Faza 2 |

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
| **M5** | **Documente: încărcare, stocare, API, preview, procesare, interfața de verificare, arhivare, întărire** | ✅ |
| **M6** | Coadă persistentă (Celery + Redis), perioade + checklist, dashboard, ecran audit, acțiuni în masă | ⏳ perioade + dashboard ✅ |
| M7 | Notificări, rapoarte | |
| M8 | Teste E2E, CI | |
| Faza 2 | Microsoft Graph, WhatsApp, OCR/AI real, remindere, export ZIP | |
| Faza 3 | Integrare software contabil, rapoarte avansate, detecție anomalii | |

**MVP = M1–M8.**

### De ce M6 este următorul

M5 este complet: un document intră, se procesează singur, ajunge la un om, se
corectează, se aprobă și se arhivează cu numele standardizat — verificat capăt la
capăt pe server real, nu doar în teste.

Ce cere M6, în ordinea în care doare lipsa lor:

1. **Coadă persistentă (Celery + Redis).** Outbox-ul există deja și cererea nu se
   mai pierde; ce lipsește este un proces separat care să consume coada și să ruleze
   recuperarea periodic, în loc de `app.cli recover-processing` chemat de mână.
   `process(document_id)` are deja semnătura potrivită.
2. **Perioade contabile + checklist.** Sunt singurul lucru care lipsește din panoul
   principal (`periods`, `clientsComplete`, `clientsMissingDocs`) și din ecranele de
   contabilitate. Contractul este definit până la ultimul câmp în
   `frontend/src/api/mock/store.ts`, inclusiv regula de progres: o factură în plus nu
   compensează un extras de cont lipsă.
3. **`POST /documents/bulk`** — acțiunile în masă din ecranul de listă. Funcția
   există în `api/endpoints.ts` și nu are încă rută.
4. **`GET /audit-logs`** — ecranul de jurnal există, ruta nu.

Înainte de oricare: **decizia de business despre `reference_period`** (§4.1). Fără
ea, perioadele se pot construi, dar nu se poate spune corect în ce lună intră un
document a cărui dată cade în alta.

---

## 4. Decizii deschise

Necesită input uman, nu sunt de rezolvat în cod:

1. ~~**Regula de `reference_period`**~~ — decisă în [ADR-008](adr/ADR-008-reference-period.md):
   implicit luna documentului, cu „luna primirii" ca setare. Rămân de confirmat de un
   contabil trei lucruri, scrise acolo: termenul până la care o factură mai poate intra
   în luna ei, dacă regula diferă pe tip de document, și dacă este per cabinet sau per
   client. *TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION* pe cele trei.
2. **Când este o perioadă „completă"?** Implementarea cere ca **fiecare** item din
   checklist să fie satisfăcut (varianta conservatoare) — alternativa, un prag pe
   total, a fost respinsă pentru că poate declara luna închisă cu documente
   obligatorii lipsă. Închiderea peste un checklist incomplet rămâne posibilă, dar
   cerută explicit. *Necesită confirmarea unui contabil.*
3. **Provider OCR/AI real** pentru Faza 2 și dacă politica firmei permite
   trimiterea documentelor în afara UE (GDPR, R2).
4. **Software-ul contabil țintă** pentru export — determină formatul.
5. **Tenant unic vs. multi-firmă** de la lansare. Schema suportă ambele;
   `organization_id` există peste tot de la început.

---

## 5. Datorie tehnică cunoscută

Niciuna nu blochează M5.7.

| Element | Notă |
|---|---|
| `QueryBoundary` (`components/page.tsx`) | scris ca să elimine triada `isLoading/error/empty`, dar nefolosit — cele 8 pagini o repetă manual |
| `react-hook-form`, `zod`, `@hookform/resolvers` | instalate, nefolosite |
| primitivele shadcn (`button`, `card`, `badge`, `separator`) | importate doar de componenta de demo; aplicația scrie Tailwind brut. Ori le adoptăm, ori recunoaștem că nu le folosim |
| `"2026-08"` hardcodat în 6 locuri | merge azi; din septembrie panoul principal arată o lună goală |
| `client_ip()` (`api/deps.py`) | ignoră `X-Forwarded-For` — corect acum, dar trebuie citit din proxy-uri de încredere când apare un reverse proxy |
| lipsă `.gitattributes` | Git raportează conversii LF↔CRLF; un `* text=auto eol=lf` previne diff-uri false dacă intră cineva pe Linux/Mac |
| `oxlint`: 2 warning-uri | `only-export-components` pe fișiere shadcn generate — cosmetic |
| `POST /documents/bulk` | declarat în `api/endpoints.ts`, fără rută în backend și fără apelant în interfață — se leagă la M6, odată cu acțiunile în masă din ecranul de listă |
| execuția procesării rulează încă în procesul API | cererea **nu se mai pierde** (outbox tranzacțional), ce rămâne pe drum se reia cu `app.cli recover-processing`, iar documentele înțepenite apar pe panou ca "Procesare întreruptă". Lipsește doar un worker separat care s-o ruleze singur, periodic — infrastructură, nu logică (M6) |
