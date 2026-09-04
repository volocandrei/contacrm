# STATUS — ContaCRM

Starea proiectului la **04.09.2026**. Documentul acesta răspunde la trei întrebări:
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
> `Comunicare → Mesaje`, care are nevoie de WhatsApp (Faza 2).

### Verificări

```bash
cd frontend && npm test && npm run lint && npm run build
cd backend  && uv run pytest && uv run ruff check . && uv run mypy app
uv run python -m app.worker --once      # un tur: surse externe + coada de procesare
uv run python -m app.cli check-storage  # baza de date și stocarea se potrivesc?
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
frontend  16.282 linii sursă +  2.517 linii teste  →   202 teste
backend   20.900 linii sursă + 17.950 linii teste  → 1.243 teste
end-to-end 1.484 linii                             →    58 teste (browser real)
migrări    1.916 linii
```

Toate verificările trec: **1.503 de teste**, lint curat, `mypy --strict` curat,
build curat, suita E2E verde într-un browser real.

### Frontend — complet, pe backend simulat ✅

Toate cele **24 de rute** sunt ecrane reale, nu placeholdere. Meniul este ordonat
după cum se lucrează, nu după cum s-au construit modulele: ziua începe la
documente, clienții și rapoartele se deschid mai rar, administrarea aproape
niciodată. „Integrări" stă separat de „Administrare" — „cum adaug un coleg" și
„cum conectez OneDrive" sunt două întrebări diferite.

| Zonă | Ecrane |
|---|---|
| Panou principal | KPI, inbox recent, „necesită atenție", perioade, cronologie |
| CRM | listă clienți (filtre + paginare), detaliu client, **agendă de contacte căutabilă**, sarcini (kanban) |
| Documente | inbox, în procesare, verificare, **neatribuite**, arhivă, **ecranul de verificare** |
| Contabilitate | perioade cu checklist, documente lipsă |
| Comunicare | mesaje, șabloane, remindere |
| Rapoarte | agregări calculate în backend, cu filtre pe lună și client |
| Administrare | utilizatori, **matricea rol × permisiune**, setări, **surse documente (OneDrive + email)**, **e-Factura**, jurnal audit |

**Ctrl+J deschide asistentul** (M13): un chat care răspunde din datele
cabinetului — „cât e de lucru?", „ce lipsește la Alfa Conta?", „când e
termenul?" — și propune drumul către ecranul potrivit.

Trei reguli îl țin onest. **Rulează ca utilizatorul**: fiecare întrebare se
execută cu permisiunile lui, prin aceleași repository-uri ca rutele obișnuite,
deci nu poate vedea peste ce vede el. **Doar citire**: nu aprobă, nu respinge,
nu trimite — o aprobare este un act contabil cu nume și oră în jurnal, deci
trebuie să aibă în spate un om care a apăsat, nu o propoziție interpretată. Și
**nu inventează**: fiecare cifră vine dintr-o unealtă care a interogat baza; când
nu știe, spune ce poate în schimb.

Motorul implicit (`ASSISTANT_PROVIDER=rules`) nu cere nicio credențială și nu
trimite nimic în afara rețelei cabinetului. Un model de limbaj se adaugă prin
același seam ca la OCR și stocare (ADR-004, ADR-005), cu aceleași unelte și
aceleași limite de rol.

**Ctrl+K deschide paleta de comenzi**: caută în același timp în ecrane, clienți
(inclusiv după CUI) și documente, și duce direct la rezultat. Înlocuiește câmpul
din antet, care promitea o căutare globală și, orice s-ar fi scris în el, ducea în
inboxul de documente. Nu ocolește nicio permisiune: ecranele se filtrează ca în
bara laterală, iar interogările pornesc doar dacă rolul le poate cere.

„Contacte" a devenit o agendă: o singură cerere pentru tot ecranul (cerea
înainte contactele fiecărui client în parte — treizeci de cereri pentru treizeci
de clienți, pornite deodată), căutare care acoperă și persoana și firma, și date
de contact **acționabile** — un click sună, scrie sau deschide WhatsApp. Un număr
pe care trebuie să-l copiezi cu ochiul nu este o agendă, este o listă.

