# Reconciliere bancară

Ce factură a plătit fiecare rând din extras — și de ce sistemul crede asta.

---

## De ce există

Reconcilierea este una dintre cele mai lungi ore ale lunii într-un cabinet:
extrasul într-o parte, facturile în alta, potrivite cu ochiul. Trei sute de
rânduri pe lună, per client.

Este și una dintre cele mai ușor de greșit. O plată pusă pe factura vecină mută
bani între conturi analitice, iar greșeala iese la închiderea anului — dacă iese.

---

## Modelul

Trei tabele, și al treilea este cel care contează.

| Tabel | Ce ține |
|---|---|
| `bank_statements` | extrasul: banca, IBAN-ul, perioada, soldurile declarate |
| `bank_transactions` | rândul: dată, sumă **cu semn**, descriere, contrapartidă, referință |
| `transaction_matches` | **legătura**: ce tranzacție, ce document, și **cât** |

### De ce legătura are tabel propriu

Realitatea unui cabinet nu este unu-la-unu:

- o plată închide **trei facturi** deodată;
- o factură se plătește în **două tranșe**;
- se plătește **mai mult** (avans) sau **mai puțin** (rest de plată);
- din sumă se scade un comision.

O coloană `document_id` pe tranzacție ar fi acoperit un caz din cinci. Restul s-ar
fi rezolvat prin note scrise de mână, adică nicăieri.

**Suma stă pe legătură**: cât din plata asta a mers pe factura aceea. Fără ea,
„plătit parțial" nu se poate scrie deloc.

---

## Stările unui rând

| Stare | Ce înseamnă |
|---|---|
| `UNMATCHED` | nimic nu s-a potrivit, sau nimeni nu s-a uitat |
| `SUGGESTED` | sistemul a găsit un candidat — **nu** o potrivire |
| `MATCHED` | acoperit integral, confirmat de un om |
| `NEEDS_REVIEW` | acoperit parțial: nici gata, nici de la capăt |
| `IGNORED` | lămurit: comision, dobândă, transfer propriu |

`IGNORED` există pentru un motiv practic: un comision bancar de trei lei nu este
„nepotrivit". Dacă cele două arată la fel, lista de nepotrivite nu se golește
niciodată — iar o listă care nu se golește nu se mai deschide.

**Starea se recalculează din sume**, nu se scrie. O stare setată de mână s-ar fi
desincronizat de legături la a treia operațiune, iar lista de lucru ar fi mințit în
amândouă direcțiile.

---

## Cum se propune o potrivire

Regulile stau în `backend/app/domain/bank_matching.py`, care este **pur** — fără
bază de date, fără sesiune. Se pot citi și testa fără să deschizi un ORM.

Semnalele, în ordinea în care contează:

1. **Numărul facturii în referința plății.** Cel mai tare care există: cine
   plătește îl scrie tocmai ca să se știe ce plătește. Se caută pe **cuvânt
   întreg** — `7001` nu are voie să se potrivească în `270015`.
2. **Suma exactă.** Egalitate la bănuț.
3. **CUI-ul contrapartidei.** Neambiguu, dar rar în descrierea unui extras.
4. **Numele partenerului**, pe formă normalizată: fără diacritice, fără `SRL`,
   fără puncte. „Șerbănescu Distribuție S.R.L." și „SERBANESCU DISTRIBUTIE SRL"
   sunt același furnizor.
5. **Apropierea de dată.** Cel mai slab, și **niciodată singur**.

### Regula care ține totul

**Un singur semnal slab nu produce nicio propunere.** Data apropiată plus o sumă
rotundă este exact tiparul care leagă factura greșită: două abonamente lunare de
aceeași valoare arată identic. Se cere fie numărul facturii, fie două semnale
independente.

Sub pragul de propunere, **tăcerea este răspunsul corect**. Un sistem care propune
mult și greșit este mai rău decât unul care tace: contabilul verifică primele zece
propuneri, găsește trei greșite, și nu mai deschide ecranul.

### Direcția nu se discută

