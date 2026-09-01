# ARCHITECTURE — ContaCRM

CRM + ERP de document management pentru firme de contabilitate.

> Status: **M1 (frontend), M2 (schelet backend), M3 (autentificare) și M4 (CRM)
> implementate.** Documentele și procesarea sunt proiectate aici, dar încă
> neimplementate. Vezi [Roadmap](#roadmap--milestones).

---

## 1. Principiul central

```
AI extracts → System validates → Human confirms when necessary → System archives
```

Nicio informație extrasă automat nu este tratată ca adevăr. Fiecare câmp extras poartă
`value + source + confidence + istoric`. Nicio arhivare ireversibilă fără control uman
sub pragul de încredere configurat.

Ordinea de prioritate în decizii (§104):
`Security > Data integrity > Reliability > Maintainability > Simplicity > Performance > DX > Cost`

---

## 2. Stack

| Strat | Tehnologie | Note |
|---|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic | ✅ schelet — endpoint subțire → service → repository |
| DB | PostgreSQL 17 | `NUMERIC` pentru bani, `timestamptz` peste tot |
| Queue | Celery + Redis | fără Kafka/RabbitMQ în MVP (ADR-003) |
| Frontend | React 19, TypeScript strict, Vite 8, Tailwind v4, shadcn/ui | ✅ implementat |
| Dependențe Python | `uv` | Python-ul nu trebuie instalat în sistem |
| Auth | JWT access + refresh rotativ, Argon2id | ✅ RBAC granular, cookie-uri httpOnly |
| Storage | `StorageProvider` abstract | Local FS în MVP → S3/OneDrive/Azure ulterior |
| OCR/AI | `DocumentExtractionService` abstract | `MockOCRProvider` în dev (ADR-005) |

Versiuni reale instalate: React 19.2, Vite 8.2, TypeScript 6.0, Tailwind 4.3,
lucide-react 1.34 · Python 3.13.15, FastAPI 0.121, SQLAlchemy 2.0.52, Alembic 1.18,
Pydantic 2.13, psycopg 3.3, structlog 26.1.

---

## 3. Structura repository-ului

```
CONTACRM/
├── backend/                   # ✅ FastAPI + SQLAlchemy 2 + Alembic
│   ├── app/
│   │   ├── api/v1/            # ✅ routere subțiri, fără business logic + router.py
│   │   ├── core/              # ✅ config, logging, errors, db, middleware
│   │   ├── models/            # ✅ organization, user, audit, client/contact/note/tag, task
│   │   ├── schemas/           # ✅ ApiModel, Paginated, PageParams
│   │   ├── repositories/      # ✅ user, client, task — filtrarea pe organization_id
│   │   ├── services/          # ✅ auth.py, audit.py                        (M5+ restul)
│   │   ├── domain/            # ✅ permissions.py, enums.py
│   │   ├── integrations/      # ⏳ graph/, whatsapp/, ocr/, storage/     (M5, Faza 2)
│   │   └── workers/           # ⏳ taskuri Celery                            (M6)
│   ├── alembic/versions/      # ✅
│   ├── prompts/               # ⏳ prompturi AI versionate (ADR-005)         (M6)
│   ├── Dockerfile             # ✅ multi-stage, rulează ca utilizator neprivilegiat
│   └── tests/                 # ✅ contract / health / config
├── frontend/                  # ✅ Vite + React + TS strict + Tailwind + shadcn
│   └── src/
│       ├── api/               # client + endpoints + hooks + mock/ (backend simulat)
│       ├── components/ui/     # primitive shadcn + componente de bibliotecă
│       ├── features/          # auth/ clients/ documents/ periods/ tasks/ …
│       └── pages/ hooks/ lib/ types/
├── docker-compose.yml         # ✅ postgres + redis (+ migrate, backend pe profilul `api`)
└── docs/{adr,…}
```

Regulă: **niciun business logic în endpoint**.
`HTTP → validare (Pydantic) → service → repository/domain → response`.

---

## 4. Schema de bază de date (propunere)

Toate tabelele relevante poartă `organization_id` de la început (multi-tenancy, §33),
chiar dacă v1 rulează cu o singură organizație. Toate au `created_at`, `updated_at`;
entitățile de business au `deleted_at` (soft delete).

### Auth & tenancy
| Tabel | Câmpuri cheie |
|---|---|
| `organizations` | id, name, tax_id, settings jsonb |
| `users` | id, organization_id, email (uniq/org), password_hash (Argon2id), full_name, is_active, last_login_at |
| `roles` | id, code (SUPER_ADMIN…VIEWER), name |
| `permissions` | id, code (`documents:approve`), description |
| `role_permissions` | role_id, permission_id |
| `user_roles` | user_id, role_id |
| `refresh_tokens` | id, user_id, token_hash, expires_at, revoked_at, user_agent, ip |

### CRM
| Tabel | Câmpuri cheie |
|---|---|
| `clients` | id, organization_id, name, tax_id (CUI), reg_com, address, status (ACTIVE/INACTIVE/PROSPECT/SUSPENDED), assigned_accountant_id, metadata jsonb |
| `contacts` | id, organization_id, client_id, full_name, role, email, phone, whatsapp_number, is_active, is_primary |
| `client_tags` / `tags` | many-to-many |
| `client_notes` | id, client_id, author_id, body, created_at |
| `tasks` | id, organization_id, client_id?, title, description, assigned_to, priority, status (TODO/IN_PROGRESS/BLOCKED/DONE), due_date, completed_at |

### Contabilitate
| Tabel | Câmpuri cheie |
|---|---|
| `accounting_periods` | id, client_id, year, month, status (NOT_STARTED…FINALIZED), opened_at, closed_at, completed_at — **UNIQUE(client_id, year, month)** |
| `period_checklist_items` | id, period_id, document_type, expected_min_count, received_count, is_satisfied |

### Documente
| Tabel | Câmpuri cheie |
|---|---|
| `document_types` | id, code, label, is_active, validation_rules jsonb — extensibil, **fără hardcodare** (§6) |
| `document_intakes` | id, organization_id, source (EMAIL/WHATSAPP/UPLOAD/API), external_message_id, sender, recipient, subject, received_at, raw_payload jsonb, client_id?, status — **UNIQUE(source, external_message_id, attachment_id)** = idempotency (§56) |
| `documents` | vezi mai jos |
| `document_versions` | id, document_id, version_number, storage_path, sha256_hash, uploaded_by, uploaded_at, reason |
| `document_extractions` | id, document_id, provider, model, prompt_version, raw_response jsonb, parsed jsonb, field_confidences jsonb, duration_ms, token_usage, cost_estimate, created_at |
| `document_field_overrides` | id, document_id, field_name, old_value, new_value, changed_by, changed_at — istoricul corecțiilor umane |
| `document_processing_jobs` | id, document_id, job_type, status, attempt, last_error, started_at, finished_at, idempotency_key |

`documents` (câmpuri per §7): `id, organization_id, client_id, accounting_period_id,
document_type_id, status, source, intake_id, original_filename, stored_filename,
storage_path, mime_type, file_size, sha256_hash, received_at, document_date,
reference_month, series, document_number, supplier_name, supplier_tax_id,
customer_name, customer_tax_id, currency, subtotal NUMERIC(18,2), vat_amount NUMERIC(18,2),
total_amount NUMERIC(18,2), ocr_text, ocr_provider, ocr_confidence, ai_classification_confidence,
ai_extraction_confidence, is_duplicate, duplicate_of_id, review_required, reviewed_by,
reviewed_at, approved_by, approved_at, archived_at, created_at, updated_at, deleted_at`

> `document_date` ≠ `reference_month`. Nu se deduc una din alta automat fără regulă
> configurată. **TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION.**

### Comunicare & audit
| Tabel | Câmpuri cheie |
|---|---|
| `communication_messages` | id, client_id, direction, channel, external_id, subject, body, occurred_at, metadata jsonb |
| `notification_templates` | id, code, channel, subject_tpl, body_tpl, locale, is_active |
| `notifications` | id, template_id, client_id, channel, payload jsonb, status (PENDING/SENDING/SENT/FAILED/RETRYING), attempts, sent_at, error |
| `reminders` | id, client_id, rule_code, schedule, is_enabled, last_run_at, next_run_at |
| `legislative_notices` | id, title, content, valid_from, valid_until, active, priority, created_by, approved_by — **necesită aprobare umană înainte de trimitere (§28)** |
| `audit_logs` | id, organization_id, user_id, action, entity_type, entity_id, old_value jsonb, new_value jsonb, ip, user_agent, request_id, created_at |
| `system_settings` | key, value jsonb, updated_by — praguri de confidence, reguli de filename etc. (nehardcodate, §16) |

### Indexuri (§63)
`documents(client_id, reference_month)`, `documents(status)`, `documents(sha256_hash)`,
`documents(accounting_period_id)`, `documents(document_date)`,
`documents(supplier_tax_id, document_number)`, `documents(organization_id, deleted_at)`,
`audit_logs(entity_type, entity_id)`, `audit_logs(created_at)`,
`contacts(email)`, `contacts(whatsapp_number)`, `clients(tax_id)`,
UNIQUE parțial pe `document_intakes(source, external_message_id, attachment_id)`.

---

## 5. Pipeline de procesare

```
RECEIVED → VALIDATING → OCR_PROCESSING → CLASSIFYING → EXTRACTING
        → VALIDATING_DATA → READY_FOR_REVIEW → APPROVED → ARCHIVED
ramuri:  → ERROR | DUPLICATE | REJECTED | UNMATCHED (client neidentificat)
```

`POST /documents/upload` → salvează originalul, calculează SHA-256, întoarce **202 Accepted**
+ job id. OCR-ul nu rulează niciodată în request-ul HTTP.

Worker (idempotent, retry cu exponential backoff):
validate file → security/AV hook → hash → duplicate check → normalize → OCR →
classify → extract → validate fields → confidence → decide review → generate filename →
archive → update period → emit evenimente → notificări.

Praguri (configurabile în `system_settings`, valori inițiale propuse):
`≥0.90` automat · `0.70–0.89` review recomandat · `<0.70` review obligatoriu.

---

## 6. Riscuri majore identificate

| # | Risc | Impact | Mitigare |
|---|---|---|---|
| R1 | ~~Python și Docker nu erau instalate pe mașina de development~~ | — | **Rezolvat.** Docker Desktop 29.7 + Compose v5.4; `uv` aduce Python 3.13 fără instalare de sistem. `docker compose --profile api up` pornește postgres + redis + migrări + API |
| R2 | Documente financiare trimise către AI extern | GDPR / confidențialitate (§35) | `MockOCRProvider` implicit; provider extern doar opt-in explicit + DPA documentat |
| R3 | Fișiere încărcate = vector de atac | RCE / path traversal / stored XSS | validare MIME reală (magic bytes), nu extensie; filename generat intern; hook AV; storage în afara webroot; preview servit prin endpoint autorizat |
| R4 | Dublă procesare (retry email/webhook/worker) | Documente duplicate, notificări repetate | idempotency keys + UNIQUE pe (source, external_message_id, attachment_id) |
| R5 | Identificare greșită a clientului după număr WhatsApp | Documente în dosarul greșit — incident de confidențialitate | mapping explicit contact→client, status `UNMATCHED`, atribuire manuală obligatorie la ambiguitate |
| R6 | Reguli fiscale/contabile inventate de model | Risc legal | nimic hardcodat; tot configurabil; marcat `TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION` |
| R7 | Coliziuni / caractere ilegale la redenumire | Pierdere de documente | `frontend/src/lib/filename.ts` — sanitizare, diacritice, nume rezervate Windows, ambii separatori de cale, limite de lungime, sufix anti-coliziune, 19 teste. Backend-ul trebuie să implementeze **aceleași** reguli în `FilenameGeneratorService` |
| R8 | Ștergere/suprascriere ireversibilă | Pierdere de probe contabile | soft delete + `document_versions` + audit; retention explicit configurat |
| R9 | Indisponibilitate provider OCR extern | Blocaj în pipeline | retry → fallback provider → review manual, nu blocarea sistemului |
| R10 | Scurgere între organizații (multi-tenant) | Breșă gravă | `organization_id` filtrat la nivel de repository + teste de autorizare negative |

---

## 7. Decizii deschise (necesită input)

1. ~~Mediu backend local~~ — **decis: Docker Desktop + uv** (2026-08-27, implementat 2026-08-28).
2. **Provider OCR/AI real** pentru faza 2 și dacă politica firmei permite trimiterea
   documentelor în afara UE.
3. **Software-ul contabil** țintă pentru export (§58) — determină formatul.
4. **Regula de `reference_period`**: cum se decide luna contabilă când `document_date`
   cade în altă lună. Necesită validare de la un contabil.
5. **Tenant unic vs. multi-firmă** de la lansare (schema suportă ambele).

---

## Roadmap / Milestones

| M | Conținut | Stare |
|---|---|---|
| **M0** | Inspecție repo, plan, ADR-uri, structură | ✅ |
| **M1** | Frontend scaffold (Vite+TS strict+Tailwind v4+shadcn) + shell dashboard cu sidebar colapsabil | ✅ |
| **M1.5** | Ecrane complete pe backend simulat (`api/mock`), cu aceleași rute ca API-ul real | ✅ |
| **M2** | Backend skeleton: FastAPI, settings, Postgres, Alembic, health, error handling, logging structurat | ✅ |
| **M3** | Auth: users/roles/permissions, JWT + refresh rotativ, Argon2id, RBAC, audit log | ✅ |
| **M4** | CRM: clients, contacts, tags, note, tasks | ✅ |
| **M5** | Documente: încărcare, StorageProvider, SHA-256, duplicate, API, preview securizat, procesare, interfața de verificare, arhivare, întărire | ✅ |
| **M6** | Coadă persistentă (Celery+Redis), perioade + checklist, dashboard KPI, ecran audit, acțiuni în masă | perioade + dashboard ✅ |
| **M7** | Notificări (abstracție + email), rapoarte |  |
| **M8** | Teste E2E, Docker compose, CI |  |
| **Faza 2** | Microsoft Graph, WhatsApp, OCR/AI real, remindere, bulk, export ZIP |  |
| **Faza 3** | Integrare software contabil, rapoarte, detecție anomalii |  |

**MVP = M1–M8.**
