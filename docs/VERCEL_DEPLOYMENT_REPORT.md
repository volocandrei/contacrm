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
| Backend | **2.007 passed** · `ruff` + `ruff format --check` + `mypy --strict` curate |
| Frontend | **415 passed** · `oxlint` + `tsc` curate · build cu `VITE_API_MODE=http` curat |
| End-to-end, browser real | **93 passed** |

Diferența față de baseline-ul din enunț (1.972, la `a61e9e5`) este explicată în
[VERCEL_RELEASE_MANIFEST.md](VERCEL_RELEASE_MANIFEST.md): **+35 de teste
adăugate, niciunul șters sau slăbit.**

## 9. Teste de fum

**Neexecutate pe Vercel** — nu există deployment.

Lanțul a fost verificat pe o **instalare locală complet nouă**: bază goală → 28
de migrări → 45 de tabele → `create-admin` → autentificare → al doilea utilizator
→ client → document urcat → descărcat octet cu octet → audit → delogare. **11
din 11.** Plus copie, distrugere, restaurare: 6 secunde, amprentă identică.

## 10–12. Bază de date, stocare, autentificare

| | |
|---|---|
| Bază de date | PostgreSQL extern, **neprovizionat**. `create_all()` nu se folosește nicăieri |
| Stocare | S3 obligatoriu pe Vercel, **neprovizionat**. Garda V-01 oprește pornirea cu `local` |
| Autentificare | neatinsă: argon2id, cookie `HttpOnly`/`Secure`/`SameSite=Lax`, politica de parole aplicată inclusiv primului administrator |

## 13. Securitate

Neatinsă de această rundă. Ce rămâne valabil din auditul anterior: izolare pe
64/64 rute parametrizate, `CORS_ALLOWED_ORIGINS` refuză `*` prin validator,
antete de securitate din aplicație, zero secrete în cod și în istoria git.

Verificat în plus aici: rutele interne răspund **404** fără `CRON_SECRET`, iar o
cerere neautorizată nu atinge baza.

## 14. Cron

Declarat în `vercel.json`, la 5 minute, către `/api/v1/internal/run-queue`.
Vercel trimite `Authorization: Bearer <CRON_SECRET>` — exact ce așteaptă ruta.
**Netestat pe platformă.**

Rezumatul zilnic și memento-urile au nevoie de câte un cron în plus, dacă se
folosesc.

## 15. Worker

Clasificare, cum s-a cerut:

| Sarcină | Pe Vercel |
|---|---|
| coada de procesare | **Vercel Cron** |
| sincronizarea surselor externe | **Vercel Cron**, în același tur |
| recuperarea joburilor abandonate | **Vercel Cron**, în același tur |
| rezumat zilnic, memento-uri | **Vercel Cron**, de adăugat |
| worker ca proces continuu | **imposibil pe Vercel** — și nu se pretinde altfel |

Nu s-a simulat niciun worker persistent într-o cerere.

## 16. Monitorizare

**Neconfigurată.** Aplicația expune semnalele și le testează; alertarea rămâne
externă. Ce trebuie pus, cu valori:
[PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md).

Blocantul `P1-01` **nu este închis**: rămâne deschis până când un serviciu extern
interoghează efectiv `/health/ready` și `/health/workers`.

Pe Vercel, `WORKER_HEARTBEAT_TIMEOUT_SECONDS` trebuie ridicat peste intervalul
cronului (≈400s), altfel alarma sună între ture.

## 17. Copii de siguranță

**Vercel nu este o copie de siguranță** și nu ține nici baza, nici documentele.
Procedura rămâne externă, verificată: `pg_dump` + copia stocării, în ordinea
bază-întâi, apoi `check-storage`. Vezi [RUNBOOK.md](RUNBOOK.md).

## 18. Integrări

Toate: `NOT LIVE VERIFIED`. Lista completă în
[VERCEL_RELEASE_MANIFEST.md](VERCEL_RELEASE_MANIFEST.md).

## 19. Avertismente cunoscute

1. Riscul de build în modul demonstrație, dacă Root Directory este `frontend/`.
   **Verificarea care îl prinde: intră cu o parolă greșită — trebuie să fii
   refuzat.**
2. Latență de până la 5 minute la procesare (interval de cron).
3. Migrările nu rulează automat.
4. Deploy cu întrerupere la release cu migrări.
5. `WORKER_HEARTBEAT_TIMEOUT_SECONDS` trebuie ajustat pentru cron.

## 20. Rollback

**Aplicația:** *Deployments* → deployment-ul anterior → **Promote to
Production**. Instant, fără build.

**Baza de date — separat, niciodată automat.** Migrarea curentă
(`a1c8f30d5e72`) adaugă o tabelă și nu atinge nimic existent, deci rollback-ul
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
