# ADR-008 — Luna contabilă a unui document

**Status:** Accepted · **Date:** 2026-09-01

## Context

Un document are două date care nu coincid întotdeauna:

- `document_date` — data scrisă pe hârtie;
- `received_at` — momentul în care a ajuns la cabinet.

O factură din 30 august poate sosi pe 3 septembrie. Luna contabilă în care intră
decide în ce declarație ajunge, deci nu poate fi lăsată la voia întâmplării și nici
dedusă tăcut dintr-una dintre cele două.

Până acum câmpul exista în schemă cu un `TODO — BUSINESS RULE REQUIRES ACCOUNTING
VALIDATION` și nu era completat de nimeni. Asta însemna că documentele se arhivau
sub `fara-perioada`, iar perioadele contabile nu se puteau construi deloc.

## Decizie

**Implicit: luna documentului.** `reference_month` = anul și luna lui
`document_date`. Este cazul covârșitor și singurul care nu depinde de cât de repede
ajunge hârtia la contabil.

**Alternativa, configurabilă:** `REFERENCE_PERIOD_STRATEGY=received_at` derivă luna
din momentul primirii. Unele cabinete lucrează așa, mai ales pentru documentele care
sosesc sistematic târziu. Este o singură setare, nu o ramură prin cod.

**Fără dată, fără derivare.** Dacă `document_date` lipsește, `reference_month` rămâne
gol și documentul merge la verificare cu motivul scris. Nu se inventează o lună:
o valoare greșită aici este mai rea decât una absentă, pentru că absența se vede.

**Corectura umană câștigă întotdeauna.** Valoarea derivată se marchează ca provenind
de la sistem; un operator o poate schimba, iar reprocesarea nu o mai atinge — aceeași
regulă ca pentru orice alt câmp (§32).

**Perioadele închise nu se rescriu tăcut.** Când luna derivată aparține unei perioade
deja închise, documentul nu intră în ea de la sine: primește o problemă de validare
explicită, iar un om decide dacă redeschide luna sau mută documentul. Închiderea unei
luni este un act contabil; a-l anula automat ar goli-o de sens.

## Ce rămâne de confirmat de un contabil

Regula de mai sus este cea structural sigură, nu una fiscală. Trei lucruri au nevoie
de confirmare umană înainte de producție:

1. **Termenul până la care o factură de intrare mai poate intra în luna ei.** În
   practică se leagă de termenul declarației, dar pragul exact este o decizie a
   cabinetului. Astăzi nu există niciun termen automat: perioada rămâne deschisă până
   când o închide cineva.
2. **Dacă strategia este aceeași pentru toate tipurile de document.** Un extras de
   cont și o factură de intrare s-ar putea să nu se poarte la fel.
3. **Dacă strategia este per cabinet sau per client.** Astăzi este per cabinet.

Marcajul `TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION` rămâne în cod exact în
locurile de mai sus. Nu este muncă amânată, ci o întrebare deschisă către un om.

## Consecințe

+ Documentele au o lună contabilă, deci perioadele și checklistul devin posibile.
+ Regula trăiește într-un singur loc, testat, și se schimbă dintr-o setare.
− Cabinetele care lucrează pe „luna primirii" trebuie să schimbe setarea înainte de
  a încărca documente; schimbarea ulterioară nu rescrie retroactiv nimic.
− Documentele fără dată rămân blocate la verificare până când cineva completează
  data. Acceptat: alternativa este să ghicim.