Pe „Documente lipsă", fiecare rând are **Copiază solicitarea**: textul către
client, cu lista lipsurilor și termenul lunii, gata de trimis din clientul de
email al contabilului. Aplicația știe ce lipsește și până când, dar nu poate
trimite — asta cere un provider și rămâne în Faza 2; butonul acoperă exact
distanța rămasă, fără să pretindă că o depășește.

Piesa centrală este **ecranul de verificare**: facsimilul documentului lângă
câmpurile extrase, fiecare câmp cu proveniența lui (`AI 81%`, „corectat manual",
„lipsă") și bordură colorată pe praguri de încredere.

Coada merge singură mai departe: după aprobare sau respingere se deschide
următorul document, iar mesajul spune ce s-a întâmplat cu cel dinainte. Ruta
`next-review` primea `after` de la început — „scoate din coadă documentul
tocmai închis" — dar interfața nu o chema așa, deci operatorul rămânea pe
documentul aprobat și mai avea de făcut două lucruri pentru fiecare document
următor. Scurtături: `Alt+S` salvează, `Alt+A` aprobă, `Alt+N` sare peste
fără să atingă documentul.

**Backendul simulat** (`src/api/mock/`, ~3.769 linii) implementează 66 de rute cu
aceleași căi, paginare, filtrare, permisiuni și coduri de eroare ca API-ul real.
Comutarea se face din `VITE_API_MODE` — restul aplicației nu știe cine răspunde.

Alte lucruri gata: temă light/dark persistată, filtre în URL (o listă filtrată se
poate trimite unui coleg), sidebar colapsabil cu contoare live, accesibilitate
consecventă (`scope`, `role="alert"`, `sr-only`, `aria-label`).

### Backend — M2–M11 complet ✅

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

Rute reale existente **azi**: **64 de căi** sub `/api/v1`, cu 77 de operații
HTTP — plus cele trei `/health/*` de la rădăcină și `/internal/run-queue`, care nu
apare în OpenAPI pentru că nu face parte din contractul cu frontend-ul.

Ultima adăugată este `GET /roles`: matricea rol × permisiune, întreagă. Până la
ea, ecranul de roluri putea completa **o singură coloană** — a rolului cu care
ești autentificat, fiindcă doar atât expune `/me` — și își recunoștea limita
într-o notă de subsol. Nota era cinstită și inutilă: cine deschide „Roluri" vrea
să afle ce poate face un operator *înainte* de a-i da rolul.

### Verificat pe date reale, nu doar în teste

- Toate cele **13** migrări se aplică **și se dau înapoi** curat — verificat
  dus-întors la fiecare adăugare, nu presupus
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

### Două defecte găsite curățând, nu construind

Amândouă erau în afara e-Facturii, și amândouă s-au văzut punând întrebarea „ce
se întâmplă dacă cineva chiar rulează asta așa cum scrie în documentație".

**`SECRET_KEY` gol trecea verificarea de producție.** Ea se uita doar dacă
valoarea a rămas cea implicită — `startswith("dev-only")` —, iar șirul gol nu
începe cu nimic. Pe multe platforme o variabilă nedefinită ajunge la proces exact
ca șir gol, iar `docker-compose.yml` folosește chiar tiparul `${VAR:-}`. Cu o
cheie goală, HMAC-ul care semnează tokenurile de acces devine ghicibil: oricine
își semnează singur o sesiune de administrator. Acum se cere o lungime minimă de
32 de caractere, cât rezultatul lui SHA-256.

**Sub `docker compose`, nicio integrare nu putea funcționa.** Fișierul trecea
proceselor doar baza de date, storage-ul și providerii de extracție —
`MS_CLIENT_ID`, `ANAF_CLIENT_ID` și `DRIVE_TOKEN_KEY` nu ajungeau nici la API,
nici la worker. Ecranele spuneau cinstit „nu este configurată", deci nimic nu
minte; dar `DEPLOY.md` recomanda compose-ul ca stivă completă, iar el nu era.
Workerul are nevoie de aceleași valori ca API-ul: el sincronizează, și fără cheia
de criptare nu poate descifra tokenurile pe care le-a stocat API-ul.

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
| Extensiile pe tip de conținut erau scrise în **trei** locuri; la adăugarea facturii electronice două au fost aduse la zi și a treia nu, iar încărcarea unui XML cădea cu 500 după ce fișierul trecuse validarea | **suita E2E**, la prima rulare cu e-Factura |
| Filtrele de lună ofereau trei luni fixe din 2026, iar „Perioade" pornea implicit pe august 2026. Instalat în 2027, ecranul ar fi arătat o lună fără date și nicio cale de a alege alta | citind ce mai scrie în lista de datorie tehnică — unde era notat greșit ca fiind „doar în backendul simulat" |
| Panoul principal scria „pentru August 2026" deasupra unor cifre care veneau din `latest_active_month`: două luni diferite, același titlu | același loc |

**Auditul de producție (3 septembrie 2026)** — vezi `docs/FINAL_PRODUCTION_AUDIT.md`:

| Defect | Cum a fost găsit |
|---|---|
| `Total de plata: 1190,00 lei` era citit **119**. Tiparul sumei accepta grupuri de mii opționale, deci se oprea după trei cifre; orice sumă peste 999 scrisă fără separator intra trunchiată. Toate sumele din suită aveau ori separator de mii, ori sub patru cifre — exact formele care mergeau | **proba de fum pe o instalare complet nouă** |
| Sincronizarea cu OneDrive și emailul se pornea doar din cron. Pe un server propriu, cu worker și fără cron, nu sosea niciodată nimic, iar interfața arăta o conexiune activă | citind de unde se cheamă `run_drive_sync` |
| Detecția duplicatelor era `SELECT` + `INSERT` fără nimic între: patru încărcări simultane ale acelorași octeți intrau toate ca documente noi | **patru fire pe un server pornit** |
| Două ecrane livrate cereau `/messages` și `/clients/:id/messages` — rute care nu există. Unul rămânea gol, fără eroare | comparând rutele consumate de frontend cu cele implementate |
| Un build de producție fără `VITE_API_MODE` livra aplicația pe backendul simulat: clienți inventați, documente inventate, autentificare care acceptă orice parolă | citind implicitul din `client.ts` |
| CI ar fi trecut **verde** dacă PostgreSQL nu pornea: peste 900 de teste sărite, cod de ieșire 0 | citind `conftest.py` |
| Trei indexuri GIN trigram erau moarte: interogarea punea `coalesce`, indexul nu | `EXPLAIN ANALYZE` pe 20.000 de documente |
| Trei constrângeri `CHECK` din modele rămăseseră în urma migrărilor. `compare_metadata` nu compară corpul lor, deci testul de derivă nu le vedea | inventarul `pg_constraint` din baza migrată |
| Niciun antet de securitate pe răspunsurile API: existau doar pe fișiere și în `vercel.json` | **antetele unui server pornit** |
| `/demo` — pagină de demonstrație, neautentificată, în producție | inventarul rutelor |
| Nu exista **niciun** mod de a adăuga un client într-o bază de producție: `seed-dev` refuză să ruleze acolo, iar interfața nu avea formular. Rezolvat întâi cu `add-client`, apoi cu ecranul propriu-zis | încercând să instalez aplicația de la zero |
| `RATE_LIMIT_PER_MINUTE` stătea în configurare de la primul commit și nu îl citea niciun modul: o protecție care exista doar pe hârtie | căutând cine citește fiecare setare |
| Prima variantă a limitării număra **toate** încercările, nu doar eșecurile: al unsprezecelea login cu parola corectă dintr-un minut era refuzat | **două teste E2E căzute departe de cauză**, în mijlocul unui flux de documente |
| Pe un ecran de 390px, fiecare pagină depășea cu 50px, iar titlul din antet se strângea la lățime zero | măsurând lățimea reală pe trei viewporturi |
| Prima variantă a verificării de accesibilitate raporta opt câmpuri „fără etichetă”; erau toate corecte — verificarea nu cunoștea eticheta implicită | citind ce anume raportase |

---

## 3. Ce mai este de făcut

### Golul concret

Frontend-ul consumă **30 de rute**. Backendul real le implementează pe toate.

Erau 32, iar două — `GET /messages` și `GET /clients/:id/messages` — erau marcate
aici drept „Faza 2". Golul era cunoscut la nivel de rută; ce nu era cunoscut este
că **ecranele care le cereau erau totuși livrate**. În modul simulat mergeau; în
modul real una arăta o eroare, iar cealaltă rămânea goală fără să spună nimic.
Auditul de producție le-a făcut oneste, iar `e2e/pages.spec.ts` deschide acum
fiecare ecran și cade dacă vreunul cere ceva ce serverul nu are.

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
| ~~`/integrations/onedrive/*` — 13 rute~~ | ✅ M9, M10 |
| ~~`/integrations/anaf/*` — 8 rute, `GET /documents/:id/files/:fileId`~~ | ✅ M11 |
| ~~`GET /messages`, `GET /clients/:id/messages`~~ | scoase din interfață la auditul de producție; cronologia reală se poate construi pe `document_intakes` |

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
| **M7** | Rapoarte în SQL, setări reale, extracție din PDF, factura electronică, identificarea clientului, încărcare | ✅ (notificările au trecut în Faza 2 — cer un provider de email sau WhatsApp) |
| **M8** | CI + teste E2E | ✅ |
| **M9** | **Preluare automată din OneDrive/SharePoint, un dosar per client** | ✅ |
| **M10** | **Preluare automată din email; expeditorul identifică clientul** | ✅ |
| **M11** | **e-Factura: preluarea din SPV-ul ANAF, cu toate trei fișierele** | ✅ (descărcarea; trimiterea rămâne în Faza 2) |
| Faza 2 | WhatsApp, trimiterea e-Facturii către ANAF, OCR real pentru scanuri, remindere, export ZIP | |
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

**M7 — factura electronică (e-Factura, UBL 2.1)**

De la 1 iulie 2024, între firme din România factura electronică este obligatorie.
Pentru un cabinet asta înseamnă că partea covârșitoare a facturilor vine ca XML,
nu ca PDF scanat — și că, pentru ele, verificarea umană poate deveni o citire în
loc de o completare.

Un XML schimbă complet regula sub care e scris restul extracției. `pdf_text`
lucrează pe text și are o singură lege: *nu ghici*. Aici nu are ce să ghicească —
fiecare valoare stă într-un element cu nume. Nu se caută un total într-un text, se
citește câmpul „total". Nu există încredere parțială: elementul e acolo sau nu e.
De aceea valorile ies cu **100%**, marcate „citit", iar ecranul spune adevărul.

Se citește tot ce un PDF nu putea da: numele furnizorului și al cumpărătorului,
care într-un PDF stau într-un bloc de adresă fără etichetă și pe care extracția
din text refuza, corect, să le ghicească.

**Ce nu face, deliberat.** Nu vorbește cu ANAF: nu descarcă, nu trimite, nu
verifică semnătura. Sunt trei lucruri diferite, cu credențiale și implicații
proprii (Faza 2). Aici se citește un fișier care a ajuns deja la noi — local,
fără rețea, exact ca `pdf_text`. Și nu decide direcția facturii: știe cine e
furnizorul și cine cumpărătorul, dar nu pentru cine lucrează cabinetul. Aceea
rămâne treaba potrivirii de client, care funcționează neschimbată.

O **notă de credit** (storno) nu este propusă ca factură obișnuită: are semn
invers, iar trecută drept factură ar dubla suma în registru. Rămâne neclasificată,
adică se uită un om la ea.

**Securitate.** XML-ul vine din afară, iar parsarea XML este un vector clasic:
„billion laughs" (o entitate care se expandează până umple memoria) și XXE (un
document care citește `/etc/passwd`). Se parsează prin `defusedxml`, care refuză
DTD-urile și entitățile. Un fișier care conține așa ceva este **respins, nu
curățat** — o factură reală nu are DOCTYPE, deci refuzul nu costă niciun caz
legitim. Ambele atacuri au propriul test.

