# Poarta de release

Ce se face în ziua lansării și la fiecare deploy de după. Se parcurge **în
ordine**. Fiecare secțiune are un pas care oprește: dacă nu trece, nu se merge
mai departe.

Pentru „ce conturi îmi trebuie", vezi
[PRODUCTION_SETUP_ACCOUNTS.md](PRODUCTION_SETUP_ACCOUNTS.md). Pentru „ce fac când
se strică", [PRODUCTION_INCIDENT_RUNBOOK.md](PRODUCTION_INCIDENT_RUNBOOK.md).

---

## PRE-DEPLOY

Cu o zi înainte. Nimic din ce urmează nu atinge producția.

```text
[ ] Toate testele trec pe commit-ul care se lansează
    cd backend  && uv run ruff check . && uv run ruff format --check .
                && uv run mypy app && uv run pytest
    cd frontend && npm run lint && npx tsc --noEmit -p tsconfig.app.json
                && npm test -- --run && npm run build
    cd frontend && npm run test:e2e

[ ] Migrările merg de la zero, pe o bază goală
    createdb contacrm_verificare
    DATABASE_URL=... uv run alembic upgrade head
    DATABASE_URL=... uv run alembic current      # trebuie sa fie la head

[ ] Nicio migrare nu este distructivă fără decizie scrisă
    (coloane sterse, tabele sterse, tipuri schimbate — vezi ROLLBACK mai jos)

[ ] Secretele sunt generate pentru ACEASTA instalare, nu copiate
    SECRET_KEY, DRIVE_TOKEN_KEY, CRON_SECRET

[ ] .env nu este in git, si niciun secret nu a fost vreodata comis
    git ls-files | grep -E "^\.env$"          # gol
    git log --all --diff-filter=A --name-only | grep -iE "\.env$|\.pem$"

[ ] Copia de siguranta de dinainte de deploy exista si este PROASPATA
    (vezi sectiunea DEPLOY, pasul 1)

[ ] Fereastra de mentenanta anuntata cabinetului
    Aplicatia NU suporta deploy fara intrerupere — vezi mai jos.
```

> **STOP.** Dacă suita nu este verde, nu se lansează. Un test roșu ignorat o dată
> nu se mai citește niciodată.

---

## DEPLOY

Ordinea contează. Pașii 1 și 3 nu se sar niciodată.

```text
1.  [ ] COPIE DE SIGURANTA, inainte de orice
        pg_dump --format=custom --no-owner "$DATABASE_URL" > pre-deploy-$(date +%F-%H%M).dump
        cp -a "$STORAGE_PATH" /backup/storage-pre-deploy-$(date +%F-%H%M)
        # Baza INTAI, fisierele dupa. Motivul, in RUNBOOK.md.

2.  [ ] Opreste workerul (nu API-ul inca)
        docker compose stop worker
        # Un worker care lucreaza in timpul migrarii vede o schema pe jumatate.

3.  [ ] MIGRARILE, inainte de a promova versiunea noua
        uv run --directory backend alembic upgrade head
        # Daca esueaza: NU promova aplicatia. Vezi ROLLBACK.

4.  [ ] Promoveaza backendul
        docker compose up -d backend

5.  [ ] Health: aplicatia raspunde si vede baza
        curl -sS https://domeniul-tau/health/ready
        # Trebuie: HTTP 200, "status":"ok", "database":true

6.  [ ] Porneste workerul
        docker compose up -d worker

7.  [ ] Health: workerul bate
        curl -sS https://domeniul-tau/health/workers
        # Trebuie: HTTP 200, "status":"ok". Poate dura pana la un tur.

8.  [ ] Promoveaza frontendul
        # Verifica intai ca build-ul a fost facut cu VITE_API_MODE=http.

9.  [ ] Planificatorul (cron) ruleaza si are CRON_SECRET-ul corect
```

---

## POST-DEPLOY

Imediat după, cu ochii pe ecran. **Nu pleca de la calculator până nu trec.**

```text
[ ] Fumul: login -> panou -> un client -> un document -> descarcare
    (lista completa mai jos)

[ ] /health/ready      -> 200, database true, worker healthy
[ ] /health/workers    -> 200
[ ] Documente -> In procesare: coada se goleste, nu creste

[ ] Urca un document real si urmareste-l pana la arhiva
[ ] Descarca-l inapoi si deschide-l

[ ] Jurnalul nu are erori noi
    docker compose logs --since=10m backend worker | grep -i error

[ ] Integrarile configurate au adus ceva
    Administrare -> Surse documente / e-Factura: ultima sincronizare

[ ] Monitorizarea externa vede ambele adrese si este PORNITA
```

### Proba de fum, în ordine

