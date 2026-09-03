# STATUS — ContaCRM

Starea proiectului la **03.09.2026**. Documentul acesta răspunde la trei întrebări:
cum pornești pe o mașină nouă, ce este construit și ce urmează.

Pentru arhitectură, schema de bază de date și registrul de riscuri, vezi
[ARCHITECTURE.md](ARCHITECTURE.md). Pentru deciziile de fond, [adr/](adr/).
Pentru punerea în funcțiune, [DEPLOY.md](DEPLOY.md).

---

## 1. Pornire pe o mașină nouă

### Ce trebuie instalat

| Unealtă | Versiune | De ce |
|---|---|---|
| Node.js | 24+ | frontend |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | aduce singur Python 3.13 — nu e nevoie de Python în sistem |
| PostgreSQL | 17 | backend |
| Git | oricare | — |

Docker este opțional: `docker compose up -d` ridică Postgres. **Pe Windows
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
Autentificare: `admin@contacrm.test`, orice parolă — ecranul o spune, și o spune
doar acolo: în modul `http` parola chiar este verificată.

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

> În modul `http` funcționează **tot**, cu o singură excepție: autentificarea,
> administrarea, CRM-ul, fluxul complet de documente, panoul principal,
> perioadele, jurnalul de audit, rapoartele și ecranul de setări. Rămâne doar
> `Comunicare → Mesaje`, care are nevoie de Microsoft Graph și WhatsApp (Faza 2).

### Verificări

```bash
cd frontend && npm test && npm run lint && npm run build
cd backend  && uv run pytest && uv run ruff check . && uv run mypy app
uv run python -m app.worker --once   # un tur al cozii de procesare
```

Testele end-to-end pornesc singure tot ce le trebuie — backendul, build-ul
frontendului și o bază proprie, `contacrm_e2e`, reconstruită la fiecare rulare:

```bash
cd frontend
npx playwright install chromium   # o singură dată
npm run test:e2e                  # `npm run test:e2e:ui` pentru interfața Playwright
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
frontend   9.455 linii sursă +  1.147 linii teste  →   99 teste
backend   11.663 linii sursă + 11.275 linii teste  →  836 teste
end-to-end   556 linii                             →   17 teste (browser real)
migrări    1.307 linii
```

Toate verificările trec: **952 de teste**, lint curat, `mypy --strict` curat,
build curat, suita E2E verde într-un browser real.

### Frontend — complet, pe backend simulat ✅

Toate cele **22 de rute** sunt ecrane reale, nu placeholdere:

| Zonă | Ecrane |
|---|---|
| Panou principal | KPI, inbox recent, „necesită atenție", perioade, cronologie |
| CRM | listă clienți (filtre + paginare), detaliu client, contacte, sarcini (kanban) |
| Documente | inbox, în procesare, verificare, arhivă, **ecranul de verificare** |
| Contabilitate | perioade cu checklist, documente lipsă |
| Comunicare | mesaje, șabloane, remindere |
| Rapoarte | agregări calculate în backend, cu filtre pe lună și client |
| Administrare | utilizatori, roluri, setări, jurnal audit |

