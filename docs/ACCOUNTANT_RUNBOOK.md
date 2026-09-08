# Ghidul contabilului

Ce face aplicația pentru tine, în termeni de cabinet. Fără cod, fără
configurare — pentru acelea sunt
[OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) și [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md).

Înainte de a te baza pe ea, parcurge
[ACCOUNTING_UAT_CHECKLIST.md](ACCOUNTING_UAT_CHECKLIST.md): acolo confirmi
valorile pe care aplicația le-a pus ca puncte de plecare și pe care **numai un
contabil le poate valida**.

---

## Ce este, într-o propoziție

Locul unde ajung, se citesc, se verifică și se arhivează documentele clienților
— și evidența a ce mai lipsește și ce trebuie depus.

**Nu este un program de contabilitate.** Nu ține conturi, nu face note contabile,
nu întocmește declarații. Stă înaintea programului de contabilitate: adună
documentele, le citește datele și ți le dă curate.

---

## Clienții

Fiecare client are o fișă cu tot ce ține de el: date de identificare, persoane de
contact, ce documente aștepți lunar de la el, ce declarații depune, onorariul, și
**cronologia** — tot ce a venit de la el, pe ce drum și când.

**Două lucruri se configurează la fiecare client nou**, și fără ele aplicația
tace despre el:

| Ce | Unde | Ce se strică fără |
|---|---|---|
| **Ce așteptăm lunar** | fișa clientului | nu apare niciodată în „Documente lipsă" |
| **Ce declarații depune** | fișa clientului | nu apare niciodată în „Termene" |

Tăcerea este deliberată: aplicația nu inventează ce ar trebui să depună cineva.
Dar înseamnă că un client neconfigurat pare în regulă când nu este.

Pentru clienți cu același profil există **șabloane**: configurezi o dată, aplici
la câți vrei.

---

## Documentele

### Cum ajung

Pe cinci drumuri, toate în același loc: încărcate de operator, trimise de client
printr-un link, luate de pe email, din OneDrive, sau descărcate din SPV.

Niciun drum nu este „mai scurt": un document de pe email trece prin exact aceiași
pași ca unul urcat de mână.

### Ce se citește din ele

Furnizorul, CUI-ul, seria, numărul, data, moneda, baza, TVA-ul, totalul — și, la
facturile electronice, **fiecare linie cu cota ei de TVA** și descrierea
produsului.

**Valorile se citesc, nu se calculează.** Aplicația nu face adunări și nu
completează un total lipsă. Un total pus de sistem ar arăta identic cu unul citit
de pe factură, iar la un control diferența contează.

Fiecare câmp arată **de unde vine**: citit din document, corectat de om, sau gol.

### Luna contabilă

Se derivă din **data de pe document**, nu din ziua în care a sosit. O factură din
31 august primită pe 3 septembrie este a lunii august.

Un document fără dată nu primește nicio lună — rămâne la verificare. O lună
greșită este mai rea decât una absentă: se aprobă fără să se uite nimeni.

### Verificarea

Niciun document nu se aprobă singur. Aprobarea automată este oprită, chiar și
peste pragul de încredere.

Nu se poate aproba un document căruia îi lipsesc câmpuri obligatorii sau
clientul. Butonul spune ce lipsește.

### Arhiva

După aprobare, documentul se copiază în arhivă, pe client și lună, cu un nume
format după o regulă fixă. **Originalul rămâne neatins.**

Un document arhivat nu se mai modifică. Corecțiile cer redeschidere, iar
istoricul păstrează versiunile.

---

## Corecțiile

Orice câmp se poate corecta în ecranul de verificare, până la arhivare. Fiecare
corectură se scrie în istoricul documentului: **ce s-a schimbat, din ce în ce,
cine și când.**

După arhivare, documentul se redeschide întâi. Redeschiderea rămâne și ea în
istoric.

Nimic nu se șterge fizic. Un document respins sau marcat duplicat rămâne, marcat.

---

## Perioadele

O lună are o stare: în lucru, documente complete, închisă. Ecranul arată, pe
client, cât mai lipsește.