O plată (bani ieșiți) poate închide numai o factură de la furnizor. O încasare,
numai una emisă. Fără regula asta, o plată și o încasare de aceeași valoare — lucru
banal între firme care își facturează reciproc — s-ar lega una de alta.

---

## De ce fiecare propunere spune de ce

> Factura 7001 · Terț Furnizor SRL · **94%**
> · numărul facturii apare în plată
> · sumă exactă
> · la 6 zile de factură

Fără explicație, contabilul fie verifică tot de la zero — și atunci automatizarea
n-a economisit nimic — fie acceptă fără să verifice, ceea ce este mai rău decât
munca de mână.

**Nimic nu se leagă singur.** Ruta de propuneri citește; legătura se scrie doar
dacă apasă cineva, iar butonul are suma scrisă pe el înainte de apăsare.

---

## Ce nu se poate face

Verificările stau în serviciu, nu în interfață — un al doilea ecran, o comandă din
CLI sau un import ar ocoli-o pe cea din browser:

- nu se poate aloca mai mult decât a rămas din tranzacție;
- nu se poate aloca mai mult decât restul de plată al facturii;
- o tranzacție cu legături nu se poate marca „lămurită";
- a doua alocare pe aceeași factură **crește legătura**, nu adaugă un rând —
  altfel „cât s-a plătit" ar depinde de câte ori a apăsat cineva.

Totul este reversibil dintr-un buton. Fără asta, o apăsare greșită ar cere o
intervenție în bază, iar contabilul care știe asta nu mai apasă deloc.

---

## Importul extrasului

**Ce are cabinetul în mână** nu este MT940 și nu este CAMT.053 — acelea se plătesc
separat la bancă. Este exportul din internet banking: un CSV cu antete în
românește, diferite de la o bancă la alta.

De aceea coloanele se recunosc **după nume**, cu sinonime. Lista din
`app/services/bank_import.py` crește; poziția fixă nu ar fi funcționat nici pentru
a doua bancă.

### Două capcane, niciuna vizibilă

**Separatorul zecimal.** `1.234,56` și `1,234.56` sunt aceeași sumă scrisă de două
programe. Ghicit greșit, din 1.234 de lei rămâne un leu și douăzeci și trei de
bani — iar extrasul se importă fără nicio eroare, doar cu alt total. Regula:
ultimul separator este cel zecimal, iar un separator singur urmat de trei cifre
este separator de mii.

**Coloana de dată.** Antetele se potrivesc **exact**, nu pe „conține": altfel
„Data" ar înghiți „Data valutei", iar toate tranzacțiile ar ajunge cu o zi alături.
Uniform, deci invizibil în total, și suficient ca operațiunile de la sfârșit de
lună să cadă în luna următoare.

### Restul regulilor

- **Se citește de două ori, se scrie o dată.** Previzualizarea nu atinge nimic.
- **Un rând stricat nu oprește fișierul.** 298 din 300 intră; cele două sunt numite.
- **Același extras de două ori nu dublează nimic.** Cheia este contul plus perioada
  plus numărul; în interior, identificatorul băncii sau data + suma + descrierea.
- **Soldurile se citesc, nu se calculează.** Dacă soldul declarat nu se potrivește
  cu suma tranzacțiilor, **asta este informația**: fișierul este incomplet. Un sold
  calculat de noi ar fi ascuns exact ce poate dovedi extrasul.

---

## Ce nu există încă

- **Preluare automată din bancă** (PSD2 / open banking). Cere contract cu un
  agregator și consimțământul fiecărui client. Extrasul se încarcă manual.
- **Recalibrarea pragurilor pe date reale.** Ponderile de acum sunt alese ca
  **ordine**, nu măsurate — nu există încă date reale. După o lună de folosire, ele
  se pot recalibra pe ce a acceptat și ce a respins omul.
- **Reconciliere pe mai multe valute.** Se importă și se afișează moneda, dar nu
  există conversie: o plată în euro pe o factură în lei nu se poate lega.
