# ADR-005 — Abstracție OCR/AI + prompturi versionate

**Status:** Accepted · **Date:** 2026-08-27

## Context
Nu știm încă providerul final; documentele sunt confidențiale (GDPR, §35).

## Decizie
`DocumentExtractionService` cu implementări interschimbabile
(Mock, Tesseract, Google Document AI, AWS Textract, Azure DI, LLM Vision).
**Implicit în development: `MockOCRProvider`** — niciun document nu părăsește mașina.
Prompturile stau în `backend/prompts/`, versionate; fiecare extracție salvează
`provider + model + prompt_version + raw_response + confidences`.
Răspunsul modelului este validat cu Pydantic; JSON nevalid ⇒ `PROCESSING_ERROR`, nu date parțiale.

## Consecințe
+ Putem investiga retroactiv de ce AI a clasificat un document într-un anumit fel.
+ Fallback: provider principal → retry → fallback → review manual (§78).
− Costuri/latency trebuie urmărite per provider (§77).