**Alegerea providerului se face după conținut, nu după configurare.**
`OCR_PROVIDER` este o singură valoare pentru tot procesul, dar un cabinet
primește în aceeași zi XML-uri, PDF-uri digitale și poze de bonuri. `local` le
rutează după ce sunt: XML la cititorul de e-Factura, restul la cel de PDF. Este
valoarea recomandată în producție, și cea pe care rulează suita E2E — deci se
verifică exact ce se rulează.

**Originalul rămâne XML în arhivă.** Un PDF „frumos" generat din el ar fi altceva
decât ce s-a depus la ANAF, iar §16 spune că originalul nu se transformă. Ecranul
de verificare arată în locul facsimilului factura redată din câmpurile ei —
spusă ca atare, cu documentul original la un clic distanță.

**M7 — luna, spusă de cine o știe**

Trei ecrane aveau luna scrisă de mână. Filtrele de pe „Documente" și „Perioade"
ofereau exact trei luni — august, iulie și iunie 2026 — iar „Perioade" pornea
implicit pe august 2026. Instalat în 2027, ecranul ar fi arătat o lună fără date
și nicio cale de a alege alta. Acum este un `<input type="month">`: orice lună e
accesibilă, nimic nu îmbătrânește, iar valoarea implicită vine dintr-un singur
loc (`lib/current-month.ts`), unde „acum" înseamnă ceasul real pe API-ul adevărat
și momentul setului sintetic în demonstrație.

