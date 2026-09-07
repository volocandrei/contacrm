# Registrul declarațiilor

## Ce este catalogul și ce nu este

Catalogul de obligații nu este legea fiscală scrisă în cod. Este un **tabel al
cabinetului**, populat la instalare cu un conținut inițial și administrat după
aceea din aplicație (`/obligatii/catalog`). Fiecare rând are un cod, o etichetă,
o periodicitate, un decalaj în luni față de sfârșitul perioadei și o zi.

Termenul se calculează, nu se scrie: `sfârșitul perioadei + months_after luni`,
ziua `deadline_day`, retezată la ultima zi a lunii dacă luna e mai scurtă
(`app/domain/obligations.py`).

> **TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION.** Termenele de mai jos
> sunt puncte de plecare uzuale, nu o afirmație a aplicației despre ce spune
> legea. Fiecare rând rămâne de confirmat de un contabil și de ajustat din
> ecranul de administrare acolo unde cabinetul știe altfel. Aplicația nu depune
> nimic la ANAF în locul nimănui; ține evidența.

## Conținutul inițial

| Cod | Formular | Periodicitate | Termen |
| --- | --- | --- | --- |
| `D300` | Decont TVA | lunar | luna următoare, ziua 25 |
| `D300_TRIM` | Decont TVA | trimestrial | luna următoare trimestrului, ziua 25 |
| `D301` | Decont special de TVA | lunar | luna următoare, ziua 25 |
| `D390` | Declarație recapitulativă (VIES) | lunar | luna următoare, ziua 25 |
| `D394` | Declarație informativă | lunar | luna următoare, ziua 30 |
| `D112` | Salarii și contribuții | lunar | luna următoare, ziua 25 |
| `D100` | Obligații de plată la bugetul de stat | trimestrial | luna următoare trimestrului, ziua 25 |
| `D101` | Impozit pe profit | anual | a 3-a lună după închidere, ziua 25 |
| `D205` | Informativă privind impozitul reținut la sursă | anual | a 2-a lună după închidere, ziua 28 |
| `SAFT` | D406 — SAF-T | lunar | luna următoare, ziua 30 |
| `BILANT` | Situații financiare anuale | anual | a 5-a lună după închidere, ziua 30 |
| `SITFIN_INTERIM` | Situații financiare interimare (dividende) | **fără calendar** | nu are termen calculat |

### De ce D301 are rândul lui, separat de D300

D301 nu este o variantă a decontului obișnuit: îl depune cine **nu** este
înregistrat normal în scopuri de TVA, dar a făcut achiziții intracomunitare sau
operațiuni cu taxare inversă. Este pentru altcineva, nu pentru același client în
altă formă — de aceea un client îl poate avea configurat fără să-l aibă pe D300.

## Situațiile financiare interimare: obligația fără calendar

Toate celelalte rânduri din catalog se nasc din calendar: luna se încheie,
termenul curge. Situațiile financiare interimare se nasc dintr-o **hotărâre** —
asociații vor să repartizeze dividende în cursul anului, iar pentru asta trebuie
întocmite situații financiare pe o perioadă aleasă de ei. Poate de trei ori
într-un an, poate niciodată.

Dacă ar fi fost trecute drept „anuale", ar fi apărut ca restanță la fiecare
sfârșit de an, la **toți** clienții — inclusiv la cei care nu au distribuit
nimic și nu aveau ce întocmi. O listă de restanțe false se închide o dată și nu
se mai deschide, iar odată cu ea și restanțele adevărate.

De aceea au periodicitatea proprie `ON_DEMAND`:

- `due_between()` nu produce **nicio** perioadă pentru ele — nu apar pe ecranul
  de termene și nu pot deveni restanțe;
- `deadline_for()` **refuză** să calculeze un termen și spune de ce:
  *„Obligațiile fără calendar nu au termen calculat: perioada o alege cine le
  întocmește."* Nu întoarce o dată inventată;
- `months_after` și `deadline_day` din catalog nu se citesc niciodată pentru ele.
  Sunt acolo doar fiindcă baza cere ca o zi să fie o zi
  (`deadline_day BETWEEN 1 AND 31`).

**Ce face aplicația în schimb:** le **înregistrează**. `POST
/api/v1/obligations/filings` acceptă un client, tipul de obligație, perioada
aleasă de om (`2026-09`) și o notă. Se pot înregistra mai multe perioade în
același an — cheia de unicitate fiind (client, tip, perioadă), o obligație
anuală nu ar fi permis-o, fiindcă perioada ar fi fost mereu decembrie.

Verificat de `backend/tests/test_interim_statements.py`, inclusiv contra-proba
că ecranul de termene nu este pur și simplu gol.

## Cum ajunge catalogul la un cabinet nou

`sync-obligation-types` scrie conținutul inițial la crearea primei organizații
(vezi `app/cli.py`). Comanda este idempotentă, cu o diferență care
contează: rulată din nou, adaugă codurile care lipsesc și aduce la zi eticheta și
ordinea (text), dar **nu atinge termenele**. Un cabinet care a corectat o zi
fiindcă știe altfel decât noi nu are voie să o vadă revenind la valoarea din cod
după un deploy.

## Registrul depunerilor, ca fișier

`GET /api/v1/reports/filings.csv` — un rând pe depunere: clientul, CUI-ul, codul
declarației, periodicitatea, perioada, ziua înregistrării, cine a înregistrat-o
și nota. Butonul stă pe ecranul de rapoarte, lângă celelalte exporturi.

Două alegeri merită motivul:

- **Intervalul se aplică perioadei declarate, nu zilei marcării.** Decontul lunii
  decembrie 2025 se marchează în ianuarie 2026; filtrat după ziua marcării, ar fi
  intrat în registrul anului 2026 și ar fi lipsit din cel al anului 2025, unde îi
  este locul.
- **Nu conține ce ar fi trebuit depus și nu s-a depus.** Registrul este o listă a
  faptelor înregistrate; restanțele sunt o concluzie care depinde de ziua în care
  se privește. Amestecate în același fișier, cele două s-ar citi la fel.

Este și singurul loc din care se pot vedea depunerile fără termen de calendar
alături de restul.

## Ce nu face aplicația

- **Nu depune** nicio declarație. Nu există o cale automată de transmitere către
  ANAF în această aplicație; SPV-ul este folosit doar pentru **preluarea**
  facturilor electronice (vezi [EFACTURA.md](EFACTURA.md)), iar acea preluare
  este NEVERIFICATĂ — NECESITĂ CREDENȚIALE EXTERNE.
- **Nu calculează** sumele din declarații. Ține evidența a ce trebuie depus, când
  și de către cine, plus documentele care stau la bază.
