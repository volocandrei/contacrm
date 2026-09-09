# Raport — pregătirea deploy-ului pe Vercel

**8 septembrie 2026.** Ce s-a inspectat, ce s-a schimbat, de ce, și ce
împiedică deploy-ul acum.

---

## 1. Ce s-a inspectat

Repository-ul întreg, cu accent pe ce atinge deploy-ul: `vercel.json` (rădăcină
și `frontend/`), `app/main.py`, `app/core/config.py`, abstracția de stocare,
`app/worker.py`, rutele de cron, autentificarea și cookie-urile, CORS, rutele de
sănătate, Alembic, `docker-compose.yml`, `pyproject.toml`, `package.json`, și
documentația de producție existentă.

Arborele de lucru era **curat**, pe `ead8f94`.

**Verificat împotriva documentației Vercel curente**, nu din memorie: cheia
`services` din `vercel.json` este sintaxa actuală pentru mai multe servicii
într-un proiect, iar `framework: "fastapi"` cu `entrypoint` este forma
documentată. **Configurarea existentă era deja corectă** — nu a fost nevoie de
niciun `api/index.py` și de nicio rescriere.

## 2. Ce s-a schimbat, și de ce fiecare

Trei schimbări. Toate au apărut din întrebarea „ce se rupe pe Vercel și nu se
rupe pe un server obișnuit".

### V-01 · P0 · Documentele s-ar fi scris pe un disc care dispare

Pe Vercel, fiecare invocare primește un filesystem propriu, aruncat la final.
`STORAGE_PROVIDER=local` acolo **nu eșuează**: scrierea în `/tmp` reușește,
providerul întoarce o cheie, documentul primește rând în baza de date și apare pe
ecran ca oricare altul. Abia la invocarea următoare fișierul nu mai există — iar
atunci există deja un rând care spune că există.

Nu exista nicio apărare. Aceasta este categoria pe care auditul o numește
blocantă: **pierdere tăcută de date**.

**Reparat:** `assert_storage_is_persistent()` oprește pornirea pe o platformă cu
filesystem efemer (`VERCEL`, `AWS_LAMBDA_FUNCTION_NAME`) dacă
`STORAGE_PROVIDER != s3`. Rulează **indiferent de `ENVIRONMENT`** — un deploy
lăsat pe `development` ar fi sărit peste toate verificările, iar discul este
efemer oricum l-am numi. Mesajul spune exact ce trebuie pus.

Nu interzice `local` în general: pe un server cu volum persistent rămâne
configurarea corectă și implicitul. Șase teste; la mutație, trei cad.

### V-02 · P1 · Alarma pentru worker ar fi sunat la nesfârșit

Pe Vercel nu există proces continuu: coada se execută prin
`GET /api/v1/internal/run-queue`, chemat de Vercel Cron. Ruta aceea făcea toată
munca workerului — dar **nu scria semnul de viață**.

Consecința: `/health/workers` ar fi raportat permanent „nu a raportat niciodată",
monitorul extern ar fi sunat la fiecare verificare, iar după a treia zi nimeni nu
s-ar mai fi uitat la el. **O alarmă care sună mereu este o alarmă oprită** — iar
semnalul construit exact ca să prindă un worker mort ar fi fost primul ignorat.

**Reparat:** ruta de cron bate acum, înaintea muncii, în tranzacție proprie, cu
eșecul înghițit (bătutul este un semnal despre muncă, nu munca însăși). Două
teste, inclusiv contra-proba că o cerere **neautorizată** nu scrie nimic — altfel
oricine ar fi putut ține alarma tăcută fără să știe secretul.

### V-03 · P2 · Durata funcției nu era declarată

Un tur de cron face muncă mărginită (5 documente, 3 fișiere per sursă externă),
dar apelurile către Graph/ANAF/IMAP pot dura. Fără `maxDuration`, se aplica
implicitul platformei.

**Reparat:** `maxDuration: 60` pe serviciul de backend, în `vercel.json`. Dacă un
tur se întrerupe, jobul rămâne `PENDING` și se reia — coada este un outbox
tranzacțional, nu memorie.

### V-04 · P1 · Pragul alarmei era construit pentru alt ritm

Continuarea directă a lui V-02. Semnul de viață se scria acum și din cron — dar
pragul de la care workerul este declarat mort rămăsese **90 de secunde**, adică
implicitul pentru workerul continuu, care bate la fiecare tur de două secunde.