**Închiderea o faci tu.** Aplicația nu închide singură o lună, oricât de completă
ar părea — este o afirmație contabilă, nu un calcul.

O lună închisă se poate redeschide.

---

## Termenele de depunere

**Contabilitate → Termene**: ce are cabinetul de depus, pentru cine, până când.
Restanțele separat, cu roșu.

Termenul se calculează din periodicitatea declarației și din decalajul
configurat. **Valorile din catalog sunt puncte de plecare uzuale, nu lege** —
se confirmă și se ajustează din *Administrare → Declarații*.

Bifezi ce s-a depus. Aplicația **nu depune** nimic la ANAF.

### Declarațiile fără termen

Situațiile financiare interimare (pentru dividende) nu se nasc din calendar: se
întocmesc când asociații hotărăsc, pe o perioadă aleasă atunci. Aplicația nu le
cere niciodată singură — le **înregistrează**, din fișa clientului, cu perioada
și nota ta.

> Trecute drept „anuale", ar fi apărut ca restanță la fiecare sfârșit de an, la
> toți clienții. O listă de restanțe false se închide o dată și nu se mai
> deschide, iar odată cu ea și restanțele adevărate.

---

## Banca

Se importă extrasul (CSV din internet banking — nu MT940, care se plătește
separat). Rândurile se citesc, iar sistemul **propune** ce factură ar putea fi
fiecare plată, cu motivele scrise.

**Legătura o faci tu.** Se acceptă plăți parțiale, mai multe facturi pe o plată,
și invers. O plată parțială lasă factura „în lucru", nu „achitată". Totul este
reversibil.

Soldurile se **citesc** din extras. Dacă banca declară un sold care nu se
potrivește cu suma tranzacțiilor citite, **asta este informația**: fișierul e
incomplet sau a fost citit greșit.

---

## Rapoarte și exporturi

| Ce | Ce conține |
|---|---|
| **Registrul** | un rând pe document, cu datele și sumele citite. Fișierul din care se lucrează mai departe |
| **Raportul** | numerele de pe ecran, agregate |
| **Declarațiile** | un rând pe depunere: ce, pentru cine, ce perioadă, cine a înregistrat |
| **Arhiva** | documentele lunii, pe client, plus registrul, într-un ZIP |

Toate se deschid corect în Excel-ul românesc: separator `;`, virgulă zecimală.

**Registrul conține și documentele rămase la verificare**, cu starea scrisă pe
rând — nu doar aprobatele. Un registru „curat" ar tăcea despre restul: cine
exportă o lună cu 12 documente în verificare ar primi 88 de rânduri dintr-o sută
fără să știe. Cele respinse și duplicatele nu intră.

---

## Istoricul

**Administrare → Audit** arată cine ce a făcut: aprobări, corecții, ștergeri,
închideri de lună, schimbări de configurare. Cu dată, oră și utilizator.

Nu se poate șterge din interfață.

---

## Ce trebuie să știi că NU face

| | |
|---|---|
| **Nu depune** declarații la ANAF | descarcă facturi din SPV, nu trimite nimic |
| **Nu calculează** sume, TVA, totaluri | le citește de pe document |
| **Nu interpretează** legislația | termenele din catalog sunt configurabile, iar răspunderea este a cabinetului |
| **Nu aprobă** singură | nici măcar documentele citite cu încredere mare |
| **Nu șterge** automat | nicio retenție automată; documentele rămân până le șterge un om |
| **Nu trimite** mesaje singură | decât dacă cineva a configurat asta explicit |
| **Nu se leagă** la bancă | extrasele se încarcă din fișier |
| **Nu exportă** în SAGA | formatul nu este public; există exportul CSV |

---

## Ce trebuie confirmat de tine, în scris

Aplicația a pus valori de plecare acolo unde a fost nevoie de o regulă contabilă,
și le-a marcat ca „de confirmat" — nu a inventat o interpretare.

Lista completă, cu loc de semnătură:
**[ACCOUNTING_UAT_CHECKLIST.md](ACCOUNTING_UAT_CHECKLIST.md)**

Cât timp nu este semnată, documentația tehnică nu are voie să pretindă că regulile
contabile sunt validate — și nu o face.
