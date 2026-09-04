# ADR-009 — e-Factura: preluare din SPV, trei fișiere pe un document

**Status:** Accepted · **Date:** 2026-09-04

## Context

De la 1 iulie 2024 factura electronică este obligatorie între firme din România.
Pentru un cabinet asta înseamnă că partea covârșitoare a facturilor clienților
**nu mai ajunge nicăieri la noi**: nu pe email, nu într-un dosar din OneDrive —
stă în Spațiul Privat Virtual al fiecărui client, la ANAF.

`domain/efactura.py` (M7) știa deja să citească o factură UBL 2.1 ajunsă la noi.
Ce lipsea era drumul până la ea.

O factură din SPV nu este un fișier, ci **trei**:

| Fișier | Provenit din | Se poate reface? |
|---|---|---|
| XML (UBL 2.1) | membru al arhivei | — este originalul fiscal |
| Arhiva ZIP cu sigiliul ANAF | `descarcare?id=` | **nu** — este dovada acceptării |
| PDF în forma oficială | convertorul public ANAF | da, oricând, din XML |

## Decizii

### 1. Cele trei fișiere stau pe **un singur** document

`document_versions.kind` primește `anaf_zip` și `anaf_pdf`, lângă `original` și
`archive`. `Document.storage_key` rămâne XML-ul.

Alternativa — trei documente — a fost respinsă pentru că un contabil vede *o
factură*, și pentru că fiecare mecanism care lucrează pe documente ar fi trebuit
atunci să știe care dintre cele trei „este" factura: detectarea duplicatelor
(același XML în două arhive), luna contabilă, arhivarea, checklistul perioadei.

### 2. Arhiva se stochează octet cu octet, **înaintea** PDF-ului

Arhiva poartă sigiliul electronic al ANAF, adică dovada acceptării, și este
singura dintre cele trei care nu se poate reface. Un ZIP recompus de noi ar avea
alt hash și ar înceta să mai fie o dovadă (§16).

Ordinea nu este cosmetică: când convertorul public al ANAF cade — și cade —
factura și dovada sunt deja salvate. Lipsa PDF-ului se scrie pe document, unde o
vede un om, nu doar în log, iar turul următor reia conversia.

Reluarea trebuie să existe tocmai pentru că **reprocesarea nu ajută**: ea cheamă
extracția, care citește XML-ul deja stocat, nu convertorul. Fără ea, o oră proastă
a ANAF ar fi lăsat facturile din ea fără forma tipăribilă definitiv.

### 3. Faza aceasta **doar citește**

`/upload` și `stareMesaj` există în API-ul ANAF și nu sunt implementate. A emite
un document fiscal în numele unui client este altă răspundere decât a-l descărca
pe cel deja emis, și nu se strecoară într-o funcție de preluare.

### 4. Împuternicirile sunt un tabel, nu o coloană pe client

`anaf_mandates` ține CUI-ul interogat separat de `clients.tax_id`, chiar dacă în
cazul obișnuit sunt același. Două motive:

- cheia unei cereri externe nu are voie să se schimbe tăcut sub noi: cineva
  corectează CUI-ul unui client în CRM, iar sincronizarea ar începe să
  interogheze altă firmă;
- rândul poartă **starea preluării** (`synced_through`, `last_error`), care nu are
  ce căuta pe client.

### 5. `synced_through` ține locul tokenului delta

ANAF nu dă tokenuri de continuare, ci ferestre de timp în milisecunde. Fereastra
se închide **abia după** ce facturile din ea au intrat — la fel ca `delta_token`
la Microsoft, din același motiv: închisă pe o eroare, ar pierde tăcut tot ce nu
s-a apucat să citească. Fereastra nouă se suprapune cinci minute peste cea
închisă; repetarea nu costă nimic, pentru că `id_descarcare` oprește orice al
doilea document.

### 6. Tokenul folosește aceeași `DRIVE_TOKEN_KEY`

Nu o cheie nouă. Este același tip de secret, cu același ciclu de viață și
aceeași consecință la scurgere; două chei ar fi însemnat două rotiri de ținut
minte, nu două granițe reale.

## Consecințe

**+** Clientul nu se ghicește. Interogarea se face pe CUI-ul lui, deci
apartenența vine din cerere — singura sursă din tot sistemul în care atribuirea
nu poate greși. La drive o dă dosarul, la email expeditorul; amândouă pot greși.

**+** Verificarea umană devine o citire, nu o completare: un document structurat
nu are valori „80% sigure".

**−** Autorizarea nu se poate automatiza, prin construcție. ANAF cere un
certificat digital calificat prezentat de browser; nu există `client_credentials`
și nu există cont de serviciu. O intervenție umană pe an, de la calculatorul cu
tokenul USB în port.

**−** Costul real nu este tehnic: **fiecare client** trebuie să depună
împuternicirea în SPV (formularul 150). Fără ea, ANAF nu întoarce eroare —
întoarce gol. De aceea refuzul apare pe rândul clientului, cu ce are de făcut.

**−** Drumul întreg către ANAF rămâne **NOT VERIFIED — EXTERNAL CREDENTIAL
REQUIRED**. Ce se verifică automat: despachetarea arhivei, idempotența,
atribuirea, fereastra de timp, împuternicirea lipsă, convertorul căzut, granița
organizației — prin protocol, cu un client fals; plus clientul HTTP însuși, cu un
transport fals.

## Trei ciudățenii ale API-ului, tratate explicit

Fiecare, netratată, produce un defect **tăcut**:

1. **„Nu există mesaje" vine ca `eroare`** în corpul răspunsului, nu ca listă
   goală. Tratat ca eroare, ar bloca fereastra de timp la nesfârșit.
2. **Cererile fără `User-Agent` primesc 403**, ceea ce seamănă leit cu o
   împuternicire lipsă și ar trimite pe cineva să caute la ANAF.
3. **Convertorul XML→PDF întoarce erorile de validare tot cu 200.** Un „PDF" care
   începe cu `{` ar ajunge în arhivă și s-ar descoperi abia când l-ar deschide
   cineva. Tot acolo: atributul `xsi:schemaLocation` încurcă uneori convertorul —
   se scoate **doar din corpul cererii**, niciodată din fișierul stocat.