Pe Vercel bătaia vine la cinci minute. Nouăzeci de secunde ar fi fost depășite
**între oricare două bătăi**: `/health/workers` ar fi răspuns 503 la fiecare
verificare, pe o instalare perfect sănătoasă. Exact eroarea pe care V-02 o
repara, mutată cu un pas mai încolo.

Reparația de până acum era o propoziție în documentație — „ridică variabila cu
mâna, la 400". Iar documentul se contrazicea singur: blocul de variabile de
copiat, cu douăzeci de rânduri mai sus, scria `WORKER_HEARTBEAT_TIMEOUT_SECONDS=90`.
Cine copia blocul — adică toată lumea — obținea alarma falsă.

**Reparat:** pragul se derivă din platformă. Pe un filesystem efemer, trei ture
de cron (`3 × CRON_TICK_SECONDS`); pe un server, cele 90 de secunde rămân. **O
valoare pusă explicit câștigă în continuare** — cine știe ce face nu este
contrazis de un implicit. Variabila a fost scoasă din blocurile de copiat pentru
Vercel și păstrată, cu explicație, pentru instalarea pe server.

### V-05 · P1 · Reamintirile către clienți nu ar fi plecat niciodată

`/internal/reminders` și `/internal/daily-digest` existau, erau testate și nu
aveau cron. Pe un server le cheamă planificatorul sistemului; pe Vercel nu există
niciun proces care să pornească singur. O rută internă fără cron **nu dă eroare,
nu apare în loguri și nu lipsește din interfață** — pur și simplu nu se execută.

Pentru un cabinet, asta înseamnă că reamintirile de termen nu ajung la clienți.
Adică fix lucrul pentru care se cumpără aplicația, tăcut, la nesfârșit.

**Reparat:** ambele au cron (06:00 și 06:30 UTC — 08:00/09:00 ora României, după
sezon). Rămân **oprite din configurare** până când cabinetul le pornește; un cron
care cheamă o funcție oprită costă o milisecundă.

Iar regula a fost scrisă ca test, nu ca notă: `tests/test_cron_contract.py`
citește rutele din aplicația construită și cronurile din `vercel.json`, și cere
ca fiecare să aibă corespondent în cealaltă listă. O rută internă adăugată mâine
intră singură în verificare. Același test leagă intervalul cronului de
`CRON_TICK_SECONDS` — cele două stau în fișiere diferite și nu au voie să plece
unul fără celălalt.

### V-06 · P2 · O demonstrație arăta exact ca aplicația adevărată

Cel mai periculos scenariu documentat până acum se apăra printr-o propoziție:
„intră cu o parolă greșită; trebuie să fii refuzat". Dacă proiectul se importă cu
Root Directory = `frontend/`, se folosește `frontend/vercel.json`, care fixează
`VITE_API_MODE=mock`: aplicația pornește normal, arată identic, și acceptă
**orice parolă**, pentru că autentificarea simulată nu se uită la ea.

Verificarea aceea cere ca cineva să și-o amintească. Un cabinet care își vede
numele pe ecran nu o să și-o amintească.

**Reparat:** un build de producție pe date simulate poartă o bandă permanentă, pe
fiecare ecran, inclusiv pe cel de intrare — acolo unde „orice parolă merge" costă
cel mai mult. Nu refuză să pornească: o demonstrație este o folosință legitimă.
Refuză doar să tacă.

### V-07 · P1 · Limita încercărilor de parolă slăbea exact când era nevoie de ea

Contorul de încercări eșuate stătea în memoria procesului de API. Pe un server cu
un container asta funcționează, iar `app/core/rate_limit.py` spunea deschis unde
nu: „pe o platformă care pornește un proces per cerere nu limitează nimic".

Platforma de deploy este exact aceea. Și este mai rău decât „nu limitează":
serverless-ul **pornește instanțe noi când crește traficul** — adică fix ce
produce cineva care încearcă parole una după alta. Cu cât se apăsa mai tare, cu
atât contorul se împărțea în mai multe bucăți. Protecția slăbea singură, în
clipa în care conta.

Ceea ce ne întoarce la propoziția din care s-a născut modulul acela: *o variabilă
care promite o protecție inexistentă este mai rea decât absența ei.* Un contor per
proces, pe o platformă fără procese stabile, promite la fel de mult.

**Reparat:** contorul stă într-un rând de bază de date, împărțit de toate
instanțele. **Fără Redis** — nu este nevoie: fereastra este de un minut, cheile
sunt puține, iar scrierea se face **numai la eșec**, deci o autentificare
reușită nu atinge tabelul. Aceleași două operații ca înainte (`blocked` înainte
de încercare, `record` numai după un eșec), aceleași praguri, aceleași chei.

