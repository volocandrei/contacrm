# Verificarea contabilului, înainte de pornire

Lista aceasta este pentru **un contabil autorizat**, nu pentru un programator.
Nu cere cunoștințe tehnice și nu se parcurge citind cod.

## De ce există

Aplicația știe să numere, să potrivească și să arhiveze. **Nu știe legea.** Peste
tot unde a fost nevoie de o regulă contabilă, aplicația a pus o valoare de
plecare uzuală și a marcat-o în cod ca „de confirmat" — nu a inventat o
interpretare și nu a pretins că ea este cea corectă.

Lista de mai jos strânge **exact** acele locuri. Sunt puține, dar fiecare are
consecințe: un termen greșit înseamnă o amendă la client, plătită de cabinet.

**Ce se separă aici, deliberat:**

| | Cine o face | Ce înseamnă |
|---|---|---|
| **Verificare tehnică** | dezvoltator | funcționează mecanismul: se salvează, se calculează, se arhivează |
| **Aprobare contabilă** | contabil autorizat | valoarea este **corectă după lege** și după cum lucrează cabinetul |

Verificarea tehnică este făcută și verificată prin teste. **Aprobarea contabilă
nu este dată** și nu poate fi dată de nimeni din echipa tehnică.

---

## Cum se parcurge

Ai nevoie de: un cont în aplicație, o oră, și un client real cu documente dintr-o
lună închisă deja, ca să poți compara cu ce ai făcut manual.

Pentru fiecare punct: **bifează** dacă e corect, sau **scrie ce trebuie
schimbat**. Toate valorile se pot ajusta din aplicație, fără programator.

---

# A. Catalogul de declarații

**Unde:** *Administrare → Declarații*

Aplicația vine cu douăsprezece declarații și, pentru fiecare, cu o periodicitate,
un decalaj în luni și o zi. **Toate sunt puncte de plecare uzuale.** Termenul se
calculează ca „sfârșitul perioadei + N luni, ziua Z".

| # | Declarație | Aplicația propune | Corect? | Dacă nu, ce |
|---|---|---|---|---|
| A1 | D300 — decont TVA | lunar, luna următoare, ziua 25 | [ ] | ______ |
| A2 | D300 — decont TVA trimestrial | trimestrial, luna următoare, ziua 25 | [ ] | ______ |
| A3 | D301 — decont special TVA | lunar, luna următoare, ziua 25 | [ ] | ______ |
| A4 | D390 — recapitulativă (VIES) | lunar, luna următoare, ziua 25 | [ ] | ______ |
| A5 | D394 — informativă | lunar, luna următoare, ziua 30 | [ ] | ______ |
| A6 | D112 — salarii și contribuții | lunar, luna următoare, ziua 25 | [ ] | ______ |
| A7 | D100 — obligații de plată | trimestrial, luna următoare, ziua 25 | [ ] | ______ |
| A8 | D101 — impozit pe profit | anual, a 3-a lună, ziua 25 | [ ] | ______ |
| A9 | D205 — informativă impozit reținut | anual, a 2-a lună, ziua 28 | [ ] | ______ |
| A10 | D406 — SAF-T | lunar, luna următoare, ziua 30 | [ ] | ______ |
| A11 | Situații financiare anuale | anual, a 5-a lună, ziua 30 | [ ] | ______ |
| A12 | Situații financiare interimare | **fără termen de calendar** | [ ] | ______ |

**A13.** Lipsește vreo declarație pe care o depune cabinetul? [ ] Nu / Care: ______

**A14.** Situațiile financiare interimare (dividende) nu au termen: aplicația nu
le cere niciodată singură, ci doar le înregistrează când cineva spune că s-au
întocmit, pe perioada aleasă atunci. **Este corect așa?** [ ] Da / ______

> **De ce contează A14:** dacă ar fi fost trecute drept „anuale", ar fi apărut ca
> restanță la fiecare sfârșit de an, la **toți** clienții — inclusiv la cei care
> nu au distribuit dividende. O listă de restanțe false se închide o dată și nu
> se mai deschide, iar odată cu ea și restanțele adevărate.

**A15.** Ziua se retează la ultima zi a lunii dacă luna e mai scurtă (ziua 30 în
februarie devine 28/29). **Corect?** [ ] Da / ______

**A16.** Aplicația **nu depune** nimic la ANAF și nu calculează sumele din
declarații. Ține evidența a ce trebuie depus, când, și de către cine.
**Confirmat că asta se aștepta?** [ ] Da

---

# B. Luna contabilă a unui document

**Unde:** orice document, câmpul „Luna"

