# Manifest de release

Ce anume se lansează, de ce depinde, și ce trebuie făcut în ziua pornirii.
Se completează la fiecare release.

---

## Release curent

| | |
|---|---|
| **Data** | 8 septembrie 2026 |
| **Commit** | `0502b67` |
| **Migrare de bază de date** | `c4e9b21a7f38` — *Contorul incercarilor, vazut de toate instantele* |
| **Migrări în total, de la zero** | 28 |
| **Backend** | Python 3.13, FastAPI 0.141, SQLAlchemy 2.0.52 |
| **Frontend** | React 19, Vite 8, TypeScript 6 |
| **Worker** | același pachet; `python -m app.worker` |
| **Bază de date** | PostgreSQL **17** |

### Ce aduce față de releaseul anterior (`a61e9e5`)

| | |
|---|---|
| **Semnal de viață al workerului** | tabel nou, endpoint `/health/workers`, alertare externă posibilă. Închide P1-01. |
| **Primul administrator** | politica de parole a aplicației se aplică și la `create-admin` |
| **Rutele de sănătate** | răspund controlat și când baza este jos: 503, nu 500 cu traceback |
| **Contract de query params** | test care oprește reapariția defectului G-01 pe orice rută |
| **Fără reușite false la stocare** | teste pentru disc plin și fișier lipsă la arhivare |
| **Documentație operațională** | monitorizare, incidente, release gate, runbooks, UAT contabil |

---

## Verificări la această versiune

| | Rezultat |
|---|---|
| Teste backend | **2.028 passed**, 1 sărit |
| Teste frontend | **419 passed** |
| Teste end-to-end (browser real, backend real) | **93 passed** |
| `ruff check` + `ruff format --check` | curat |
| `mypy --strict` (180 module) | curat |
| `tsc --noEmit`, `oxlint`, `npm run build` | curat |
| `npm audit` (runtime și dev) | **0 vulnerabilități** |
| Migrări de la zero, pe bază goală | 29, până la `c4e9b21a7f38` |
| Copie + restaurare, executate | **da** — 6 secunde, fișiere identice pe octet |
| Izolare între cabinete | 64/64 rute parametrizate |

---

## Variabile de mediu obligatorii

Numele, nu valorile. Lista completă și explicată:
[PRODUCTION_ENVIRONMENT_VARIABLES.md](PRODUCTION_ENVIRONMENT_VARIABLES.md).

**Fără acestea, aplicația refuză să pornească în producție:**

```text
DATABASE_URL
SECRET_KEY                 (>= 32 caractere, generat pentru aceasta instalare)
PUBLIC_BASE_URL            (adresa reala, nu localhost)
CORS_ALLOWED_ORIGINS
OCR_PROVIDER               (local recomandat; mock este refuzat)
ENVIRONMENT=production
```

**Necesare pentru funcționare completă:**

```text
DRIVE_TOKEN_KEY            (cripteaza tokenurile integrarilor)
CRON_SECRET                (gol = rutele interne refuza orice)
STORAGE_PATH               (volum persistent) sau S3_*
DEFAULT_TIMEZONE=Europe/Bucharest
WORKER_HEARTBEAT_TIMEOUT_SECONDS=90
```

**Frontend, la build:**

```text
VITE_API_MODE=http         (fara ea, build-ul se opreste)
```

---

## Servicii externe

Detalii complete:
[PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md](PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md).

**Obligatorii:**

| Serviciu | Stare la release |
|---|---|
| PostgreSQL 17 | verificat rulând |
| Stocare (disc local sau S3) | disc verificat rulând; S3 `MOCK VERIFIED` |
| Găzduire + domeniu + TLS | de configurat |
| Monitorizare externă (`/health/ready`, `/health/workers`) | **de configurat — nu există în aplicație** |

**Opționale, niciuna verificată live:**

| Serviciu | Stare |
|---|---|
| SMTP | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| Microsoft Graph | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| IMAP | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| ANAF / SPV | `NOT VERIFIED — PROVIDER ACCESS REQUIRED` |
| Anthropic (extragere / asistent) | `NOT VERIFIED — CREDENTIALS REQUIRED` |

