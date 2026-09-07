# e-Factura

Ce face aplicația cu facturile electronice: cum le citește, cum le leagă de
exemplarul clasic, și ce rămâne neverificat până la primele credențiale reale.

---

## 1. Citirea unei facturi electronice

Factura electronică este un **XML UBL 2.1** (RO_CIUS). Spre deosebire de un PDF,
fiecare valoare stă într-un element cu nume: nu se citește un total dintr-un text,
se citește câmpul `TaxInclusiveAmount`. Nu există „80% sigur".

Se citesc: numărul și seria, data emiterii, furnizorul și cumpărătorul cu CUI-urile
lor, moneda, baza, TVA-ul, totalul — și **liniile**, cu descrierea, cantitatea,
prețul unitar, cota de TVA și categoria ei.

**Securitate.** XML-ul vine din afară. Parsarea se face prin `defusedxml`, care
refuză DTD-urile și entitățile — adică exact vectorii „billion laughs" și XXE. O
factură reală nu are DOCTYPE, deci refuzul nu costă niciun caz legitim.

**Nu se completează nimic.** Un câmp absent din XML rămâne absent și în aplicație.
Un `None` cinstit costă zece secunde de completat; o valoare plauzibilă trece pe
lângă operator.

---

## 2. Perechea XML ↔ PDF

**Problema.** Aceeași factură ajunge de două ori și pe două drumuri: XML-ul din
SPV, descărcat automat, și PDF-ul trimis de furnizor pe email sau adus de client.
Sunt **același document**, nu două — dar niciunul nu se aruncă: XML-ul este
originalul fiscal, cu valori exacte; PDF-ul este ce se poate privi și tipări.

Fără legătură, cabinetul are două rânduri în registru pentru o singură factură, iar
contabilul le potrivește cu ochiul, în fiecare lună.

### Cheia

**Identitatea legală a facturii**: codul fiscal al furnizorului, seria și numărul.
Tripletul identifică o factură în mod unic — de aceea el, și nu suma. Dacă
furnizorul, seria și numărul coincid, o sumă diferită înseamnă că una dintre cele
două a fost citită greșit, iar **asta** trebuie arătat, nu ascuns.

### Stările

| Stare | Ce înseamnă | Ce se întâmplă |
|---|---|---|
| `MATCHED` | identitate exactă, un singur candidat | **se leagă singur** |
| `PROBABLE` | se potrivesc numărul și seria, lipsește CUI-ul sau suma | se propune |
| `MULTIPLE_CANDIDATES` | două sau mai multe la fel de bune | se arată toate |
| `CONFLICT` | identitate identică, **sume diferite** | nu se leagă, se semnalează |
| `MISSING` | nu există pereche | nimic — este cazul obișnuit |

**Se leagă singur numai pe identitatea legală completă.** Nu este o ghicire: este
aceeași factură după cheia care o definește legal. Orice lipsă coboară la
„probabil", iar acolo apasă un om.

**Conflictul câștigă asupra oricărei potriviri reușite.** Dacă există un exemplar
cu aceeași identitate și altă sumă, aceea este informația — și stă sus pe ecran, în
roșu, nu îngropată sub o legătură care pare în regulă.

### Legătura

Este **reciprocă**: fiecare exemplar știe unde este celălalt. Poartă **motivele**
în cuvinte („același număr, aceeași serie, CUI furnizor identic, aceeași sumă") și
spune dacă a făcut-o sistemul sau un om. Se poate rupe dintr-un buton.

Două exemplare de **același fel** nu se pot lega: două XML-uri cu aceeași
identitate sunt un duplicat, nu o pereche, iar duplicatele au modulul lor.

---

## 3. Preluarea din SPV

Sincronizarea cu SPV-ul ANAF există în cod: conexiune OAuth, împuterniciri per
client, descărcarea mesajelor, dezarhivarea, sigiliul.

**Două condiții care nu se rezolvă din configurare:**

1. **Certificatul digital calificat**, înrolat în SPV, prezentat de browser la
   autorizare. Se face o dată pe an, de la calculatorul cu tokenul USB în port.
2. **Împuternicirea fiecărui client** în SPV (formular 150), pentru certificatul
   cabinetului. Fără ea, ANAF nu întoarce eroare — întoarce **gol**.

## Stare: `NEVERIFICAT — NECESITĂ CREDENȚIALE EXTERNE`

Ce s-a verificat: parsarea XML-ului pe fișiere reale ca formă, dezarhivarea,
tratarea erorilor, reluarea, izolarea între cabinete, și comportarea turului
periodic când un cabinet cade.

Ce **nu** s-a putut verifica: că serverul ANAF răspunde așa cum credem. Nicio
afirmație din documentație nu pretinde altceva.

---

## 4. Ce nu face, deliberat

- **Nu trimite facturi.** Emiterea și transmiterea în SPV sunt altă discuție, cu
  alte implicații; aplicația citește.
- **Nu verifică sigiliul ANAF.** Arhiva îl conține și se păstrează, dar validarea
  criptografică nu este implementată.
- **Nu convertește XML-ul în PDF.** Ce se poate privi este rezumatul, iar PDF-ul
  oficial vine din arhiva ANAF când există.
