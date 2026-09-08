# Manifest de release Vercel

Ce s-a pregătit, ce s-a verificat, ce lipsește. Se completează la deploy-ul real.

> **Stare: deploy-ul de producție NU a fost executat.** Câmpurile marcate
> `________` se completează atunci. Ce urmează este verificat pe cod și
> configurare, nu pe o instalare vie.

---

## Versiunea

| | |
|---|---|
| **Commit pregătit** | `________` *(HEAD la momentul deploy-ului)* |
| **Commit de referință al auditului** | `a61e9e5` |
| **Migrare de bază de date** | `a1c8f30d5e72` |
| **Migrări de la zero** | 28 |
| **Proiect Vercel** | `________` *(neconfigurat)* |
| **URL de producție** | `________` *(fără domeniu)* |
| **URL de preview** | `________` |

## Infrastructura

| | Stare |
|---|---|
| **Bază de date** | `________` — **neprovizionată**. Cerință: PostgreSQL 17 extern, cu TLS |
| **Stocare documente** | `________` — **neprovizionată**. Cerință: bucket S3-compatibil, **nepublic** |
| **Domeniu** | `________` — neconfigurat |
| **Monitor extern** | `________` — neconfigurat |

## Variabile de mediu — NUME, niciodată valori

Se pun în *Project Settings → Environment Variables*, target **Production**.
Explicate în
[PRODUCTION_ENVIRONMENT_VARIABLES.md](PRODUCTION_ENVIRONMENT_VARIABLES.md).

**Opresc pornirea dacă lipsesc:**

```text
ENVIRONMENT
DATABASE_URL
SECRET_KEY
PUBLIC_BASE_URL
CORS_ALLOWED_ORIGINS
OCR_PROVIDER
STORAGE_PROVIDER
S3_BUCKET
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
```

**Necesare pentru funcționare completă:**

```text
S3_ENDPOINT_URL
S3_REGION
DRIVE_TOKEN_KEY
CRON_SECRET
DEFAULT_TIMEZONE
TRUSTED_PROXY_COUNT
DB_EXTERNAL_POOLER
WORKER_HEARTBEAT_TIMEOUT_SECONDS
```

**Frontend, la build:**

```text
VITE_API_MODE
```

**Opționale, per integrare** (niciuna configurată):

```text
MS_CLIENT_ID  MS_CLIENT_SECRET  MS_TENANT_ID  MS_REDIRECT_URI
ANAF_CLIENT_ID  ANAF_CLIENT_SECRET  ANAF_REDIRECT_URI  ANAF_ENVIRONMENT
SMTP_HOST  SMTP_PORT  SMTP_USER  SMTP_PASSWORD  SMTP_FROM  NOTIFICATIONS_ENABLED
AI_API_KEY  AI_MODEL  AI_PROVIDER
ASSISTANT_API_KEY  ASSISTANT_PROVIDER
```

## Migrări

| | |
|---|---|
| Mecanism | `alembic upgrade head`, rulat manual către baza externă |
| `create_all()` ca migrare | **nu se folosește nicăieri** — verificat prin căutare |
| Aplicate pe baza de producție | **nu** — nu există bază |
| Verificate pe bază goală | **da** — 28 de migrări, 45 de tabele |

## Teste rulate

| Suită | Rezultat |
|---|---|
| Backend (`pytest`) | **2.007 passed** |
| `ruff check` + `ruff format --check` | curat |
| `mypy --strict` (178 module) | curat |
| Frontend (`vitest`) | **415 passed** |
| `oxlint` + `tsc --noEmit` | curat |
| `npm run build` cu `VITE_API_MODE=http` | curat |
| End-to-end, browser real | **93 passed** |

**De ce numerele diferă de baseline-ul din enunț** (1.972 backend): acela este de
la `a61e9e5`. Între timp s-au adăugat teste, niciunul șters sau slăbit:

| Rundă | Δ | Ce s-a adăugat |
|---|---|---|
| Poarta de release (`db42b0e`) | +27 | heartbeat worker, politica parolei primului admin, contract de query params, eșecuri de stocare, volum pe liste |
| Pregătirea Vercel (aici) | +8 | garda de filesystem efemer (6), bătaia din ruta de cron (2) |

## Teste de fum

**Neexecutate** — nu există deployment. Lista de parcurs după deploy:
[VERCEL_DEPLOYMENT.md](VERCEL_DEPLOYMENT.md) și
[PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md).

Verificat însă pe o **instalare locală complet nouă**, ca probă a lanțului:
bază goală → migrări → `create-admin` → autentificare → al doilea utilizator →
client → document urcat → descărcat octet cu octet → audit → delogare:
**11 din 11**.

## Integrări

Vocabular fără ambiguitate, cum s-a cerut.

| Integrare | Stare |
|---|---|
| PostgreSQL | `NOT LIVE VERIFIED` — neprovizionată. Verificată local, rulând |
| Stocare S3 | `NOT LIVE VERIFIED` — neprovizionată. Implementarea verificată pe `moto` |
| Microsoft Graph | `NOT LIVE VERIFIED` — fără credențiale |
| IMAP | `NOT LIVE VERIFIED` — fără cutie poștală |
| SMTP | `NOT LIVE VERIFIED` — fără credențiale |
| ANAF / SPV | `NOT LIVE VERIFIED` — fără certificat calificat |
| Anthropic (extragere) | `NOT LIVE VERIFIED` — fără cheie |
| Anthropic (asistent) | `NOT LIVE VERIFIED` — fără cheie |
| WhatsApp | `NOT IMPLEMENTED` — deliberat; rămâne `wa.me` |
| SAGA | `NOT IMPLEMENTED` — lipsește specificația |
| Vercel Cron | `NOT LIVE VERIFIED` — declarat în `vercel.json`, netestat pe platformă |
| Monitor extern | `NOT CONFIGURED` |

## Avertismente operaționale cunoscute

1. **Workerul rulează doar prin cron** pe Vercel — nu există proces continuu.
   Latență de până la 5 minute la procesare. Coada este durabilă, deci nimic nu
   se pierde.
2. **`WORKER_HEARTBEAT_TIMEOUT_SECONDS` trebuie ridicat** peste intervalul
   cronului (≈400s pentru cron la 5 minute). Implicitul de 90s este pentru un
   worker continuu și ar produce alarme false.
3. **Migrările nu rulează automat** — pas manual înainte de fiecare promovare.
4. **Deploy cu întrerupere** la release cu migrări: 5–15 minute.
5. **Rezumatul zilnic și memento-urile** au nevoie de câte un cron în plus, dacă
   se folosesc.
6. **Riscul de build în modul demonstrație:** dacă proiectul se importă cu Root
   Directory = `frontend/`, se folosește `frontend/vercel.json`, care fixează
   `VITE_API_MODE=mock` — aplicația ar arăta identic, pe date inventate, cu o
   autentificare care acceptă orice parolă. Verificarea care o prinde: **intră cu
   o parolă greșită; trebuie să fii refuzat.**
