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

**Un fișier descărcat de pe WhatsApp** se încarcă manual, din *Inbox*, alegând
clientul din selector. WhatsApp nu are astăzi o preluare automată, iar
`.env.example` o spune pe față.

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

## 6. Duplicatele

Se detectează pe conținut (SHA-256) și, separat, pe identitatea documentului
(furnizor + număr + dată). Detecția este serializată cu o încuietoare pe conținut:
fără ea, două încărcări simultane ale aceluiași fișier nu se vedeau una pe alta.

Un duplicat nu se șterge niciodată automat. Se marchează și rămâne vizibil.