Panoul principal era mai rău decât vechi: scria „Situația documentelor pentru
August 2026" deasupra unor cifre care veneau din `latest_active_month` — luna pe
care o spun **datele**, nu calendarul. Două luni diferite, același titlu. Serverul
trimite acum luna pe care o descriu cifrele, iar ecranul o afișează pe aceea; când
nu există niciun document, nu se inventează niciuna.

Distincția merită reținută, pentru că exact confuzia ei a produs defectul: **un
filtru alege de unde să pornească; un titlu afirmă ceva despre niște numere.**

**M9 — preluarea automată din OneDrive**

Cererea cabinetului, în cuvintele lui: *„în principiu mă interesa să îmi preia
automat ce documente trimit domnii clienți, să nu mai stau eu să le descarc și să
le numesc manual. Dacă merge să se conecteze direct librării din OneDrive exact
cum am eu făcute frumos pentru fiecare client ar fi perfect."*

Amândouă jumătățile erau deja pe jumătate rezolvate: numele standardizat există
din M5.7, iar `DocumentIntake` avea din M5.1 idempotență pe id-uri externe,
scrisă atunci pentru email și WhatsApp. Ce lipsea era cine aduce fișierele.

**Dosarul dă clientul, și asta este piesa cea mai valoroasă.** Contabilul are
deja un dosar per client; maparea aceea, făcută o singură dată, e mai sigură
decât orice citire de CUI — merge și pentru o poză neclară, fără text. Extracția
rămâne să spună *ce* este documentul; *al cui* este se știe de la intrare. Un
dosar nemapat nu ghicește nimic: fișierele intră și ajung la verificare
neatribuite, ca oricare altele.