Trei alegeri care contează:

- **Tranzacție proprie.** Refuzul se ridică drept eroare de aplicație, iar
  `CommittingRoute` nu confirmă tranzacția când ruta ridică ceva. Un eșec numărat
  în sesiunea cererii s-ar fi șters odată cu ea — adică exact încercările de
  ținut minte ar fi dispărut.
- **Lasă să treacă dacă baza nu răspunde.** Un refuz acolo ar transforma o
  clipire a bazei într-o pană de autentificare pentru tot cabinetul; pasul
  următor are oricum nevoie de bază și va eșua cu eroarea potrivită.
- **Curățenie la fiecare tur de worker.** Altfel tabelul ar fi crescut cu un rând
  per adresă care a greșit vreodată o parolă.

Aceeași schimbare acoperă asistentul — unde contorul este singurul plafon de
cheltuială către un API plătit, iar înmulțirea lui cu numărul de instanțe l-ar fi
desființat tocmai când se cheltuiește mai mult — și portalul clientului.

**Ce nu înlocuiește:** limitarea de la marginea rețelei. Un atac distribuit, cu o
adresă nouă la fiecare încercare, trece pe lângă orice contor per cheie; acela se
oprește la firewall. Ce apără aici este cazul obișnuit: multe parole pe un cont,
sau o parolă pe multe conturi.

> Detaliul care spune de ce nu se vedea: cu contorul per instanță, **toate**
> testele existente treceau. Testele folosesc un singur obiect limitator, deci
> întrebau mereu aceeași memorie. Testul nou pornește două — ca două instanțe de
> API — și abia atunci se vede.

### V-08 · P0 · Comanda de copiere de siguranță nu rula — și putea copia altă bază

Găsit executând procedura, nu citind-o. `docs/RUNBOOK.md` scria:

```bash
pg_dump --format=custom --no-owner "$DATABASE_URL" > contacrm-$(date +%F).dump
```

`DATABASE_URL` este scrisă în dialect SQLAlchemy — `postgresql+psycopg://…` — iar
`pg_dump` **nu recunoaște schema aceea ca URI**. Nu se plânge de ea: o tratează ca
nume de bază de date și se conectează cu setările implicite, adică în altă parte,
ca alt utilizator.

Ce urmează depinde de noroc, și ambele capete sunt proaste:

- cu parolă cerută → `password authentication failed for user <utilizatorul de
  sistem>`, un mesaj care te trimite să cauți o problemă de parolă acolo unde este
  o problemă de adresă — exact în minutul în care ai nevoie de o copie;
- cu `trust` sau un `.pgpass` potrivit → **comanda reușește și copiază altă bază**,
  iar fișierul are dimensiune, dată și un nume liniștitor.

O copie care nu conține nimic se descoperă la restaurare. Nu există moment mai
prost, și este chiar prioritatea întâi din enunț: **siguranța datelor**.

**Reparat** în cele trei locuri unde apărea (runbook-ul de copiere și restaurare,
poarta de release, runbook-ul de incident): dialectul se scoate o dată,
`PGURL="${DATABASE_URL/+psycopg/}"`, iar procedura începe cu întrebarea *cu ce
bază vorbesc de fapt* — `psql "$PGURL" -Atc "select current_database()"`.

Regula este acum un test: `tests/test_runbook_commands.py` citește documentația și
refuză orice unealtă PostgreSQL care primește `$DATABASE_URL` direct.

### Ce NU s-a schimbat, deliberat

- **arhitectura** — nimic rescris, nimic înlocuit;
- **abstracția de stocare** — S3 exista deja implementat și testat; s-a
  configurat, nu s-a rescris;
- **coada** — rămâne outbox în PostgreSQL; **nu s-a introdus Redis**;
- **`vercel.json` de la rădăcină** — era deja corect;
- **autentificarea, CORS, antetele, izolarea** — neatinse;
- **WhatsApp** — rămâne `wa.me`; **SAGA** — rămâne blocat.

## 3. Arhitectura de deploy

Un proiect Vercel, două servicii, aceeași origine — necesar pentru cookie-ul
`SameSite=Lax`, altfel previzualizarea documentelor ar returna 401. Detaliile și
procedura: [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md).

```
utilizator ──▶ Vercel ──┬── /api/*  → FastAPI  ──▶ PostgreSQL (extern)
                        │                      ──▶ S3 (extern)
                        └── /*      → Vite (static)
             Vercel Cron ──▶ /api/v1/internal/run-queue   (*/5 * * * *)
```