**Neimplementate, deliberat:** WhatsApp API, SAGA, Sentry/OTLP, retenție
automată, plăți, analytics.

---

## Limitări cunoscute

Nu sunt defecte — sunt alegeri, cu motivul lor.

| Limitare | De ce | Referință |
|---|---|---|
| **Deploy cu întrerupere** (5–15 min) | migrările rulează cu workerul oprit; la scara unui cabinet, o fereastră anunțată e mai sigură decât migrări compatibile în ambele sensuri | [PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md) |
| **Lista de tranzacții bancare nu are paginare** | are plafon cu refuz explicit, nu trunchiere; ecranul cere întotdeauna un extras anume, iar un extras lunar are zeci–sute de rânduri | vezi mai jos |
| **Nicio alertare în aplicație** | ar fi presupus un furnizor; adresele de sănătate sunt acolo, monitorul este extern | [PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md) |
| **Fără retenție automată** | ce se șterge și când este o decizie a cabinetului, nu una tehnică | [ACCOUNTING_UAT_CHECKLIST.md](ACCOUNTING_UAT_CHECKLIST.md) K1 |
| **Fără export SAGA** | formatul nu este public; unul ghicit ar pune cifre greșite în contabilitate | [SAGA.md](SAGA.md) |
| **Fără preluare automată din WhatsApp** | cere cont WhatsApp Business și număr aprobat de Meta; importul manual cu proveniență scrisă există | [DOCUMENT_PROCESSING.md](DOCUMENT_PROCESSING.md) |
| **Termenele declarațiilor neconfirmate** | aplicația nu interpretează legislația | [ACCOUNTING_UAT_CHECKLIST.md](ACCOUNTING_UAT_CHECKLIST.md) |

### Despre paginarea tranzacțiilor bancare — decizia

Evaluată la această poartă și **amânată deliberat**:

- ecranul cere întotdeauna un extras anume, iar un extras lunar are zeci, cel
  mult sute de rânduri — paginarea nu ar schimba nimic pentru utilizator;
- ruta are deja un plafon care **refuză explicit** peste 1000 de rânduri, în loc
  să trunchieze: o listă tăiată arată exact ca una completă, iar într-o
  reconciliere rândul lipsă este chiar cel căutat;
- N+1-ul a fost reparat, deci costul unei pagini mari nu mai crește cu numărul
  de rânduri;
- schimbarea formei răspunsului ar rupe contractul cu interfața fără câștig
  pentru cabinet.

Se reia dacă un cabinet ajunge la extrase de peste o mie de rânduri.

---

## Verificări în ziua pornirii

Lista completă, de bifat: [PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md).

**Cele care opresc lansarea dacă nu trec:**

```text
[ ] Secrete generate pentru aceasta instalare (SECRET_KEY, DRIVE_TOKEN_KEY, CRON_SECRET)
[ ] Primul administrator creat cu create-admin, fara parola implicita
[ ] Copie de siguranta RESTAURATA o data, cu check-storage trecut
```

**Imediat după:**

```text
[ ] /health/ready   -> 200, database true
[ ] /health/workers -> 200
[ ] Proba de fum completa (15 pasi)
[ ] Monitorizarea externa configurata SI pornita
[ ] Datele de expirare trecute in calendar
```

---

## Rollback

Procedura: secțiunea ROLLBACK din
[PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md).

**Migrarea acestui release (`c4e9b21a7f38`) creează o tabelă nouă și nu atinge
nimic existent.** Rollback-ul aplicației este sigur fără `downgrade`: versiunea
veche pur și simplu ignoră tabela. Nu se pierd date.

Dacă totuși vrei să dai înapoi și schema, `alembic downgrade d7c2a41f8b95`
șterge doar `worker_heartbeats` — semnale de viață, nu date de cabinet.

---

## Cine răspunde

Se completează la punerea în funcțiune.

| Rol | Nume | Contact |
|---|---|---|
| Proprietar aplicație | ________ | ________ |
| Administrator cabinet | ________ | ________ |
| Responsabil infrastructură | ________ | ________ |
| Contabil care semnează UAT-ul | ________ | ________ |
