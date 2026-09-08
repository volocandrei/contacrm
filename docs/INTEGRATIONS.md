# Integrările externe și ce s-a verificat din fiecare

Documentul acesta răspunde la o singură întrebare, pe fiecare integrare:
**cât din ea a fost verificat rulând-o, și cât rămâne o presupunere despre cum
răspunde celălalt sistem.**

Regula pe care o respectă tot proiectul: fără credențială, funcția **spune că nu
este configurată** — nu se oferă și apoi eșuează în mijlocul unei sincronizări.

> **Inventarul complet** — cu adrese, variabile de mediu, conturi necesare,
> expirări și ce anume se trimite fiecărui serviciu — este în
> [PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md](PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md).
> Fișierul de față explică **de ce** fiecare integrare are starea pe care o are;
> acela le enumeră pe toate, inclusiv pe cele care nu există.

## Ce înseamnă fiecare stare

| Stare | Înseamnă |
|---|---|
| **VERIFIED LIVE** | S-a rulat împotriva serviciului real, cu credențiale reale. |
| **VERIFIED SANDBOX** | S-a rulat împotriva mediului de test al furnizorului. |
| **MOCK VERIFIED** | S-au verificat parsarea, tratarea erorilor, izolarea și starea din baza noastră, împotriva unui dublu scris de noi după documentație. Protocolul rămâne o presupunere. |
| **NOT VERIFIED — EXTERNAL CREDENTIAL REQUIRED** | Nu s-a putut rula deloc: lipsește credențiala. |

**Nicio integrare din aplicație nu este VERIFIED LIVE.** Nu s-a primit nicio
credențială externă pe durata construcției. Ce urmează spune, pentru fiecare, ce
s-a putut totuși verifica și ce anume rămâne de confirmat la prima rulare reală.

---

## ANAF — SPV, facturi electronice (e-Factura)

**Stare: `NOT VERIFIED — PROVIDER ACCESS REQUIRED`.**

Preluarea listei de mesaje și descărcarea arhivelor din SPV nu s-au rulat
niciodată împotriva serverului ANAF: cer un certificat calificat și înregistrarea
aplicației în SPV.

**Ce s-a verificat, și nu este puțin** (`test_anaf_client.py`,
`test_anaf_archive.py`, `test_anaf_sync.py`, `test_extraction_efactura.py`):

- parsarea UBL 2.1 / RO_CIUS, inclusiv liniile de factură cu cota de TVA pe
  fiecare linie și descrierea produsului (§9);
- dezarhivarea răspunsului, cu apărare împotriva zip-slip și a arhivelor umflate;
- reînnoirea tokenului, expirarea lui, și ce se întâmplă când ANAF răspunde cu o
  eroare sau cu nimic;
- izolarea pe organizație și serializarea prin `pg_advisory_xact_lock`: două
  sincronizări simultane nu descarcă același mesaj de două ori;
- că un eșec al preluării nu marchează documente ca eșuate.

**Ce rămâne de confirmat la prima rulare reală:** că răspunsurile serverului au
forma din documentație — numele câmpurilor din listă, structura arhivei, codurile
de eroare. Restul lanțului (de la XML în jos) este verificat.

**Ce nu face aplicația deloc:** nu **depune** nimic la ANAF. Vezi
[DECLARATIONS.md](DECLARATIONS.md).

## Microsoft Graph — OneDrive, SharePoint, email

**Stare: `NOT VERIFIED — CREDENTIALS REQUIRED`.**

`MS_CLIENT_ID` / `MS_CLIENT_SECRET` / `MS_TENANT_ID` nu au fost obținute, deci
consimțământul OAuth nu s-a parcurs niciodată cu un cont real.

**Ce s-a verificat** (`test_drive_sync.py`, `test_mail_sync.py`, `drive_fake.py`):
parcurgerea folderelor, paginarea, delta-tokenul, descărcarea și așezarea
fișierelor pe clientul potrivit, criptarea refresh tokenului cu `DRIVE_TOKEN_KEY`
înainte de bază, deconectarea, și că o sincronizare eșuată pe o organizație nu
oprește restul.

**Ce rămâne de confirmat:** forma răspunsurilor Graph și comportamentul real al
delta-tokenului la expirare.

## IMAP — cutia poștală a cabinetului

**Stare: `NOT VERIFIED — CREDENTIALS REQUIRED`.**

Nu s-a primit o cutie poștală de test.

**Ce s-a verificat** (`test_imap_sync.py`, `test_imap_runner.py`, `imap_fake.py`):
citirea mesajelor, atașamentele, tipurile MIME, recunoașterea expeditorului ca
client, marcarea ca citit, și — reparat în auditul final — serializarea per
organizație, ca două rulări simultane să nu importe același atașament de două ori.

