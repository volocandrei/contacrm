# Predarea datelor către Saga

Programul de contabilitate al cabinetului este **Saga** (răspuns primit pe
5 septembrie 2026: „majoritatea folosesc Saga").

Documentul acesta există ca să separe ce se știe de ce se presupune. Un export
scris din presupuneri ori nu se importă deloc — și atunci se pierde o zi — ori se
importă strâmb, și atunci nu observă nimeni până la o verificare.

---

## Ce există deja și nu depinde de Saga

**`GET /reports/register.csv`** — registrul lunii, un rând pe document, cu data,
seria, numărul, furnizorul, CUI-ul, baza, TVA-ul și totalul citite din fiecare.
Se deschide în Excel cu setările românești (separator `;`, BOM, virgulă la
zecimale) și se poate prelucra manual oricum.

Este exportul universal. Rămâne, indiferent ce se adaugă peste el.

---

## Ce nu se știe încă

**Forma exactă pe care o așteaptă importul din Saga.** Nu este ceva ce se poate
deduce corect din documentație generală sau din memorie: contează numele
coloanelor, ordinea lor, ce identifică un partener (CUI cu sau fără `RO`), cum se
codifică cota de TVA, ce se face cu documentele fără furnizor identificat și dacă
importul cere un fișier pe client sau unul pe cabinet.

*NEVERIFICAT — NECESITĂ UN EXEMPLU REAL DE LA CABINET.*

### Ce anume ar debloca lucrul

Oricare dintre acestea, în ordinea utilității:

1. **Un fișier exemplu** pe care Saga îl importă acum cu succes — chiar și cu
   date inventate. Din el se citește forma exactă, fără presupuneri.
2. **Numele meniului** din Saga prin care se face importul, plus o captură a
   ecranului de import. Din el se află ce format se așteaptă.
3. **Cum ajung azi datele în Saga** — tastate de mână, importate din e-Factura,
   sau altfel. Determină ce merită automatizat întâi.

Până atunci nu se scrie niciun „export Saga". Un buton care produce un fișier
respins de Saga este mai rău decât lipsa butonului: prima dată se pierde o oră
căutând greșeala în date.

---

## Ce se poate face fără spec, dacă se dovedește util

**Fișierele e-Factura, adunate pe lună.** Aplicația descarcă deja din SPV-ul ANAF
XML-ul fiecărei facturi electronice, cu toate cele trei fișiere (M11). Facturile
electronice se importă în programele de contabilitate direct din XML, fără să
treacă printr-un format proprietar.

**Nu s-a construit**, pentru că nu se știe încă dacă ajută: multe cabinete conectează
Saga direct la SPV și primesc XML-urile pe cont propriu. Dacă acesta este cazul
aici, funcția ar duplica ceva ce merge deja — de aceea întrebarea stă înaintea
codului.