Piesa centrală este **ecranul de verificare**: facsimilul documentului lângă
câmpurile extrase, fiecare câmp cu proveniența lui (`AI 81%`, „corectat manual",
„lipsă") și bordură colorată pe praguri de încredere. Scurtături `Alt+S` / `Alt+A`.

**Backendul simulat** (`src/api/mock/`, ~1.700 linii) implementează 32 de rute cu
aceleași căi, paginare, filtrare, permisiuni și coduri de eroare ca API-ul real.
Comutarea se face din `VITE_API_MODE` — restul aplicației nu știe cine răspunde.

Alte lucruri gata: temă light/dark persistată, filtre în URL (o listă filtrată se
poate trimite unui coleg), sidebar colapsabil cu contoare live, accesibilitate
consecventă (`scope`, `role="alert"`, `sr-only`, `aria-label`).

### Backend — M2–M8 complet ✅

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

**M6 (a doua parte) — coada, acțiunile în masă, jurnalul**

**Workerul rulează separat de API.** `python -m app.worker` ia din coadă și
procesează; `--once` face un tur și iese, pentru cron sau verificări. Oprirea la
`SIGTERM` este ordonată — jobul în lucru se termină. La pornire repune în coadă ce a
rămas de la o rulare moartă, pentru că foarte probabil chiar el a fost cel care a
murit la mijloc.

**Fără Celery și fără Redis, deliberat.** Coada există deja și este durabilă:
`document_processing_jobs` este un outbox tranzacțional, revendicat cu
`FOR UPDATE SKIP LOCKED`. Un broker ar aduce încă un serviciu de rulat, monitorizat
și repornit, ca să facă exact ce face deja baza de date pe care oricum o avem. La
volumul unui cabinet — sute de documente pe zi, nu sute pe secundă — Postgres este
coada potrivită. Dacă vreodată devine strâmt, `process(document_id)` are deja
semnătura unui task de worker: se schimbă transportul, nu logica.

Selecția din coadă **nu** revendică: jobul rămâne `PENDING` până chiar înainte de
muncă. Marcat `RUNNING` prea devreme, un worker care moare între selecție și
extracție l-ar bloca până la pragul de vechime.

**Acțiuni în masă** (`POST /documents/bulk`): fiecare document este propria
tranzacție. Un lot de cincizeci în care al treilea eșuează nu are voie să anuleze
primele două — operatorul a apăsat un buton, dar a luat cincizeci de decizii.
Rezultatul spune ce a mers și ce nu, **cu motivul concret**: „au eșuat 7 documente"
fără să spună care și de ce este inutilizabil. Permisiunea se verifică pe acțiune,
nu pe rută: un OPERATOR poate reprocesa în masă, dar nu poate aproba.

**Jurnalul de audit** (`GET /audit-logs`) este doar citire, doar cu `audit:read`.
Vechile și noile valori nu ies prin API: auditul răspunde la „cine, ce, când", nu la
„ce scria pe factură". Cine are nevoie de conținut deschide documentul, iar acea
deschidere se auditează la rândul ei.

Rute reale existente: 37 de endpoint-uri (auth ×3, `/me`, `/users`, CRM ×6,
documente ×13, `/dashboard` ×2, perioade ×5, audit, rapoarte, setări, health ×3),
plus `/internal/run-queue`, care nu apare în OpenAPI pentru că nu face parte din
contractul cu frontend-ul.

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
| Bara laterală oferea unui OPERATOR „Utilizatori", „Roluri" și „Setări" — trei uși încuiate, fiecare ducând într-un 403 | **prima rulare a suitei E2E** |
| Ecranul de autentificare declara „parola nu este verificată" pe orice instalare, cu parola `demo` deja completată — în modul `http` parola este verificată, iar `demo` nu merge | scriind testul E2E de autentificare |
| Un byte NUL brut în `store.ts` făcea fișierul binar pentru git, iar verificarea de igienă din CI îl **sărea** (`git grep -I`) | căutând altceva prin `grep` |
| Testele frontend își făceau propriul `QueryClient`, cu alte valori decât aplicația: întreaga clasă de defecte de cache era invizibilă prin construcție | investigând un eșec din E2E |

---

## 3. Ce mai este de făcut

### Golul concret

Frontend-ul consumă **32 de rute**. Backendul real le implementează pe toate în
afară de una (plus `/auth/refresh` și health). **Rămâne 1** — `GET /messages`,
din Faza 2.

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
| ~~`POST /documents/bulk`, `GET /audit-logs`~~ | ✅ M6 |
| ~~`GET /reports/summary`, `GET /settings`, `POST /documents/upload`~~ | ✅ M7 |
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
| **M6** | Coadă durabilă + worker separat, perioade + checklist, dashboard, ecran audit, acțiuni în masă | ✅ |
| **M7** | Rapoarte în SQL, setări reale, extracție reală din PDF, identificarea clientului, încărcare | ✅ (notificările au trecut în Faza 2 — cer un provider de email sau WhatsApp) |
| **M8** | CI + teste E2E | ✅ |
| Faza 2 | Microsoft Graph, WhatsApp, OCR/AI real, remindere, export ZIP | |
| Faza 3 | Integrare software contabil, rapoarte avansate, detecție anomalii | |

**MVP = M1–M8.**

**M7 — rapoarte și setări reale**

Amândouă au pornit de la același defect: interfața spunea ceva ce nu era adevărat.

`GET /reports/summary` numără în SQL. Înainte, pagina cerea primele 200 de
documente — plafonul maxim — și le agrega în browser; „rata de procesare reușită"
era calculată pe felia aceea și afișată ca și cum ar fi acoperit tot. Pe setul
sintetic sunt sub 200 de documente, deci ieșea corect **din întâmplare** — exact
motivul pentru care greșeala nu se vedea.

Trei lucruri se văd altfel acum: documentele fără lună, fără client sau fără tip
nu mai sunt sărite din agregare, ci au propria găleată; `successRate` este `null`
când nu s-a terminat nimic, nu zero, pentru că zero se citea ca „totul a eșuat";
iar etichetele vin doar de unde există cu adevărat — numele clientului și
denumirea tipului de la server, formularea absenței și traducerea stărilor din
interfață, care le avea deja.

`GET /settings` publică configurarea după care rulează procesul. Ecranul afișa
`"local"`, `"0,90"`, `"mock"` scrise de mână în TSX, sub un banner care declara că
vin din variabile de mediu: `STORAGE_PROVIDER=s3` în producție nu ar fi schimbat
nimic pe ecran. Ce se publică este o **listă albă**, nu un filtru — un câmp nou în
`Settings` nu apare de la sine, iar un test se uită la fiecare câmp existent, nu
la o listă ținută minte, ca prima cheie de API adăugată să nu ajungă pe un ecran.

Notificările rămân Faza 2: datele pe care s-ar sprijini există deja („Documente
lipsă" spune pentru fiecare client ce nu a sosit), dar trimiterea cere un provider
de email sau WhatsApp.

**M7 — primul provider care chiar citește documentul**

`OCR_PROVIDER=pdf_text` scoate textul pe care PDF-ul îl poartă deja și recunoaște
în el ce poate fi recunoscut cu certitudine: dată, serie și număr, coduri fiscale,
bază, TVA, total, monedă. Local, fără rețea, fără cheie de API — din punct de
vedere GDPR identic cu `mock`, doar că rezultatul este adevărat (R2).

**Regula sub care este scris tot:** nu ghicește. O valoare se întoarce doar dacă
textul o marchează explicit, lângă eticheta ei. Un câmp gol costă zece secunde de
completat de pe facsimil; un câmp completat greșit trece pe lângă operator, pentru
că ecranul arată ceva ce pare citit de pe document.

Ce **nu** încearcă, deliberat: direcția facturii (intrare/ieșire depinde de al cui
este cabinetul — un document în registrul greșit e mai rău decât unul
neclasificat), numele furnizorului (stă într-un bloc de adresă, fără etichetă) și
luna contabilă (o derivă sistemul din dată, ADR-008). Un PDF scanat sau o poză nu
au strat de text: acolo întoarce un rezultat gol, nu unul inventat.

Verificat capăt la capăt pe server real: dintr-o factură cu `Data emiterii` și
`Data scadenței` una lângă alta, a luat-o pe prima — confuzia dintre ele ar fi
mutat documentul în altă lună contabilă.

Pe drum s-a reparat o minciună veche a ecranului de verificare: badge-ul afișa
„AI 95%" pentru **orice** proveniență care nu era `MANUAL`, `EMPTY` sau `DERIVED`.
O valoare citită de o regulă apare acum ca „citit", cu altă iconiță.

**M7 — identificarea clientului, pasul care lipsea din flux**

Fluxul produsului spune „intake → **identificare client** → OCR/AI". Pasul acela nu
exista: fiecare document ajungea `UNMATCHED` și aștepta un om care să aleagă
clientul dintr-o listă. La sute de documente pe zi, era cea mai scumpă apăsare de
buton din tot sistemul.

Acum se caută codurile fiscale citite de pe document printre clienții cabinetului.
Se compară normalizat, pentru că aceeași firmă apare cu `RO` pe o factură și fără
pe alta.

**Rolul potrivirii dă și direcția documentului.** Extracția nu putea decide dacă o
factură este de intrare sau de ieșire, și pe bună dreptate: un modul care citește
text nu are de unde să știe pentru cine lucrează cabinetul. Dar dacă clientul
nostru apare ca *furnizor*, el a emis-o — este ieșire; dacă apare ca *cumpărător*,
este intrare. Extracția rămâne cinstită și spune doar „este factură, nu știu a
cui"; sistemul decide restul, din ce știe despre proprii clienți. Tipul rezultat
este marcat `DERIVED`, nu `AI`.

Când nu se poate spune, nu se spune: o factură între doi clienți ai aceluiași
cabinet aparține la fel de mult amândurora, deci rămâne `UNMATCHED`.

Verificat capăt la capăt pe server: aceeași factură, o dată cu clientul nostru
cumpărător și o dată furnizor, a ieșit „Factură intrare" și „Factură ieșire"; una
cu două coduri necunoscute a rămas neatribuită.

**Un defect prins tot acolo:** o expresie regulată ajunsese în fișier cu `\b`
transformat în byte de control, deci nu se potrivea cu nimic. Testele unitare nu
existau pentru ea; rularea pe server a arătat-o imediat. Acum există și testele,
și o verificare în CI care refuză caractere de control în surse.

**M7 — încărcarea, drumul prin care un document chiar intră**

Fluxul produsului începe cu email și WhatsApp, dar amândouă sunt Faza 2. Între
timp aplicația nu avea **niciun** mod prin care un utilizator să bage un document
în sistem: ruta `POST /documents/upload` exista de la M5, dar numai un script o
putea folosi. Tot restul — verificare, corectură, aprobare, arhivare — se
sprijinea pe date semănate. Un cabinet care ar fi deschis aplicația nu ar fi avut
ce să facă cu ea.

Panoul stă pe inbox, unde documentul ajunge oricum. Fișierele pleacă **unul câte
unul**: douăzeci de cereri deodată nu ajung mai repede, se bat pe aceeași
conexiune și, în spatele unei platforme serverless, se lovesc de limite. Un eșec
nu oprește lotul — al treilea fișier respins nu are voie să ascundă că primele
două au intrat, iar fiecare rând își poartă motivul concret venit de la server.

Interfața **nu verifică nimic**: tipul îl stabilește serverul din primii octeți,
nu din ce declară browserul (§50), iar limita din configurarea lui. O a doua
copie a regulilor aici s-ar despărți tăcut de cea adevărată, și atunci ecranul ar
refuza fișiere pe care serverul le acceptă — sau, mai rău, invers.

**M8 — CI**

`.github/workflows/ci.yml` rulează la fiecare push exact comenzile care se rulează
local — un CI care verifică altceva dă un fals sentiment de siguranță. Backendul
pornește un PostgreSQL real, nu un SQLite „ca să meargă în CI": altfel ar rămâne
neverificate exact lucrurile care contează — indexuri parțiale, `unaccent`,
`FOR UPDATE SKIP LOCKED`, constrângerile CHECK.

Al patrulea job verifică ce nu are voie să intre în repo: documente contabile
(§70), fișiere `.env`, caractere de control.

Verificarea de igienă avea ea însăși o gaură, găsită imediat: `git grep -I`
**sare** fișierele pe care git le consideră binare — adică exact fișierele
stricate. `store.ts` conținea un byte NUL brut acolo unde codul voia escape-ul
din două caractere; valoarea șirului ieșea la fel, testele treceau, dar git
trata fișierul ca binar, diff-urile deveneau „Binary files differ" și
verificarea trecea verde peste el. Acum se citește prin
`git ls-files | xargs grep -a`. A găsit pe loc încă un caz: propoziția din acest
document care descrie defectul cu 0x08 conținea ea însăși un 0x08.

**M8 — testele end-to-end**

Aproape toate defectele serioase ale proiectului au fost găsite **rulând**
aplicația, nu citind-o: tokenul fals trimis către API-ul real, un buton oferit
într-o stare în care ruta răspundea 409, o reprocesare care răspundea 202 cu un
document neatins, o expresie regulată ajunsă în fișier cu un byte de control.
Toate au trecut prin teste unitare verzi. Ce le lega era că apăreau abia acolo
unde cele două jumătăți se întâlnesc: browser, HTTP, cookie-uri, bază reală.

Suita Playwright pune exact acel drum sub verificare automată, în loc să depindă
de cine își aduce aminte să deschidă aplicația. Ce pornește este aplicația
adevărată: PostgreSQL real (baza `contacrm_e2e`, reconstruită la fiecare rulare
prin migrări), backendul real cu `OCR_PROVIDER=pdf_text`, și **build-ul**
frontendului servit prin `vite preview` — nu serverul de development, pentru că
un E2E care verifică un artefact pe care nimeni nu-l pune în producție verifică
altceva decât produsul.

Testul central urcă un PDF construit de test, cu text scris de test, și cere
înapoi **exact acele valori**: numărul, seria, totalul, data emiterii (nu cea a
scadenței), clientul identificat din CUI, direcția facturii dedusă din rolul
potrivirii. Dacă extracția ar începe vreodată să inventeze, testul cade.
Restul lanțului merge până la capăt: corectură umană care supraviețuiește unei
reîncărcări, aprobare, arhivare, și documentul regăsit în arhivă sub numele
standardizat din §10.

Trei lucruri se pot verifica **doar** aici, dintr-un browser: că sesiunea chiar
stă într-un cookie `httpOnly` (invizibil din JavaScript prin definiție, deci un
test care rulează în pagină nu poate ști), că niciun token nu apare în vreun URL
cerut de pagină (§27 — se ascultă toate cererile, nu doar cele la care ne-am
gândit), și că previzualizarea vine dintr-un `blob:`.

`npm run test:e2e` rulează același lucru pe laptop și în CI: Playwright pornește
singur ambele servere și reconstruiește baza. `reset-e2e` refuză orice bază al
cărei nume nu se termină în `_e2e` — un `DROP DATABASE` într-un CLI este exact
unealta care distruge o bază reală la o variabilă de mediu pusă greșit.

**Un defect găsit scriind suita:** ecranul de autentificare afișa, pe orice
instalare, „Mod development — autentificare simulată, parola nu este
verificată", cu parola `demo` deja completată. În modul `http` parola **este**
verificată, iar `demo` nu funcționează. Un ecran de autentificare care minte
despre autentificare este primul lucru pe care îl vede un utilizator nou.
Bannerul și conturile de acces rapid apar acum doar pe backendul simulat.

### Punerea în funcțiune

M1–M6 sunt complete: un document intră, se procesează în afara cererii HTTP,
ajunge la un om, se corectează, se aprobă și se arhivează cu numele standardizat,
iar luna contabilă și panoul principal se construiesc din date, nu din calendar.

Repo-ul este pregătit pentru un singur proiect Vercel cu două servicii — detaliile
și motivele sunt în [DEPLOY.md](DEPLOY.md). Pe scurt, ce a fost nevoie:

- **`S3StorageProvider`.** `LocalStorageProvider` presupune un disc care
  supraviețuiește repornirii; în containere efemere discul dispare, iar o probă
  contabilă nu are voie să dispară (R8). Vorbește protocolul, nu cu un furnizor
  anume: AWS, Supabase Storage, R2, MinIO — se schimbă doar endpointul. Testele de
  stocare au fost rescrise ca **contract**: fiecare întrebare se pune de două ori,
  o dată pe disc și o dată pe S3, pentru că un provider nou nu se validează
  citindu-l.
- **`GET /api/v1/internal/run-queue`.** Un ceas din afară în locul procesului
  continuu, acolo unde nu există proces continuu. Fără `CRON_SECRET`, ruta
  răspunde 404 — la fel ca pentru un secret greșit.
- **Pooling.** `DB_EXTERNAL_POOLER=true` oprește poolul propriu și instrucțiunile
  pregătite, pe care un pooler în mod tranzacție le rupe tăcut: eșecul apare la a
  doua cerere, nu la prima, deci niciodată la testare.
- **`app.cli create-admin`.** Nu exista niciun drum care să creeze primul
  utilizator al unei baze de producție: orice creare de cont cere deja un cont.

Ce urcă în varianta fără backend este interfața completă pe **backendul simulat
din browser**, cu date sintetice — o demonstrație care funcționează integral, dar
nu aplicația legată la un API real.

**MVP-ul este complet (M1–M8).** Ce rămâne este Faza 2: intrarea documentelor
prin email (Microsoft Graph) și WhatsApp, OCR real pentru documente scanate,
notificări și export ZIP. Până atunci, documentele intră prin panoul de
încărcare.

Ce urcă în varianta fără backend rămâne interfața completă pe **backendul
simulat din browser**, cu date sintetice — o demonstrație care funcționează
integral, dar nu aplicația legată la un API real.

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
3. **OCR real pentru documente scanate.** `pdf_text` acoperă PDF-urile digitale —
   cazul covârșitor — dar o poză de bon fiscal nu are text de citit. Tesseract ar
   rezolva-o local (încă un binar de instalat, calitate variabilă pe fotografii);
   un serviciu cloud ar rezolva-o mai bine, dar înseamnă că documentele pleacă de
   pe infrastructura noastră. *Decizie cu implicații GDPR (R2), nu una tehnică.*
4. ~~**`OCR_PROVIDER=mock` în producție**~~ — **decis: pornirea o refuză.**
   Providerul inventează furnizori, sume și date, iar ecranul de verificare le
   arată cu proveniență și scor de încredere, adică exact ca pe niște valori
   citite de pe document: operatorul nu are cum să le deosebească. Nu era o
   decizie de business, ci un defect care aștepta o instalare. Pentru
   demonstrații rămâne `ENVIRONMENT=staging`; `pdf_text` este, din punctul de
   vedere al GDPR, identic cu `mock` — local, fără rețea — doar că adevărat.
5. **Software-ul contabil țintă** pentru export — determină formatul.
6. **Tenant unic vs. multi-firmă** de la lansare. Schema suportă ambele;
   `organization_id` există peste tot de la început.

---

## 5. Datorie tehnică cunoscută

Niciuna nu blochează deploy-ul.

| Element | Notă |
|---|---|
| `QueryBoundary` (`components/page.tsx`) | scris ca să elimine triada `isLoading/error/empty`, dar nefolosit — cele 8 pagini o repetă manual |
| `react-hook-form`, `zod`, `@hookform/resolvers` | instalate, nefolosite |
| primitivele shadcn (`button`, `card`, `badge`, `separator`) | importate doar de componenta de demo; aplicația scrie Tailwind brut. Ori le adoptăm, ori recunoaștem că nu le folosim |
| `"2026-08"` hardcodat în 6 locuri | doar în backendul simulat, unde `MOCK_NOW` este tot august: setul sintetic rămâne coerent oricând l-ai deschide. Backendul real urmărește datele, nu calendarul (`latest_active_month`). Rămâne totuși o valoare scrisă de mână acolo unde ar trebui derivată din `MOCK_NOW`. `MONTH_OPTIONS` din ecranul de perioade poate trece pe `MonthFilter`, care nu are nevoie de nicio listă |
| ~~`client_ip()` ignoră `X-Forwarded-For`~~ | rezolvat: `TRUSTED_PROXY_COUNT` spune câte proxy-uri stau obligatoriu în față, iar adresa se citește numărând **de la dreapta**. Implicit 0 — antetul se ignoră până când cineva declară explicit prin ce trece cererea. Pe Vercel se pune 1 |
| `oxlint`: 2 warning-uri | `only-export-components` pe fișiere shadcn generate — cosmetic |