**Ce rămâne de confirmat:** dialectul serverului real (fiecare server IMAP are
particularitățile lui la `FETCH` și la flag-uri).

## SMTP — trimiterea de solicitări și memento-uri

**Stare: `NOT VERIFIED — CREDENTIALS REQUIRED`.**

`SMTP_*` nu au fost furnizate. Fără ele, aplicația folosește
`services/mail/disabled.py`: **spune** că trimiterea nu este configurată, în loc
să pretindă că a trimis.

**Ce s-a verificat** (`test_mail.py`, `test_daily_digest.py`): compunerea
mesajelor, adresele, șabloanele, ce se întâmplă la eșec, și că un memento nu se
trimite de două ori (blocare per organizație).

**Ce rămâne de confirmat:** livrarea efectivă și reputația domeniului — SPF,
DKIM, DMARC. Vezi [DEPLOY.md](DEPLOY.md).

## Modelul de extragere (AI)

**Stare: `NOT VERIFIED — CREDENTIALS REQUIRED`**, și numai pentru o parte a lanțului: citirea locală a PDF-urilor merge fără nicio cheie.

`AI_API_KEY` nu a fost furnizată. Fără ea, pornirea se **oprește** dacă
`OCR_PROVIDER` cere un model — nu pornește cu extragerea tăcut moartă
(`core/config.py`).

**Ce se verifică fără nicio cheie**, fiindcă nu are nevoie de model
(`test_extraction_pdf_text.py`, ADR-005): citirea locală a PDF-urilor cu text.
Aceasta este calea implicită și acoperă documentele emise de un ERP — fără
rețea, fără cheie, fără ca documentul să părăsească sediul.

**Ce este verificat doar pe un dublu** (`test_extraction_vision.py`): trimiterea
pozelor și a scanurilor către model, limita de mărime a imaginii
(`MAX_BYTES`), plafonul de tokeni al răspunsului (`MAX_TOKENS` — acolo se
oprește costul unei cereri), tratarea răspunsurilor incomplete, și plafonarea
încrederii sub pragul de aprobare, ca nimic citit de un model să nu se aprobe
singur (`MAX_CONFIDENCE`).

**Ce nu există:** o limită de rată pe extragere. Limitatoarele din aplicație sunt
pe autentificare și pe asistent. Costul unei rulări mari este mărginit de
`MAX_TOKENS` pe cerere, nu de un plafon zilnic — dacă asta contează pentru
cabinet, se pune în contul furnizorului, unde se și vede.

**Ce rămâne de confirmat:** calitatea reală a extragerii din poze. Aceea nu se
poate estima dintr-un dublu — vezi `docs/DOCUMENT_PROCESSING.md` pentru cum se
măsoară pe documentele cabinetului.

## SAGA — import / export

**Stare: `NOT IMPLEMENTED`, deliberat.**

Nu s-a scris nicio conversie. Motivul este în [SAGA.md](SAGA.md): formatul de
import al SAGA nu este public, iar un format ghicit ar fi produs fișiere care se
încarcă și pun cifre greșite în contabilitate — cel mai scump fel de eșec, fiindcă
nu se vede.

**Ce lipsește ca să se poată face:** un fișier real exportat din SAGA de la
cabinet, sau documentația formatului de import de la producător. Cu el, conversia
este muncă de câteva zile și verificabilă.

Ce există deja și este util imediat: exportul CSV al registrului
(`/api/v1/reports/register.csv`), în formatul pe care Excel-ul românesc îl
deschide corect — separator `;`, BOM, CRLF, virgulă zecimală
(`services/excel_csv.py`).

## Băncile — extrase de cont

**Stare: VERIFICAT PE FIȘIERE**, fără conexiune bancară.

Nu există nicio integrare directă cu vreo bancă și nu s-a promis una. Extrasele
se **încarcă** ca fișiere. Importul, potrivirea automată și reconcilierea sunt
verificate pe fișiere de test — inclusiv formatele românești cu virgulă zecimală
și codificare `cp1250`. Vezi [BANK_RECONCILIATION.md](BANK_RECONCILIATION.md).

---

## Ce înseamnă asta pentru pornirea în producție

Aplicația pornește și este utilă fără **niciuna** dintre integrările de mai sus:
clienți, perioade, documente încărcate manual sau prin linkul trimis clientului,
termene, onorarii, rapoarte, bancă din fișier. Fiecare integrare se adaugă
separat, iar cât timp lipsește, ecranul ei spune că nu este configurată.

Ordinea în care merită obținute credențialele, cu ce deblochează fiecare:
[CREDENTIALE.md](CREDENTIALE.md).