```text
1.  [ ] Autentificare
2.  [ ] Panoul se incarca, fara erori in consola browserului
3.  [ ] Lista de clienti; deschide unul
4.  [ ] Perioada curenta a clientului
5.  [ ] Incarca un document (PDF real)
6.  [ ] Documentul intra in procesare si iese din ea
7.  [ ] Ecranul de verificare: campurile citite se vad
8.  [ ] Corecteaza un camp si salveaza
9.  [ ] Aproba
10. [ ] Arhiveaza
11. [ ] Descarca din arhiva — se deschide, e acelasi fisier
12. [ ] Creeaza o sarcina
13. [ ] Administrare -> Audit: actiunile de mai sus apar
14. [ ] Descarca registrul lunii (CSV) si deschide-l in Excel
15. [ ] Delogare; sesiunea chiar se inchide
```

---

## ROLLBACK

Se hotărăște **repede**. Dacă proba de fum cade la un pas care atinge documente,
nu depana în producție — dă înapoi și depanează pe o copie.

### Aplicația (backend, worker, frontend)

```text
[ ] Promoveaza imaginea/commit-ul anterior
[ ] Reporneste backend + worker
[ ] Verifica /health/ready si /health/workers
```

Este partea ușoară. Procesele nu țin stare: coada este în baza de date, iar un
job rămas `RUNNING` se repune cu `recover-processing`.

### Migrările — **partea care nu se face automat**

**Nu rula `alembic downgrade` fără să citești ce face migrarea.** Un `downgrade`
care șterge o coloană **șterge datele din ea**, iar acelea nu se mai întorc din
aplicație.

Regula, pe tipuri de migrare:

| Ce face migrarea | Rollback |
|---|---|
| Adaugă o tabelă sau o coloană **nullable** | **Nu da înapoi.** Versiunea veche o ignoră. Cel mai sigur. |
| Adaugă un index sau o constrângere | `downgrade` este sigur; nu se pierd date |
| Redenumește sau schimbă tipul unei coloane | `downgrade` **poate pierde date**. Restaurează din copia de dinainte de deploy |
| Șterge o coloană sau o tabelă | `downgrade` **nu poate reface datele**. Restaurare din copie, obligatoriu |

**Când restaurezi din copie:** procedura completă în [RUNBOOK.md](RUNBOOK.md).
Nu uita `check-storage` la final — baza și fișierele trebuie să fie din același
moment.

### Ce nu se dă înapoi

**Documentele urcate după deploy.** Dacă restaurezi baza la starea de dinainte,
ele rămân pe disc fără rând în bază: `check-storage` le va raporta ca fișiere în
plus (inofensive), dar munca de la momentul respectiv se pierde.

De aceea fereastra de mentenanță este anunțată și scurtă: cât timp cabinetul nu
lucrează, nu se pierde nimic la un rollback.

---

## INCIDENT

Dacă ceva se strică **după** ce deploy-ul a fost declarat reușit:
[PRODUCTION_INCIDENT_RUNBOOK.md](PRODUCTION_INCIDENT_RUNBOOK.md).

Verificarea de treizeci de secunde, pentru început:

```bash
curl -s https://domeniul-tău/health/ready
curl -s https://domeniul-tău/health/workers
docker compose logs --tail=100 backend worker
```

---

## Despre „zero downtime"

**Aplicația nu suportă deploy fără întrerupere, și nu se pretinde că suportă.**

Motivul este migrarea: pasul 3 rulează `alembic upgrade head` cu workerul oprit,
iar între migrare și promovarea backendului există un interval în care schema
este nouă și codul este vechi. La scara unui cabinet contabil, o fereastră de
câteva minute, anunțată, este mai ieftină și mult mai sigură decât mecanica
necesară pentru migrări compatibile în ambele sensuri.

**Fereastră de mentenanță așteptată: 5–15 minute**, în afara programului.

Ce se întâmplă cu ce era în lucru:

- **cererile HTTP în zbor** se pierd; utilizatorul reîncarcă pagina;
- **documentele în coadă rămân în coadă** — coada este un tabel, nu memorie;
- **jobul care rula** rămâne `RUNNING` și se repune cu `recover-processing`;
- **nimic nu se pierde din ce a fost salvat.**

---

## RPO și RTO — ținte, nu garanții

Sunt **ținte propuse**, pe baza a ce s-a măsurat efectiv. Nu sunt garantate: nu
există încă o instalare de producție pe care să fi fost măsurate, iar valorile
reale depind de furnizorul de găzduire și de disciplina copiilor de siguranță.

| | Țintă | De unde vine |
|---|---|---|
| **RPO** (cât se poate pierde) | **maximum 24 de ore** | copie zilnică; se poate coborî la o oră cu copii mai dese sau WAL archiving |
| **RTO** (cât durează revenirea) | **maximum 4 ore** | restaurarea măsurată a durat **6 secunde** pe un set mic; restul este timp de om: observare, decizie, acces la server, verificare |

Restaurarea a fost parcursă integral, cu verificare: numărul de rânduri și
SHA-256-ul fiecărui fișier identice, aplicația pornită peste baza restaurată,
document descărcat. Vezi [FINAL_PRODUCTION_BUILD.md](FINAL_PRODUCTION_BUILD.md).

**Ca RPO-ul de 24 de ore să fie real**, copia trebuie să ruleze automat și să fie
verificată. O copie care nu s-a restaurat niciodată nu este o copie.
