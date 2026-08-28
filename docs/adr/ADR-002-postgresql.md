# ADR-002 — PostgreSQL ca bază de date

**Status:** Accepted · **Date:** 2026-08-27

## Context
Date financiare, relații multiple, audit, căutare, JSON semi-structurat (extracții AI).

## Decizie
PostgreSQL 16. `NUMERIC(18,2)` pentru sume (niciodată float, §72),
`timestamptz` pentru toate momentele, `jsonb` pentru payload-uri de extracție și audit.

## Consecințe
+ Un singur motor pentru relațional + JSON + full-text search (MVP).
− Search avansat poate necesita ulterior un index dedicat; se amână până există nevoia reală.
