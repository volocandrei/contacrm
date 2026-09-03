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

## Adăugire (03.09.2026) — cititorii locali și ruta după conținut

Abstracția a fost pusă la treabă cu trei implementări, toate **locale**:

| Provider | Ce citește |
|---|---|
| `mock` | date sintetice, deterministe pe hash. Producția refuză să pornească cu el |
| `pdf_text` | stratul de text al PDF-ului, prin reguli scrise pentru documente românești |
| `efactura` | factura electronică UBL 2.1 (e-Factura ANAF) |
| `local` | alege între `pdf_text` și `efactura` după conținutul fișierului |

Două lucruri pe care contextul de mai sus nu le anticipa:

**Încrederea nu este întotdeauna o probabilitate.** ADR-ul presupunea un model
care propune valori cu un scor. `efactura` citește un document *structurat*: nu
există „80% sigur că scrie 1190,00", ci doar prezență sau absență. Valorile ies
cu 1.0 și proveniența `OCR` — „citit de pe document" — pentru că exact asta s-a
întâmplat. `ExtractedValue` suporta deja distincția; nu a fost nevoie de nicio
schimbare de contract.

**Providerul nu se poate alege doar din configurare.** `OCR_PROVIDER` este o
singură valoare pentru tot procesul, dar un cabinet primește în aceeași zi
XML-uri, PDF-uri digitale și poze. `local` rutează după tipul de conținut
verificat pe octeți, iar `ExtractionResult.provider` poartă numele cititorului
care a răspuns — deci în audit și în interfață se vede cine a citit documentul,
nu un „local" generic.

Prompturile versionate rămân relevante abia la primul provider bazat pe model.
Până atunci `prompt_version` este `v1` peste tot, iar `raw_response` nu are ce să
conțină: nu există niciun răspuns de model de păstrat.