## 4–7. Proiect, URL, commit

| | |
|---|---|
| Proiect Vercel | **niciunul** — nu s-a putut crea |
| URL de producție | **niciunul** |
| Commit pregătit | HEAD-ul acestei ramuri |

## 8. Teste

| Suită | Rezultat |
|---|---|
| Backend | **2.032 passed**, 1 sărit · `ruff` + `ruff format --check` + `mypy --strict` (180 module) curate |
| Frontend | **419 passed** · `oxlint` + `tsc` curate · build cu `VITE_API_MODE=http` curat |
| End-to-end, browser real | **93 passed** |

Diferența față de baseline-ul din enunț (1.972, la `a61e9e5`) este explicată în
[VERCEL_RELEASE_MANIFEST.md](VERCEL_RELEASE_MANIFEST.md): **+61 de teste backend
adăugate, niciunul șters sau slăbit.**

Testul sărit nu este o slăbire și nu este nou: este cazul parametrizat pentru o
obligație **fără calendar**, care nu are termen de calculat. Ce trebuie să fie
adevărat despre ea — că nu produce nicio perioadă și că refuzul spune de ce — se
verifică în două teste dedicate, imediat sub el.

## 9. Teste de fum

**Neexecutate pe Vercel** — nu există deployment.

Lanțul a fost verificat pe o **instalare locală complet nouă**: bază goală → 29
de migrări → 46 de tabele → `create-admin` → autentificare → al doilea utilizator
→ client → document urcat → descărcat octet cu octet → audit → delogare. **11
din 11.** Plus copie, distrugere, restaurare: 6 secunde, amprentă identică.

Proba a fost **reluată pe schema de acum** — `pg_dump` custom, bază nouă,
`pg_restore`: 46 de tabele, aceleași numărători de rânduri pe fiecare, inclusiv
rândul din tabela adăugată în această rundă. Reluarea a scos la iveală V-08.

## 10–12. Bază de date, stocare, autentificare

| | |
|---|---|
| Bază de date | PostgreSQL extern, **neprovizionat**. `create_all()` nu se folosește nicăieri |
| Stocare | S3 obligatoriu pe Vercel, **neprovizionat**. Garda V-01 oprește pornirea cu `local` |
| Autentificare | argon2id, cookie `HttpOnly`/`Secure`/`SameSite=Lax`, politica de parole aplicată inclusiv primului administrator. Limita încercărilor este acum împărțită de toate instanțele (V-07) |

## 13. Securitate

O singură schimbare: **V-07**, limita încercărilor de parolă, care pe o
platformă serverless nu limita nimic. Ce rămâne valabil din auditul anterior: izolare pe
64/64 rute parametrizate, `CORS_ALLOWED_ORIGINS` refuză `*` prin validator,
antete de securitate din aplicație, zero secrete în cod și în istoria git.

Verificat în plus aici: rutele interne răspund **404** fără `CRON_SECRET`, iar o
cerere neautorizată nu atinge baza.

## 14. Cron

Declarat în `vercel.json`, la 5 minute, către `/api/v1/internal/run-queue`.
Vercel trimite `Authorization: Bearer <CRON_SECRET>` — exact ce așteaptă ruta.
**Netestat pe platformă.**

Rezumatul zilnic (`/internal/daily-digest`, 06:30 UTC) și memento-urile
(`/internal/reminders`, 06:00 UTC) au și ele cron — vezi V-05. Trei cronuri în
total; cadența de cinci minute cere un plan care o permite.

Corespondența dintre rute și cronuri este ținută de un test, nu de memorie:
`tests/test_cron_contract.py`.

## 15. Worker

Clasificare, cum s-a cerut:

| Sarcină | Pe Vercel |
|---|---|
| coada de procesare | **Vercel Cron** |
| sincronizarea surselor externe | **Vercel Cron**, în același tur |
| recuperarea joburilor abandonate | **Vercel Cron**, în același tur |
| rezumat zilnic, memento-uri | **Vercel Cron**, declarat (06:00 / 06:30 UTC) |
| worker ca proces continuu | **imposibil pe Vercel** — și nu se pretinde altfel |

Nu s-a simulat niciun worker persistent într-o cerere.

## 16. Monitorizare

**Neconfigurată.** Aplicația expune semnalele și le testează; alertarea rămâne
externă. Ce trebuie pus, cu valori:
[PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md).

