# ADR-006 — RBAC granular + multi-tenancy de la început

**Status:** Accepted · **Date:** 2026-08-27

## Context
Roluri: SUPER_ADMIN, ADMIN, ACCOUNTANT, OPERATOR, REVIEWER, VIEWER.
Chiar dacă v1 e pentru o singură firmă, izolarea pe organizație e mult mai ieftină acum decât retroactiv.

## Decizie
Permisiuni granulare (`documents:approve`, `clients:write`…) grupate în roluri.
`organization_id` în toate entitățile relevante, filtrat la nivel de repository.
Teste negative obligatorii: user din org A nu vede date din org B (§49.13).

## Consecințe
+ Extensibil fără migrare dureroasă.
− Fiecare query trebuie să treacă prin repository-ul care aplică filtrul de tenant.