**Ce nu face, deliberat:** nu scrie nimic înapoi în OneDrive. Documentele
clienților rămân exact cum le-au pus ei — un sistem care umblă în fișierele
altcuiva le strică într-o zi. Scope-ul cerut la consimțământ este `Files.Read.All`,
doar citire.

Trei proprietăți pe care se sprijină restul, fiecare cu testele ei:

- **Nimic nu intră de două ori.** Fiecare fișier lasă un intake cu id-ul lui din
  Graph, iar întrebarea se pune *înainte* de descărcare: un fișier deja preluat
  nu trece prin rețea. Peste asta lucrează și detecția pe SHA-256, pentru cazul
  în care același document apare în două dosare.
- **Un fișier stricat nu oprește dosarul.** Un `.txt`, un PDF corupt, o
  descărcare picată: se notează cu motivul și se trece mai departe.
- **Tokenul delta se salvează abia după ce fișierele au intrat.** Salvat înainte,
  o cădere la mijloc ar face ca fișierele nepreluate să nu mai fie văzute
  niciodată — cea mai urâtă formă de pierdere, pentru că e tăcută.

**Securitate.** Refresh tokenul Microsoft nu poate fi stocat hash-uit — trebuie
folosit — iar ce se citește înapoi dintr-un dump de bază de date dă acces la
OneDrive-ul cabinetului. Se criptează cu `DRIVE_TOKEN_KEY`, **separată de
`SECRET_KEY`**: aceea se rotește exact după o scurgere, adică exact când nimeni
nu vrea să afle că a pierdut și legăturile cu OneDrive. Fără cheie, conectarea
este refuzată cu un mesaj explicit — nu se scrie niciun token în clar „doar de
data asta". Un sweep peste toate răspunsurile rutei verifică faptul că tokenul nu
iese nici întreg, nici trunchiat (§73).

