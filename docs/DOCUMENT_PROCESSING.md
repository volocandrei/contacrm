# Ciclul unui document

De la fișierul care sosește până la rândul din registru: cine îl aduce, ce se
citește din el, cine îl verifică și ce rămâne scris despre asta.

---

## 1. Cum intră

| Sursă | Cine o pornește | Clientul se știe? |
|---|---|---|
| Încărcare din aplicație | contabilul, din *Documente → Inbox* | dacă îl alege el, sau se află din CUI |
| Link de trimitere (portal) | clientul, singur | **da**, din link |
| Email (Microsoft Graph) | sincronizarea periodică | din adresa expeditorului |
| Email (IMAP) | sincronizarea periodică | din adresa expeditorului |
| OneDrive / SharePoint | sincronizarea periodică | din dosarul urmărit |
| e-Factura (SPV ANAF) | sincronizarea periodică | **da**, din împuternicire |

Toate ajung în același loc și trec prin aceiași pași. Nu există un drum „mai
scurt" pentru vreuna: un document sosit prin email se procesează exact ca unul
urcat de mână, altfel cele două s-ar comporta diferit la a treia lună.

### Documentele primite pe WhatsApp

WhatsApp nu are astăzi o preluare automată — ar cere un cont WhatsApp Business și
un număr aprobat de Meta, adică o înregistrare de firmă, nu o setare. Ce se poate
face este drumul pe care oricum îl parcurge cabinetul: contabilul descarcă de pe
telefon pozele primite, le încarcă din *Inbox*, alege clientul și pune
**„Primit pe WhatsApp"** la „Cum a ajuns la noi".

Câmpul acela nu este cosmetic. Fără el, documentele intrau în evidență drept
„încărcat manual" — adevărat despre ultimul pas, tăcut despre primul. Cronologia
clientului spunea „a încărcat cineva un fișier" exact acolo unde răspunsul la
„dar eu v-am trimis pozele" trebuia să fie „le-am primit pe WhatsApp pe 3
septembrie".

**Se pot declara doar două proveniențe: încărcare directă și WhatsApp.** Restul —
email, OneDrive, SPV — sunt *constatări ale sistemului*: „a venit pe email"
înseamnă că am citit-o dintr-o cutie poștală. Declarate dintr-un formular, ar
înceta să fie constatări și ar deveni păreri, iar la un control diferența este
tot ce contează. Serverul le refuză explicit, cu 422, nu le ignoră în tăcere
(`MANUAL_SOURCES` în `app/api/v1/documents.py`).

---

## 2. Ce se întâmplă cu el

```
RECEIVED → PROCESSING → REVIEW_REQUIRED → APPROVED → ARCHIVED
                    ↘ ERROR          ↘ REJECTED
                    ↘ DUPLICATE
```

**Nimic nu se aprobă singur.** `AUTO_APPROVE_ENABLED` există, este oprit implicit,
și rămâne o decizie a cabinetului: aprobarea este un act contabil cu nume și oră
în jurnal.

Procesarea rulează **în afara cererii HTTP**, dintr-o coadă care este un tabel în
aceeași bază de date (`document_processing_jobs`), revendicată cu
`FOR UPDATE SKIP LOCKED`. Motivul pentru care nu există un broker separat este
scris în `backend/app/worker.py`.

---

## 3. Ce se citește din el

| Provider | Ce citește | Ce **nu** citește |
|---|---|---|
| `efactura` | factura electronică (XML UBL 2.1), inclusiv **liniile** | nimic din PDF |
| `pdf_text` | stratul de text al PDF-ului | poze, scanuri, linii |
| `local` | alege între cele două după conținut | — |
| `vision` | poze și scanuri, cu un model care vede imagini | — |
| `hybrid` | local întâi, model doar pentru ce n-a mers | — |
| `mock` | date sintetice, deterministe pe hash | **refuzat în producție** |

### Liniile facturii

Se citesc **numai** din facturi electronice. Acolo fiecare valoare stă într-un
element cu nume: `cbc:Percent` este cota, nu un procent găsit într-un text. Nu
există „80% sigur".

Din PDF-uri liniile nu se citesc și nu se vor ghici. Motivul nu este comoditatea:
o linie inventată intră direct în decontul de TVA, iar acolo greșeala se plătește.

