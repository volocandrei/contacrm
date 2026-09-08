# Variabilele de mediu — lista completă

Toate cele **71 de variabile** pe care le citește aplicația, plus cele 4 pe care
le citește `docker-compose.yml` și cele 11 marcate `NEIMPLEMENTAT`. Lista este
generată din `Settings` (`backend/app/core/config.py`), nu scrisă din memorie.

**Aici sunt doar NUME.** Nicio valoare secretă nu apare în acest fișier și nu are
voie să apară niciodată — nici în `.env.example`, nici în cod, nici în frontend.

Un test ține lista sincronizată cu codul:
`backend/tests/test_env_example_contract.py` cade dacă apare un câmp nou care nu
e în `.env.example`, sau o variabilă în `.env.example` pe care n-o citește nimeni.

**Legendă:** *Secret* = valoarea trebuie ținută într-un manager de secrete, nu
într-un fișier trimis pe email. *Producție* = ce trebuie pus înainte de LIVE.

---

## Blochează pornirea în producție dacă lipsesc

`Settings.assert_production_ready()` refuză să pornească fără ele. Nu ocoli
mesajul: spune exact ce lipsește.

| Variabilă | Rol | Secret | Producție |
|---|---|:--:|---|
| `SECRET_KEY` | Semnează tokenurile de sesiune. Minimum 32 de caractere; cea implicită este refuzată | **DA** | generează una nouă pentru **această** instalare |
| `PUBLIC_BASE_URL` | Adresa reală; linkurile trimise clienților se compun cu ea | nu | `https://domeniul-tău` — pe `localhost` pornirea se oprește |
| `OCR_PROVIDER` | Motorul de extragere | nu | `local` (recomandat) sau `hybrid`. **`mock` este refuzat în producție** — inventează date contabile |
| `AI_API_KEY` | Cheia modelului care citește pozele | **DA** | obligatorie doar dacă `OCR_PROVIDER` este `vision` sau `hybrid` |
| `ASSISTANT_API_KEY` | Cheia asistentului | **DA** | obligatorie doar dacă `ASSISTANT_PROVIDER=anthropic` |
| `S3_BUCKET` | Bucketul de documente | nu | obligatoriu doar dacă `STORAGE_PROVIDER=s3` |

## Aplicație

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `ENVIRONMENT` | `development` \| `staging` \| `production` | `development` | nu |
| `APP_NAME` | Numele afișat | `ContaCRM` | nu |
| `API_V1_PREFIX` | Prefixul API | `/api/v1` | nu |
| `DEFAULT_LOCALE` | Limba | `ro` | nu |
| `DEFAULT_TIMEZONE` | **Fusul cabinetului.** Termenele se calculează pe ziua cabinetului, nu a serverului | `Europe/Bucharest` | nu |
| `LOG_LEVEL` | Nivelul de log | `INFO` | nu |

## Securitate și sesiuni

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `SECRET_KEY` | Semnătura tokenurilor | *(dev)* | **DA** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durata tokenului de acces | `15` | nu |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Durata sesiunii | `14` | nu |
| `CORS_ALLOWED_ORIGINS` | Originile permise, enumerate. **Caracterul universal `*` este refuzat** | `http://localhost:5173` | nu |
| `PUBLIC_BASE_URL` | Adresa publică | `http://localhost:5173` | nu |
| `LOGIN_ATTEMPTS_PER_MINUTE` | Încercări pe cont, pe minut, de la o adresă | `10` | nu |
| `LOGIN_ATTEMPTS_PER_ADDRESS_PER_MINUTE` | Încercări totale de la o adresă. Separat, fiindcă sunt două atacuri diferite | `60` | nu |
| `CRON_SECRET` | Secretul planificatorului. **Gol = rutele interne refuză orice** | `""` | **DA** |
| `TRUSTED_PROXY_COUNT` | Câte proxy-uri stau în față. Sub acest număr, `X-Forwarded-For` se ignoră | `0` | nu |
| `DRIVE_TOKEN_KEY` | Criptează refresh tokenurile OneDrive/ANAF și parolele IMAP înainte de bază. **Separată de `SECRET_KEY`**, deliberat | `""` | **DA** |

> Algoritmul de hash al parolelor **nu este configurabil**: este argon2id, ales în
> `app/core/security.py`. A existat aici o variabilă `PASSWORD_HASH_ALGORITHM` pe
> care nu o citea nimeni; a fost scoasă, fiindcă lăsa pe cineva să creadă că a
> schimbat o decizie de securitate pe care nu a schimbat-o.