`state`-ul consimțământului este **semnat și legat de organizație**. Fără asta,
un link pregătit de altcineva ar conecta cabinetului un OneDrive străin, din care
ar citi apoi tot ce intră.

**Ce rămâne neverificat, spus pe față.** Microsoft nu poate fi chemat dintr-un
test. Tot ce contează — sincronizarea, idempotența, erorile, granița organizației
— se exercită prin protocolul din `services/drive/base.py`, cu un client fals.
Ce nu se poate testa este clientul HTTP real, care e deliberat subțire:
construiește URL-uri și citește JSON. Prima conectare cu credențiale adevărate
rămâne singura care îl atinge.

**Un defect găsit rulând serverul:** `?parentId=` nu se lega. Un parametru de
query nu trece prin `ApiModel`, deci nu primește aliasul camelCase de la sine;
FastAPI căuta `parent_id`, nu găsea nimic și răspundea tăcut cu rădăcina.
Răsfoirea *părea* că merge, dar nu cobora niciodată într-un subdosar. Aceeași
clasă de defect ca „filtrele de listă nu se legau deloc", din M6.

**M10 — preluarea din email**

Cealaltă jumătate a lui *„ce documente trimit domnii clienți"*: unii le pun în
dosarul lor din OneDrive, ceilalți le trimit pe email. Acum amândouă drumurile
duc în același loc, pe **aceeași conexiune Microsoft** — un singur consimțământ,
două surse.

**Aici clientul îl dă expeditorul, nu dosarul.** Este singura diferență de fond
față de M9, și ea decide restul: într-o cutie poștală intră toți clienții
deodată, deci maparea trebuie făcută pe mesaj. Adresa de pe email se caută
printre contactele din CRM (`contacts.email`), care există de la M4. Consecința
practică pentru cabinet: ce trebuie ținut la zi sunt **adresele de contact**, nu
o mapare de dosare.

Un expeditor necunoscut nu oprește nimic — atașamentul intră și rămâne
neatribuit. Mai bine să ajungă la un om decât să nu intre deloc: atunci nimeni nu
ar ști că a venit. Iar o adresă care apare la doi clienți — un contabil care e
contact la două firme — nu se ghicește: se scoate din hartă și decide omul.

**Ce nu este un document.** Logo-ul din semnătura expeditorului este tot un
atașament. Se sar cele marcate `inline` și cele sub 8 KB; altfel fiecare email ar
produce trei „documente" de respins manual, iar o listă plină de gunoi se citește
la fel de prost ca una goală.

