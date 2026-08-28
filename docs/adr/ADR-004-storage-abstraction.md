# ADR-004 — Abstracție de storage

**Status:** Accepted · **Date:** 2026-08-27

## Context
MVP-ul rulează pe filesystem local, dar clientul poate cere OneDrive/S3/Azure.

## Decizie
Interfața `StorageProvider` (`save`, `open_stream`, `delete`, `exists`, `move`).
Implementare MVP: `LocalFilesystemStorage`. Business logic nu atinge niciodată `os.path` direct.
Căile se construiesc exclusiv prin `StoragePathService`; numele de fișier vin exclusiv din
`FilenameGeneratorService` — niciodată din inputul utilizatorului (protecție path traversal, §36).

## Consecințe
+ Schimbarea providerului nu atinge business logic.
− Un strat în plus; acceptat pentru că integrarea externă e reală, nu ipotetică (§88.10).
