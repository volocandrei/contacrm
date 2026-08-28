# ADR-007 — Frontend: Vite + React 19 + TS strict + Tailwind v4 + shadcn/ui

**Status:** Accepted · **Date:** 2026-08-27

## Context
Aplicație internă, densă în informație, orientată desktop. Operatorul procesează sute de
documente pe zi (§67). Nu e nevoie de SSR/SEO.

## Decizie
SPA cu Vite (fără Next.js — nu avem nevoie de server rendering).
Tailwind v4 (config CSS-first, `@theme inline`), shadcn/ui în `src/components/ui/`,
alias `@/*`, TypeScript `strict: true`.
Dark mode pe clasă, nu pe `prefers-color-scheme`: `@custom-variant dark (&:is(.dark *))`.

## Consecințe
+ Build ~0.5s, componente shadcn instalabile prin CLI în locul corect (`components.json`).
− Directiva `"use client"` din componentele copiate din registry se elimină (produce warning la bundling, nu are sens fără RSC).