## Bază de date

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `DATABASE_URL` | Conexiunea PostgreSQL 17 | *(dev)* | **DA** (conține parola) |
| `DB_ECHO` | Loghează SQL-ul | `false` | nu |
| `DB_POOL_SIZE` | Conexiuni în pool | `5` | nu |
| `DB_MAX_OVERFLOW` | Conexiuni peste pool | `10` | nu |
| `DB_EXTERNAL_POOLER` | `true` când `DATABASE_URL` arată spre un pooler în mod tranzacție (PgBouncer, Supabase `:6543`). Fără el, instrucțiunile pregătite se rup tăcut | `false` | nu |

Citite de `docker-compose.yml`, nu de aplicație: `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, `BACKEND_PORT`.

## Stocarea documentelor

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `STORAGE_PROVIDER` | `local` \| `s3`. O valoare necunoscută oprește pornirea | `local` | nu |
| `STORAGE_PATH` | Rădăcina pe disc. **Volum persistent**, nu în container | `./storage` | nu |
| `ARCHIVE_ROOT` | Unde se arhivează lunile închise | `./storage/ARHIVA` | nu |
| `MAX_UPLOAD_SIZE_MB` | Limita per fișier | `25` | nu |
| `ALLOWED_MIME_TYPES` | Tipurile acceptate, determinate din conținut | PDF, XML, JPEG, PNG, WEBP | nu |
| `S3_BUCKET` | Bucketul | `""` | nu |
| `S3_ENDPOINT_URL` | Gol = AWS; altfel adresa R2/Supabase/MinIO | `""` | nu |
| `S3_REGION` | Regiunea | `eu-central-1` | nu |
| `S3_ACCESS_KEY_ID` | Cheia de acces | `""` | **DA** |
| `S3_SECRET_ACCESS_KEY` | Secretul | `""` | **DA** |
| `S3_PREFIX` | Separă medii care împart un bucket | `""` | nu |

## Extragerea datelor (OCR / AI)

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `OCR_PROVIDER` | `mock` \| `pdf_text` \| `efactura` \| `local` \| `vision` \| `hybrid` | `mock` | nu |
| `AI_PROVIDER` | `mock` \| `anthropic`. **Nu alege** providerul — spune al cui este modelul, pentru verificarea de consistență și ecranul de setări. O valoare necunoscută oprește pornirea | `mock` | nu |
| `AI_API_KEY` | Cheia modelului care **vede documentele** | `""` | **DA** |
| `AI_MODEL` | Modelul folosit | `claude-sonnet-5` | nu |
| `PROMPT_VERSION` | Se scrie pe fiecare document citit, pentru trasabilitate | `v1` | nu |
| `CONFIDENCE_AUTO_THRESHOLD` | Peste cât s-ar putea aproba automat | `0.90` | nu |
| `CONFIDENCE_REVIEW_THRESHOLD` | Sub cât se cere verificare | `0.70` | nu |
| `AUTO_APPROVE_ENABLED` | Aprobare fără om. **Oprită implicit**: este o decizie de business | `false` | nu |
| `MAX_PROCESSING_ATTEMPTS` | Reprocesări automate înainte de `ERROR` | `3` | nu |
| `PROCESSING_STALE_AFTER_MINUTES` | După cât un job `RUNNING` se consideră abandonat | `15` | nu |
| `REFERENCE_PERIOD_STRATEGY` | Din ce se derivă **luna contabilă**: `document_date` \| `received_at` (ADR-008) | `document_date` | nu |

## Microsoft (OneDrive / SharePoint / email)

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `MS_CLIENT_ID` | Aplicația din Entra ID. Gol = integrarea spune că nu e configurată | `""` | nu |
| `MS_CLIENT_SECRET` | Secretul ei. **Expiră** — vezi inventarul | `""` | **DA** |
| `MS_TENANT_ID` | `common` acceptă orice cont; id-ul propriu restrânge | `common` | nu |
| `MS_REDIRECT_URI` | Trebuie **identic** cu cel din Entra ID | *(dev)* | nu |
| `DRIVE_SYNC_BATCH` | Fișiere per tur, per dosar | `50` | nu |
| `MAIL_SYNC_BATCH` | Mesaje per tur | `25` | nu |

## IMAP

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `IMAP_SYNC_BATCH` | Mesaje citite pe bătaie | `15` | nu |

Gazda, utilizatorul și parola se configurează **per cabinet, din interfață** —
parola se criptează cu `DRIVE_TOKEN_KEY` înainte de bază.

## ANAF / e-Factura

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `ANAF_CLIENT_ID` | Aplicația din portalul OAuth ANAF | `""` | nu |
| `ANAF_CLIENT_SECRET` | Secretul ei | `""` | **DA** |
| `ANAF_REDIRECT_URI` | Trebuie identic cu cel înregistrat | *(dev)* | nu |
| `ANAF_ENVIRONMENT` | `prod` \| `test`. **Baze complet separate.** Lăsat pe `test`, raportează „nicio factură" la nesfârșit | `prod` | nu |
| `ANAF_SYNC_BATCH` | Facturi per tur, per client | `25` | nu |
| `ANAF_LOOKBACK_DAYS` | Cât în urmă privește prima sincronizare (ANAF nu acceptă peste 60) | `30` | nu |

## Email trimis (SMTP)

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `NOTIFICATIONS_ENABLED` | **Comutatorul principal.** Oprit, nimic nu pleacă — nici cu SMTP configurat | `false` | nu |
| `SMTP_HOST` | Serverul. Gol = trimiterea spune că nu e configurată | `""` | nu |
| `SMTP_PORT` | Portul | `587` | nu |
| `SMTP_USER` | Utilizatorul | `""` | nu |
| `SMTP_PASSWORD` | Parola | `""` | **DA** |
| `SMTP_FROM` | Expeditorul; gol = `SMTP_USER` | `""` | nu |
| `SMTP_STARTTLS` | `true` pentru 587, `false` pentru 465 | `true` | nu |
| `DAILY_DIGEST_ENABLED` | Rezumatul zilnic **către cabinet** | `false` | nu |
| `CLIENT_REMINDERS_ENABLED` | Memento-urile **către clienți**, trimise automat | `true` | nu |

## Termene și asistent

| Variabilă | Rol | Implicit | Secret |
|---|---|---|:--:|
| `FILING_DEADLINE_DAY` | Ziua termenului implicit. Maximum 28: trebuie să existe și în februarie | `25` | nu |
| `ASSISTANT_PROVIDER` | `rules` \| `anthropic` | `rules` | nu |
| `ASSISTANT_API_KEY` | Cheia asistentului, **separată** de `AI_API_KEY` | `""` | **DA** |
| `ASSISTANT_MODEL` | Modelul | `claude-sonnet-5` | nu |
| `ASSISTANT_MAX_TOOL_ROUNDS` | Runde de unelte per întrebare | `3` | nu |

---

## Variabile care NU fac nimic — marcate ca atare

Rămân în `.env.example` **marcate `NEIMPLEMENTAT`**, deliberat: marcajul este mai
onest decât ștergerea — planul rămâne vizibil, iar nimeni nu pierde o după-amiază
adunând credențiale degeaba. Un test verifică marcajul în amândouă direcțiile.

| Variabilă | Situația |
|---|---|
| `RETENTION_ENABLED` | Are câmp și se afișează, dar **nu există niciun job de retenție**. Pe `true` nu șterge nimic. |
| `RETENTION_DOCUMENTS_YEARS` | Fără câmp în cod. Durata este o decizie a cabinetului, nu una pe care aplicația s-o aplice singură. |
| `RETENTION_AUDIT_LOG_YEARS` | Idem. |
| `RETENTION_TEMP_FILES_DAYS` | Idem. |
| `SENTRY_DSN` | Nu există export către Sentry. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Nu există export OTLP. |
| `WHATSAPP_PROVIDER` | Nu există integrare WhatsApp. |
| `WHATSAPP_TOKEN` | Idem. |
| `WHATSAPP_PHONE_NUMBER_ID` | Idem. |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | Idem. |
| `WHATSAPP_APP_SECRET` | Idem. |

## Variabile din frontend

Una singură, și **nu conține niciun secret**:

| Variabilă | Rol |
|---|---|
| `VITE_API_MODE` | `mock` (backend simulat în browser) sau `http` (server real). **`http` este obligatoriu în producție** — fără el, build-ul refuză să pornească și spune de ce. Implicitul ar fi fost demonstrația cu clienți inventați. |
| `VITE_PROXY_TARGET` | Adresa API-ului în development și în testele E2E. |

Orice variabilă `VITE_*` ajunge **în pachetul servit browserului**. Nu pune
niciodată un secret acolo.

---

## Ce s-a găsit și s-a reparat la această verificare

| Problemă | Ce era greșit | Ce s-a făcut |
|---|---|---|
| `PASSWORD_HASH_ALGORITHM` | Enumerată ca și cum ar configura ceva; niciun modul n-o citea. Algoritmul este fixat în cod | scoasă, cu explicația în locul ei |
| `OCR_FALLBACK_PROVIDER` | Nicio corespondență în cod, nemarcată | scoasă; lanțul de fallback **este** `OCR_PROVIDER=hybrid` |
| `AI_PROVIDER` | Fără validator, spre deosebire de toți ceilalți provideri. `openai` și `azure_openai` erau enumerate fără să existe în cod: aplicația pornea și le afișa ca provider activ | adăugat validator (`mock` \| `anthropic`); pornirea se oprește la o valoare neimplementată |
| `REFERENCE_PERIOD_STRATEGY` | Câmp real care decide luna contabilă, absent din `.env.example` | adăugată, cu explicația celor două valori |
| lipsea o verificare automată | Lista fusese curățată o dată de mână și se umpluse la loc | `test_env_example_contract.py` — patru verificări, toate confirmate prin mutație |