**O redenumire, făcută acum cât nu costă.** `drive_connections` ținea deja un
cont Microsoft, nu un drive: același token deschide și OneDrive, și cutia
poștală. Numele devenea o minciună în momentul în care emailul se adaugă pe
aceeași conexiune. Tabela este acum `microsoft_connections`, iar pachetul
`app/services/microsoft/`.

**Ce rămâne neverificat, la fel ca la M9:** clientul HTTP care chiar vorbește cu
Graph. Restul — potrivirea expeditorului, idempotența, filtrarea semnăturilor,
erorile, granița organizației — se exercită cu un client fals, prin protocol.

**M11 — e-Factura: preluarea din SPV-ul ANAF**

A treia sursă, și cea care aduce astăzi cele mai multe documente: de la 1 iulie
2024 factura electronică este obligatorie între firme, deci partea covârșitoare a
facturilor unui cabinet nu mai vine nici pe email, nici într-un dosar — stă în
SPV-ul fiecărui client.

**Trei fișiere, un singur document.** ANAF dă o arhivă ZIP care conține factura
(XML, UBL 2.1) și sigiliul lui electronic; din XML se obține, de la convertorul
public al ANAF, PDF-ul în forma tipăribilă oficială. Toate trei se păstrează, pe
același document: un contabil vede *o factură*, iar dacă ar fi trei documente,
detectarea duplicatelor, luna contabilă și arhivarea ar trebui fiecare să știe
care dintre ele „este" factura. `document_versions.kind` avea deja forma
potrivită — a primit două valori noi, `anaf_zip` și `anaf_pdf`.

**Care dintre ele contează cel mai mult.** Arhiva. Ea poartă sigiliul, adică
dovada că factura a fost acceptată, și este singura care **nu se poate reface**:
XML-ul este membru al ei, iar PDF-ul se regenerează oricând. De aceea se
stochează octet cu octet, nerecompusă — un ZIP rescris de noi ar avea alt hash și
ar înceta să mai fie o dovadă — și de aceea se scrie **înaintea** PDF-ului. Când
convertorul ANAF cade, factura și dovada sunt deja salvate, iar lipsa PDF-ului se
scrie pe document, unde o vede un om, nu doar în log.

Nota aceea promitea, în prima variantă, că PDF-ul „se reface prin reprocesare".
Nu era adevărat: reprocesarea cheamă extracția, care citește XML-ul deja stocat,
nu convertorul ANAF. O oră proastă a ANAF ar fi lăsat facturile din ea fără forma
tipăribilă **pentru totdeauna**, cu o promisiune scrisă pe un document contabil.
Turul de sincronizare reia acum conversiile lipsă (cel mult cinci pe tur) și
șterge nota odată cu motivul ei — iar reluarea nu are nevoie de certificat,
pentru că convertorul este public: merge și când autorizarea a expirat, adică
exact când nimic altceva nu merge.

**Aici clientul nu se ghicește.** Este singura sursă din tot sistemul cu această
proprietate: interogarea se face pe CUI-ul clientului, deci apartenența vine din
cerere, nu dintr-o citire. La drive o dă dosarul, la email expeditorul — amândouă
pot greși; aici nu are ce.

**Ce ține locul tokenului delta.** ANAF nu dă tokenuri de continuare, ci ferestre
de timp în milisecunde. `anaf_mandates.synced_through` ține minte până unde am
citit și avansează **abia după** ce facturile din fereastră au intrat — la fel ca
tokenul delta, din același motiv: închisă pe o eroare, fereastra ar pierde tăcut
tot ce nu s-a apucat să citească. Fereastra nouă se suprapune cinci minute peste
cea închisă, pentru că un mesaj apărut chiar în secunda închiderii ar cădea
altfel exact între două ferestre; repetarea nu costă nimic, `id_descarcare`
oprește orice al doilea document.