Blocantul `P1-01` **nu este închis**: rămâne deschis până când un serviciu extern
interoghează efectiv `/health/ready` și `/health/workers`.

Pragul workerului **nu mai trebuie reglat cu mâna** pe Vercel: se derivă din
intervalul cronului (V-04). O valoare pusă explicit câștigă oricum.

## 17. Copii de siguranță

**Vercel nu este o copie de siguranță** și nu ține nici baza, nici documentele.
Procedura rămâne externă, verificată: `pg_dump` + copia stocării, în ordinea
bază-întâi, apoi `check-storage`. Vezi [RUNBOOK.md](RUNBOOK.md).

## 18. Integrări

Toate: `NOT LIVE VERIFIED`. Lista completă în
[VERCEL_RELEASE_MANIFEST.md](VERCEL_RELEASE_MANIFEST.md).

## 19. Avertismente cunoscute

1. Riscul de build în modul demonstrație, dacă Root Directory este `frontend/`.
   **Acum se anunță singur** printr-o bandă permanentă (V-06), dar verificarea
   rămâne valabilă: intră cu o parolă greșită — trebuie să fii refuzat.
2. Latență de până la 5 minute la procesare (interval de cron).
3. Migrările nu rulează automat.
4. Deploy cu întrerupere la release cu migrări.
5. Cele trei cronuri cer un plan Vercel care permite cadența de cinci minute.
6. Reamintirile și rezumatul zilnic au cron, dar rămân **oprite din
   configurare** până când cabinetul le pornește și există SMTP.

## 20. Rollback

**Aplicația:** *Deployments* → deployment-ul anterior → **Promote to
Production**. Instant, fără build.

**Baza de date — separat, niciodată automat.** Migrarea curentă
(`c4e9b21a7f38`) adaugă o tabelă și nu atinge nimic existent, deci rollback-ul
aplicației este sigur fără `downgrade`. Regula pe tipuri de migrare:
[PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md).

---

# VERDICT

## VERCEL DEPLOYMENT BLOCKED

Codul și configurarea sunt pregătite. Deploy-ul nu se poate executa: lipsesc
**patru prerechizite externe**, iar trei dintre ele sunt condiții pe care chiar
enunțul le pune ca oprire („Do not deploy if: production secrets are missing;
storage is not persistent; database is not persistent").

| # | Blocant | De ce oprește | Ce dezblochează |
|---|---|---|---|
| **B-1** | **Vercel GitHub App neinstalată** pentru `volocandrei/contacrm` | Vercel refuză să lege repo-ul: `400 — To link a GitHub repository, you need to install the GitHub integration first` | Un clic: https://github.com/apps/vercel |
| **B-2** | **Nicio bază de date PostgreSQL** | Aplicația nu pornește fără `DATABASE_URL`; migrările n-au unde rula | Un PostgreSQL 17 accesibil public (Neon, Supabase, RDS) |
| **B-3** | **Niciun bucket S3** | Garda V-01 oprește pornirea; fără ea, documentele s-ar pierde tăcut | Un bucket S3-compatibil **nepublic** (R2, Supabase, AWS) |
| **B-4** | **Niciun domeniu** | `PUBLIC_BASE_URL` pe un URL de preview produce linkuri care mor la următorul deploy | Un domeniu îndreptat către proiect |

**Nu sunt defecte de cod.** Sunt lucruri de procurat, iar trei dintre ele
costă bani și cer decizii care nu sunt ale mele.

De asemenea, niciuna dintre cele trei porți **P0** din
[PRODUCTION_LAUNCH_CHECKLIST.md](PRODUCTION_LAUNCH_CHECKLIST.md) nu poate fi
trecută fără B-2 și B-3: secretele se generează pentru o instalare care nu
există, primul administrator se creează într-o bază care nu există, iar copia de
siguranță nu are ce restaura.

## Ce se întâmplă după ce blocantele cad

Ordinea, cu ce am verificat deja pregătit:

1. instalezi GitHub App → import proiect, **Root Directory = rădăcina repo-ului**;
2. provizionezi PostgreSQL și bucketul S3;
3. generez secretele și le pun în Vercel (Production);
4. rulez `alembic upgrade head` către baza reală;
5. creez primul administrator cu `create-admin`;
6. **preview** → lista de verificare, inclusiv proba cu parola greșită;
7. domeniu, `PUBLIC_BASE_URL`, `CORS_ALLOWED_ORIGINS`;
8. **producție**;
9. proba de fum, apoi monitorul extern;
10. prima copie de siguranță și **o restaurare**.

Procedura completă: [VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md).
