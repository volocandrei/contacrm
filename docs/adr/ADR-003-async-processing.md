# ADR-003 — Procesare asincronă cu Celery + Redis

**Status:** Accepted · **Date:** 2026-08-27

## Context
OCR/AI durează secunde–minute. Webhookurile (WhatsApp, Graph) trebuie confirmate rapid.

## Decizie
Celery + Redis. **Fără** Kafka/RabbitMQ/Kubernetes în MVP (§88.6–88.8).
`POST /documents/upload` întoarce `202 Accepted` + job id.

## Consecințe
+ Retry cu exponential backoff, joburi idempotente, o singură dependență de infrastructură.
− Redis devine componentă critică; necesită persistență și backup separat.
