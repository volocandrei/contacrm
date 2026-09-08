# ADR-003 — Procesare asincronă cu Celery + Redis

**Status:** **SUPERSEDED** la M6 · **Date:** 2026-08-27 · **Revizuit:** 2026-09-08

> ## Ce s-a implementat, de fapt
>
> **Nu Celery + Redis.** Coada este `document_processing_jobs`, un **outbox
> tranzacțional în PostgreSQL**, revendicat cu `FOR UPDATE SKIP LOCKED`.
>
> **De ce s-a schimbat decizia.** Un broker separat ar fi adus încă un serviciu
> de rulat, monitorizat și salvat în copii de siguranță — ca să facă exact ce
> face deja baza de date pe care oricum o avem. La volumul unui cabinet
> contabil (sute de documente pe zi, nu pe secundă), Postgres **este** coada
> potrivită.
>
> Ce s-a câștigat: un singur loc unde stă starea, deci nicio situație în care
> jobul există în broker dar nu în bază, sau invers. Ce s-a pierdut: throughput
> pe care nu îl folosim.
>
> Motivul complet, cu alternativele cântărite, în capul lui `backend/app/worker.py`.
>
> **Ce a rămas valabil din decizia inițială:** `202 Accepted` + job id, retry cu
> limită, joburi idempotente, fără Kafka/RabbitMQ/Kubernetes.
>
> *Textul original se păstrează mai jos, ca înregistrare a ce s-a hotărât atunci.*

## Context
OCR/AI durează secunde–minute. Webhookurile (WhatsApp, Graph) trebuie confirmate rapid.

## Decizie
Celery + Redis. **Fără** Kafka/RabbitMQ/Kubernetes în MVP (§88.6–88.8).
`POST /documents/upload` întoarce `202 Accepted` + job id.

## Consecințe
+ Retry cu exponential backoff, joburi idempotente, o singură dependență de infrastructură.
− Redis devine componentă critică; necesită persistență și backup separat.
