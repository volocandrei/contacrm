# ContaCRM — backend

FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16. Vezi [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

## Rulare locală

Dependențele se gestionează cu [`uv`](https://docs.astral.sh/uv/) — nu e nevoie de
Python instalat în sistem, `uv` îl aduce singur (`.python-version` → 3.13).

```bash
cd backend && uv sync
```

Infrastructura (necesită Docker Desktop pornit):

```bash
docker compose up -d          # postgres + redis
```

Migrări și pornire:

```bash
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

API-ul răspunde pe http://localhost:8000, documentația pe http://localhost:8000/docs
(ascunsă automat în producție).

## Totul în Docker

```bash
docker compose --profile api up -d --build
```

Migrările rulează într-un container separat; `backend` nu pornește până când acesta
nu s-a terminat cu succes.

## Comenzi

```bash
uv run pytest                       # teste
uv run ruff check . && uv run ruff format .
uv run mypy app                     # strict
uv run alembic revision --autogenerate -m "descriere"
uv run alembic upgrade head
uv run alembic downgrade -1
```

`alembic upgrade head --sql` randează SQL-ul fără să atingă baza — util pentru
review înainte de a rula ceva pe date reale.

## Health

| Rută | Întrebarea la care răspunde |
|---|---|
| `/health/live` | procesul răspunde? (nu atinge nicio dependență) |
| `/health/ready` | poate servi trafic? `503` + `degraded` dacă baza nu răspunde |
| `/health/info` | ce versiune și ce configurare rulează (fără secrete) |

Sunt montate și sub `/api/v1/...`, și la rădăcină — orchestratorul nu trebuie să
cunoască versiunea API.

## Convenții

- **Niciun business logic în endpoint**: `HTTP → Pydantic → service → repository → response`.
- **Contractul JSON este camelCase** (`ApiModel.alias_generator`), pentru că
  frontend-ul îl consumă direct. Python-ul rămâne snake_case.
- **Codurile de eroare** din `app/core/errors.py` sunt oglinda listei
  `API_ERROR_CODES` din `frontend/src/api/types.ts`. `tests/test_contract.py`
  citește fișierul frontend-ului și cade dacă cele două se despart.
- **Bani**: `NUMERIC(18,2)` în DB, `Decimal` în Python, `string` prin API. Niciodată `float`.
- **Timp**: `timestamptz` peste tot, niciodată datetime naiv.
- **Secrete**: doar prin variabile de mediu. `Settings` refuză `*` în CORS și refuză
  să pornească în producție cu `SECRET_KEY` implicit.
- Nicio regulă fiscală hardcodată. Unde e neclar:
  `TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION`.

## Structură

```
backend/
├── app/
│   ├── api/v1/        # routere subțiri + agregatorul din router.py
│   ├── core/          # config, logging, errors, db, middleware
│   ├── models/        # SQLAlchemy — base.py ține mixin-urile comune
│   ├── schemas/       # Pydantic (ApiModel, Paginated, PageParams)
│   ├── repositories/  # acces la date  ─┐
│   ├── services/      # business logic  ├─ se populează de la M3 încolo
│   └── domain/        # enums, reguli  ─┘
├── alembic/versions/  # migrări
└── tests/
```
