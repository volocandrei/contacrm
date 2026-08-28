# ADR-002 — PostgreSQL ca bază de date

**Status:** Accepted · **Date:** 2026-08-27 · **Revizuit:** 2026-08-28 (16 → 17)

## Context
Date financiare, relații multiple, audit, căutare, JSON semi-structurat (extracții AI).

## Decizie
PostgreSQL 17. `NUMERIC(18,2)` pentru sume (niciodată float, §72),
`timestamptz` pentru toate momentele, `jsonb` pentru payload-uri de extracție și audit.

Versiunea inițială a fost 16. Am trecut la 17 pe 2026-08-28 pentru că mașina de
development rulează 17 (instalat nativ, vezi mai jos), iar a testa pe o versiune
și a rula pe alta introduce o clasă de erori care apar abia în producție. Niciunul
dintre argumentele de mai sus nu depinde de versiune.

## Consecințe
+ Un singur motor pentru relațional + JSON + full-text search (MVP).
+ Aceeași versiune local și în container — testele rulează pe ce rulează în producție.
− Search avansat poate necesita ulterior un index dedicat; se amână până există nevoia reală.

## Notă de mediu
Docker Desktop nu ridică engine-ul pe Windows ARM64 (clientul primește 500 de la
server chiar și la `docker version`). Pe mașina de development rulează un
PostgreSQL 17 nativ, instalat cu `winget install PostgreSQL.PostgreSQL.17`.
`docker compose` rămâne calea suportată acolo unde Docker funcționează.