Ce se păstrează pe linie: numărul de pe document, descrierea, cantitatea și
unitatea (cod UN/ECE), prețul unitar, valoarea fără TVA, **cota**, categoria UBL
(`S`, `AE`, `E`, `Z`) și, când documentul le declară, TVA-ul și totalul cu TVA.

Ce **nu** se calculează: TVA-ul pe linie, când documentul nu îl scrie. S-ar putea
— bază înmulțită cu cota — dar un număr calculat de noi, pus lângă unul citit de
pe factură, arată identic pe ecran, iar contabilul nu ar avea cum să le
deosebească.

**De ce contează.** Pe aceeași factură pot sta 21% pentru un produs, 11% pentru
altul și 0% pentru un serviciu scutit. Un singur procent la nivel de document este
o medie fără sens contabil, din care defalcarea nu se poate reconstitui.

La reprocesare liniile se **înlocuiesc**, nu se adaugă: adăugate, ar fi dublat
baza de TVA a lunii la fiecare reîncercare — o greșeală care nu s-ar fi văzut pe
ecranul documentului, ci abia în decont. Iar un provider care nu știe să citească
linii (`pdf_text`, `mock`) nu le șterge pe cele citite dintr-un XML.

---

## 4. Ce rămâne scris

Pentru fiecare câmp citit se păstrează **valoarea, proveniența și încrederea**:
`AI`, `OCR`, `MANUAL` sau `EMPTY`. Ecranul de verificare le arată, iar o corectură
umană marchează câmpul `MANUAL` — după care nicio reprocesare nu îl mai atinge.

Pentru document se păstrează providerul, modelul, versiunea de prompt, durata și
încrederea. Un document clasificat greșit se poate investiga peste șase luni.

---

## 5. Numele fișierului

Numele venit de la cel care a încărcat fișierul **nu ajunge niciodată** într-o
cale. Cheia de stocare este generată
(`organizations/{org}/documents/{uuid}/original/source.pdf`), iar numele lizibil
se compune la arhivare din date citite de pe document.

Aceeași funcție curăță numele la descărcare **și** în arhiva lunii — au fost o
vreme două drumuri, unul păzit și unul nu, iar cel nepăzit lăsa `../` să ajungă
intrare de ZIP.

---

## 6. Când procesarea nu merge

Ecranul *Documente → În procesare* poartă sus starea cozii. Există pentru o
întrebare care până acum nu avea unde să primească răspuns: **„de ce nu s-a
procesat documentul urcat acum douăzeci de minute?"** Documentul stătea în
„Primit", ecranul nu arăta nicio eroare — fiindcă nu era niciuna — iar singurul
semn că workerul murise era o coadă care creștea și pe care nu o vedea nimeni.
Se descoperea a doua zi, la o sută de documente neprocesate.

**Cifra care contează nu este câte cereri sunt în coadă, ci de când așteaptă cea
mai veche.** Treizeci de cereri într-o dimineață aglomerată sunt normale și se
golesc singure. Una singură care așteaptă de patruzeci de minute nu are nicio
explicație bună: ori workerul nu rulează, ori s-a blocat.

| Cifra | Ce înseamnă | Ce se face |
|---|---|---|
| în așteptare | cereri scrise, nepornite | dacă cea mai veche trece de un sfert de oră, procesarea nu rulează |
| în lucru | cereri pornite | nimic, se termină singure |
| blocate | pornite de mai mult decât `PROCESSING_STALE_AFTER_MINUTES` | `uv run python -m app.cli recover-processing` le readuce în coadă |
| eșecuri recente | cereri eșuate în ultimele două zile | fiecare are motivul scris; se reprocesează de pe documentul ei |

Panoul **nu repornește nimic**. Recuperarea are comanda ei, iar reprocesarea unui
document se cere de pe documentul acela, unde se vede exact ce se reprocesează.
Un buton care ar relua totul este exact felul de acțiune pe care cineva o apasă
de două ori.

Când starea nu se poate citi, panoul o **spune**. Ascuns la eroare, ar fi arătat
identic cu o coadă sănătoasă — adică opusul rostului lui.

---

## 7. Duplicatele

Se detectează pe conținut (SHA-256) și, separat, pe identitatea documentului
(furnizor + număr + dată). Detecția este serializată cu o încuietoare pe conținut:
fără ea, două încărcări simultane ale aceluiași fișier nu se vedeau una pe alta.

Un duplicat nu se șterge niciodată automat. Se marchează și rămâne vizibil.