**Adevăratul cost al funcționalității nu este tehnic.** Certificatul digital
singur nu deschide nimic: pentru fiecare client, ANAF cere o împuternicire
depusă în SPV (formularul 150). Fără ea, interogarea **nu întoarce eroare —
întoarce gol**, care este forma cea mai neplăcută de refuz, pentru că nu se
strică nimic vizibil. De aceea `anaf_mandates` există ca tabel separat și de
aceea refuzul apare pe rândul clientului, cu ce are de făcut, nu într-un log.

Trei ciudățenii ale API-ului ANAF, toate tratate explicit pentru că fiecare
produce un defect tăcut: „nu există mesaje" vine ca **eroare** în corpul
răspunsului, nu ca listă goală; cererile fără `User-Agent` primesc 403, ceea ce
seamănă cu o problemă de drepturi; iar convertorul XML→PDF întoarce erorile de
validare tot cu 200, deci un „PDF" care începe cu `{` ar ajunge în arhivă și s-ar
descoperi abia când l-ar deschide cineva.

**Nu trimite facturi**, deliberat. `/upload` și `stareMesaj` există în API și nu
sunt implementate: a emite un document fiscal în numele unui client este altă
răspundere decât a-l descărca pe cel deja emis, și nu se strecoară într-o funcție
de preluare.

**Ce rămâne neverificat: drumul întreg către ANAF.** Autorizarea cere un
certificat digital calificat prezentat fizic de browser — nu există cont de
serviciu, iar mediul de test al ANAF îl cere la fel. **NOT VERIFIED — EXTERNAL
CREDENTIAL REQUIRED.** Ce *se* verifică: despachetarea arhivei, idempotența,
atribuirea, fereastra de timp, împuternicirea lipsă, convertorul căzut, granița
organizației — toate prin protocol, cu un client fals; plus clientul HTTP însuși,
cu un transport fals, care acoperă construcția URL-urilor și cele trei ciudățenii
de mai sus.

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
| ~~`react-hook-form`, `zod`, `@hookform/resolvers`~~ | scoase la auditul de producție: nimic nu le importa |
| ~~primitivele shadcn (`button`, `card`, `badge`, `separator`)~~ | scoase odată cu pagina `/demo`, singura care le folosea. `components.json` rămâne: `npx shadcn add <componentă>` le aduce înapoi când chiar sunt necesare |
| numărul total la căutarea în documente | pagina se ia în 2 ms; `COUNT(*)` peste `OR`-ul care traversează tabela clienților ia 140 ms pe 20.000 de documente. Se poate rezolva doar denormalizând numele clientului pe document sau renunțând la totalul exact la căutarea textuală — niciuna nu merită încă |
| corpul cererii de upload | fișierul este primit **întreg** înainte ca aplicația să-l poată refuza (măsurat: 150 MB refuzați în 1,3 s). Limita trebuie pusă și în proxy-ul din față — vezi `docs/DEPLOY.md` |
| ~~`"2026-08"` hardcodat în 6 locuri~~ | rezolvat, și **nu era doar în backendul simulat**, cum scria aici: erau trei luni fixe din 2026 în filtrele reale de pe „Documente" și „Perioade", plus titlul panoului principal. Vezi mai jos |
| ~~`client_ip()` ignoră `X-Forwarded-For`~~ | rezolvat: `TRUSTED_PROXY_COUNT` spune câte proxy-uri stau obligatoriu în față, iar adresa se citește numărând **de la dreapta**. Implicit 0 — antetul se ignoră până când cineva declară explicit prin ce trece cererea. Pe Vercel se pune 1 |
| ~~`oxlint`: 2 warning-uri~~ | dispărute odată cu fișierele shadcn |
| codul `INTERNAL_ERROR` pe un răspuns 405 | eticheta este greșită, dar nu schimbă nimic: frontendul decide reîncercarea după status, nu după cod. Un cod nou ar însemna o schimbare de contract pentru zero câștig |