Aceasta este **cea mai consecventă alegere din aplicație**. Din ea rezultă în ce
lună intră documentul, deci ce raportează fiecare declarație.

**B1.** Aplicația derivă luna din **data de pe document**, nu din ziua în care a
sosit. O factură din 31 august primită pe 3 septembrie este a lunii **august**.

**Corect pentru cabinet?** [ ] Da / [ ] Nu, trebuie ziua sosirii

**B2.** Un document **fără dată** nu primește nicio lună — rămâne la verificare.
Aplicația nu ghicește. **Corect?** [ ] Da / ______

> O lună greșită este mai rea decât una absentă: se aprobă fără să se uite nimeni.

**B3.** Regula este **una singură pentru tot cabinetul**. Trebuie să difere pe
tip de document (un extras de cont față de o factură) sau pe client?
[ ] Nu, una singură e bine / [ ] Da, pentru: ______

**B4.** Verifică pe cinci documente reale dintr-o lună închisă: luna atribuită de
aplicație este cea în care le-ai înregistrat tu? [ ] Da / ______

---

# C. Tipurile de documente și câmpurile obligatorii

**Unde:** *Administrare → Tipuri de documente*

Fiecare tip are o listă de câmpuri fără de care documentul **nu poate fi
aprobat**.

**C1.** Lista tipurilor acoperă ce primește cabinetul? [ ] Da / Lipsește: ______

**C2.** Pentru fiecare tip folosit des, câmpurile obligatorii sunt cele potrivite?

| Tip | Câmpuri cerute | Corect? |
|---|---|---|
| Factură intrare | ______ | [ ] |
| Factură ieșire | ______ | [ ] |
| Bon fiscal | ______ | [ ] |
| Extras de cont | ______ | [ ] |
| Altele | ______ | [ ] |

**C3.** Un câmp obligatoriu lipsă blochează aprobarea. Este prea strict undeva
(blochează munca) sau prea permisiv (lasă să treacă documente incomplete)?
______

---

# D. Direcția facturii și clientul

**D1.** Aplicația stabilește dacă o factură este de **intrare** sau de **ieșire**
comparând CUI-ul de pe document cu CUI-ul clientului — nu ghicește din text.
**Corect?** [ ] Da / ______

**D2.** Ia zece facturi, cinci de intrare și cinci de ieșire. Toate au fost puse
în direcția corectă? [ ] Da / Greșite: ______

**D3.** Când clientul nu poate fi identificat, documentul ajunge în
„Neatribuite", nu într-un client ales la întâmplare. **Corect?** [ ] Da

---

# E. TVA și sumele

**E1.** Aplicația **nu calculează** TVA, totaluri sau conversii de monedă. Scrie
valorile **citite de pe document**, așa cum sunt.

**Confirmat că asta se aștepta?** [ ] Da

> Un total pus de sistem ar arăta identic cu unul citit de pe factură, iar la un
> control diferența contează.

**E2.** O factură poate avea **cote diferite de TVA pe linii diferite**, iar
fiecare linie își poartă cota ei. Verifică pe o factură cu cote mixte:
[ ] Corect / ______

**E3.** Sumele se păstrează exact, cu două zecimale, fără rotunjiri ascunse. Ia o
factură și compară banii cu originalul: [ ] Identic / ______

**E4.** În exportul CSV, sumele apar cu **virgulă** zecimală, ca Excel-ul
românesc să le adune. Deschide un export și trage un total pe coloană:
[ ] Se adună / ______

---

# F. Perioada contabilă (luna de lucru)

**Unde:** *Contabilitate → Perioade*

**F1.** O lună se închide manual, de un om. Aplicația nu o închide singură.
**Corect?** [ ] Da / ______

**F2.** O lună închisă se poate redeschide, iar redeschiderea rămâne în istoric.
**Corect?** [ ] Da

**F3.** „Documente complete" pentru o lună înseamnă că fiecare tip din lista de
așteptări a atins numărul minim. **Cine confirmă că asta e definiția potrivită?**
______ (numele contabilului)

**F4.** Cât timp rămâne o lună încheiată „în lucru" înainte să fie considerată
întârziată? Aplicația urmează datele, nu calendarul.
Prag dorit: ______ zile după sfârșitul lunii

---

# G. Așteptările lunare per client

**Unde:** fișa clientului → *Ce așteptăm lunar*

**G1.** Un client fără așteptări configurate **nu apare niciodată** în „Documente
lipsă". Este tăcut, deliberat — aplicația nu inventează ce ar trebui să trimită
cineva.

**Confirmat, și există un pas în procedura de client nou care le configurează?**
[ ] Da / ______

