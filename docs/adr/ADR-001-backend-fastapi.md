# ADR-001 — Backend: FastAPI + Pydantic v2 + SQLAlchemy 2

**Status:** Accepted · **Date:** 2026-08-27

## Context
Sistemul are nevoie de validare strictă a datelor (extracții AI, uploaduri),
OpenAPI generat automat și I/O asincron pentru integrări externe.

## Decizie
FastAPI + Pydantic v2 + SQLAlchemy 2.x (stil 2.0, typed) + Alembic.

## Consecințe
+ Validare la graniță gratuită; OpenAPI (§39) fără efort suplimentar.
+ Pydantic validează și răspunsul modelului AI (§75) — nu acceptăm JSON arbitrar.
− Necesită disciplină: endpointurile rămân subțiri, logica trăiește în services.