**G2.** Un client fără declarații bifate **nu apare niciodată** în „Termene".
Același lucru. [ ] Confirmat

---

# H. Numele fișierelor și arhiva

**Unde:** *Documente → Arhivă*

**H1.** Numele sub care se arhivează un document este format după o regulă fixă.
Deschide arhiva unei luni: numele sunt cele pe care le vrea cabinetul?
[ ] Da / Vreau: ______

**H2.** Structura dosarelor din arhivă (client / lună) este cea potrivită?
[ ] Da / ______

**H3.** Diacriticele din numele clienților apar corect în numele fișierelor și
în arhiva descărcată? [ ] Da / ______

**H4.** Un document arhivat nu se mai modifică. Corecțiile cer redeschidere, iar
istoricul păstrează versiunile. **Corect?** [ ] Da

---

# I. Rapoarte și exporturi

**I1.** Registrul lunii (`Rapoarte → Descarcă registrul`) conține **și**
documentele rămase la verificare, cu starea scrisă pe rând — nu doar cele
aprobate.

**Corect?** [ ] Da / [ ] Nu, vreau doar aprobatele

> Un registru „curat" ar tăcea despre restul: cine exportă o lună cu 12 documente
> în verificare ar primi 88 de rânduri dintr-o sută, fără să știe.

**I2.** Cele respinse și duplicatele **nu** intră în registru. [ ] Corect / ______

**I3.** Ia o lună închisă deja și compară registrul exportat cu evidența ta
manuală. Numărul de documente și totalurile se potrivesc? [ ] Da / Diferă: ______

**I4.** Registrul declarațiilor (`Rapoarte → Descarcă declarațiile`) filtrează
după **perioada declarată**, nu după ziua în care s-a bifat. Decontul lui
decembrie marcat în ianuarie rămâne al lui decembrie. [ ] Corect / ______

---

# J. Banca

**J1.** Importă un extras real. Toate rândurile au fost citite, cu sumele
corecte? [ ] Da / ______

**J2.** Soldurile se **citesc** din extras, nu se calculează. Dacă banca declară
un sold care nu se potrivește cu suma tranzacțiilor, aplicația o spune.
**Corect?** [ ] Da

**J3.** Propunerile de potrivire vin cu motive scrise, iar legarea o face un om.
Verifică cinci propuneri: sunt rezonabile? [ ] Da / ______

**J4.** O plată parțială lasă factura „în lucru", nu „achitată". [ ] Corect

---

# K. Ce rămâne de decis de cabinet

Aplicația nu poate lua deciziile astea.

**K1. Retenția.** Nu există nicio ștergere automată. Documentele se păstrează la
nesfârșit până când cineva le șterge manual.

Cât trebuie păstrate? Documente: ______ ani. Jurnal de audit: ______ ani.

**K2. Aprobarea automată.** Este **oprită**. Chiar și un document citit cu
încredere mare așteaptă un om.

Se pornește vreodată? [ ] Nu / [ ] Da, peste pragul: ______

**K3. Mesajele automate către clienți.** Memento-urile pot pleca singure.

Se trimit? [ ] Nu / [ ] Da, cu ______ zile înainte de termen

**K4. Citirea pozelor de un model extern.** Dacă se activează, **pozele
documentelor părăsesc sediul cabinetului** și ajung la furnizorul de model.
PDF-urile cu text se citesc local, fără rețea.

Se activează? [ ] Nu / [ ] Da, cu acordul: ______

---

# Aprobare

Prin semnătura de mai jos confirm că am parcurs punctele de mai sus și că
valorile marcate sunt corecte după legislația în vigoare și după cum lucrează
cabinetul, **sau** că am notat ce trebuie schimbat înainte de pornire.

Confirm de asemenea că am înțeles că:

- aplicația **nu depune** declarații la ANAF;
- aplicația **nu calculează** sumele din declarații;
- aplicația **nu interpretează** legislația fiscală;
- termenele din catalog sunt configurabile și **răspunderea pentru ele este a
  cabinetului**.

| | |
|---|---|
| Nume și prenume | ________________________ |
| Calitate (expert contabil / contabil autorizat) | ________________________ |
| Nr. carnet CECCAR | ________________________ |
| Data | ________________________ |
| Semnătura | ________________________ |

**Puncte rămase de schimbat înainte de pornire:**

1. ______________________________________________
2. ______________________________________________
3. ______________________________________________

---

> **Pentru echipa tehnică:** cât timp acest document nu este semnat, starea
> corectă în raportul de release este **ACCOUNTANT SIGN-OFF REQUIRED**, nu
> „validat". Documentația tehnică nu are voie să pretindă validare fiscală.
