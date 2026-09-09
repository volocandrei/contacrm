# Raport final — construcția pentru producție

Data: **8 septembrie 2026.** Documentul acesta răspunde la o singură întrebare:
**poate aplicația să țină datele financiare reale ale unui cabinet contabil, de
mâine?**

Pentru auditul de defecte, vezi [FINAL_PRODUCTION_AUDIT.md](FINAL_PRODUCTION_AUDIT.md).
Pentru ce trebuie făcut în ziua pornirii,
[PRODUCTION_LAUNCH_CHECKLIST.md](PRODUCTION_LAUNCH_CHECKLIST.md). Pentru starea
fiecărei integrări, [INTEGRATIONS.md](INTEGRATIONS.md).

---

## Verdict

**READY WITH WARNINGS.**

> **Actualizat la 8 septembrie 2026.** Documentul are trei straturi, în ordine
> cronologică: raportul de construcție (aici), **poarta de Go-Live**, și
> **poarta finală de release** — fiecare cu ce a găsit și ce a reparat. Verdictul
> curent este cel de la sfârșitul documentului.
>
> Poarta de Go-Live. Aceasta a găsit și reparat șase defecte, dintre care
> unul de corectitudine contabilă (ecranul de reconciliere arăta rândurile
> altui extras). Verdictul rămâne același, dar acum se sprijină pe o verificare
> de izolare care acoperă toate cele 64 de rute parametrizate și pe o restaurare
> executată, nu inspectată.

Aplicația poate porni pe date reale, cu trei condiții care nu sunt negociabile și
sunt scrise ca porți **STOP** în lista de control: secrete generate pentru
instalarea aceasta, primul cont de administrator creat cum trebuie, și o copie de
siguranță **restaurată o dată** înainte de primul client.

Avertismentele nu sunt despre ce face aplicația, ci despre ce **nu s-a putut
verifica rulând**: nicio integrare externă nu a fost probată cu credențiale
reale, fiindcă nu există niciuna. Ce depinde numai de noi — autentificare,
izolare între cabinete, ciclul documentului, termenele, rapoartele, banca din
fișier, copiile de siguranță — este verificat rulând, nu citind.

Nu este **READY** fiindcă a spune asta despre un lanț al cărui capăt nu a fost
niciodată atins ar fi o afirmație pe care nu o pot susține. Nu este **NOT READY**
fiindcă blocajul din enunț — securitatea administratorului — a fost rezolvat, iar
partea de aplicație care ține datele cabinetului funcționează și se poate folosi
fără nicio integrare.

---

## Ce s-a construit în această rundă

### Securitatea administratorului (blocantul din enunț)

- politică de parole aplicată în amândouă capetele, cu aceleași reguli verificate
  de un test de contract care citește cazurile din fișierul TypeScript;
- o parolă nu poate conține fragmente din emailul sau numele contului;
- schimbarea parolei din aplicație, cu parola curentă cerută;
- lista sesiunilor active și revocarea celorlalte, dintr-un ecran propriu;
- resetarea unei parole de către administrator **revocă toate sesiunile** acelui
  utilizator — altfel o parolă compromisă rămânea utilă prin sesiunea deschisă.

### Declarațiile

- catalogul completat: D301, D101, D205, plus situațiile financiare interimare;
- periodicitatea `ON_DEMAND`, pentru obligațiile care nu se nasc din calendar:
  nu produc perioade, nu apar ca restanțe, iar calculul termenului **refuză** și
  spune de ce în loc să întoarcă o dată inventată;
- înregistrarea lor de pe fișa clientului, cu perioada aleasă de om și nota lui;
- lista a ce s-a înregistrat, pe fișa clientului — fără ea, o depunere fără
  calendar ar fi fost scrisă în evidență și invizibilă în aceeași clipă;
- registrul declarațiilor ca fișier, cu intervalul aplicat perioadei declarate,
  nu zilei marcării.

### Documentele

- liniile facturii cu **cota de TVA pe fiecare linie** și descrierea produsului,
  citite din XML-ul e-Factura;
- desfacerea automată a teancurilor scanate, cu proveniența fiecărei bucăți;
- perechea XML ↔ PDF a aceleiași facturi, cu stări explicite și cu **conflictul
  de sume care nu se leagă niciodată**;
- proveniența declarată la încărcarea manuală: se pot afirma două drumuri,
  încărcare directă și WhatsApp, iar restul — email, OneDrive, SPV — sunt
  constatări ale sistemului și se refuză explicit;
- centrul de procesare: starea cozii pe ecran, cu cifra care contează (de când
  așteaptă cea mai veche cerere, nu câte sunt).

### Banca

Import de extrase, potrivire automată cu documentele, reconciliere și ecranul ei.
Nicio conexiune bancară directă — și nu s-a promis una.

### Ce s-a reparat, găsit rulând

Zece defecte în auditul de pregătire, dintre care două de securitate (o formulă
executabilă într-un CSV exportat, o cale de fișier venită de la client) și patru
de integritate sau de comportament (aceeași reamintire trimisă de patru ori, ziua
serverului confundată cu ziua cabinetului, o stivă din documentație care nu putea
porni, un asistent fără limită de cost). Detaliile, cu reproducerea fiecăruia, în
[FINAL_PRODUCTION_AUDIT.md](FINAL_PRODUCTION_AUDIT.md).

---

## Ce nu s-a putut verifica, și de ce

| Integrare | Stare | Ce lipsește |
|---|---|---|
| ANAF / SPV (e-Factura) | NOT VERIFIED — EXTERNAL CREDENTIAL REQUIRED | certificat calificat, aplicație înregistrată în SPV |
| Microsoft Graph (OneDrive, email) | MOCK VERIFIED | `MS_CLIENT_ID` / `MS_CLIENT_SECRET` / `MS_TENANT_ID` |
| IMAP | MOCK VERIFIED | o cutie poștală de test |
| SMTP | MOCK VERIFIED | `SMTP_*` și un domeniu cu SPF/DKIM/DMARC |
| Model de extragere (poze, scanuri) | MOCK VERIFIED | `AI_API_KEY` |
| SAGA | neimplementat, deliberat | un fișier real exportat din SAGA sau documentația formatului de import |

Detaliile fiecăreia — ce anume **s-a** verificat și ce rămâne o presupunere
despre protocolul celuilalt sistem — în [INTEGRATIONS.md](INTEGRATIONS.md).

**Despre SAGA, explicit:** nu s-a scris nicio conversie. Formatul de import nu
este public, iar unul ghicit ar produce fișiere care se încarcă și pun cifre
greșite în contabilitate — cel mai scump fel de eșec, fiindcă nu se vede. Ce
există în loc și este util imediat: exportul CSV al registrului, în formatul pe
care Excel-ul românesc îl deschide corect.

---

## Ce rămâne de făcut de om, nu de aplicație

1. **Catalogul de declarații se confirmă cu un contabil**, rând cu rând.
   Termenele din cod sunt puncte de plecare uzuale, nu o afirmație a aplicației
   despre ce spune legea. Se ajustează din `/administrare/declaratii`.
2. **Copia de siguranță se restaurează o dată**, pe o instalare de test, înainte
   de primul client real. O copie care nu s-a restaurat niciodată nu este o
   copie.
3. **Prima rulare a fiecărei integrări se face cu un singur client**, urmărită.
4. **Cineva trebuie alertat când workerul moare.** Panoul de procesare arată
   starea cozii pe ecran, dar nu sună pe nimeni noaptea.

---

## Cifrele

| | Valoare |
|---|---|
| Teste backend | **1.972** |
| Teste frontend | **415** |
| Teste end-to-end (browser real, backend real) | 93 |
| `mypy --strict` pe 176 de module | curat |
| `ruff check` + `ruff format --check` pe 312 fișiere | curat |
| Migrări aplicate de la zero | 27, până la `d7c2a41f8b95` |
| Secrete în repository | 0 |
| Rute cerute de frontend și inexistente în backend | 0 |
| Integrări externe verificate live | **0** — vezi tabelul de mai sus |

Fiecare regulă nouă din runda aceasta este verificată **prin mutație**: se strică
deliberat regula și se confirmă că testul cade. O aserțiune care trece și cu
regula stricată nu apără nimic.

## Cum se verifică ce scrie aici

```bash
# backend: lint, tipuri, migrări, teste
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run alembic upgrade head
uv run pytest

# frontend: lint, tipuri, teste, build
cd ../frontend
npm run lint
npx tsc --noEmit -p tsconfig.app.json
npm test -- --run
npm run build

# end-to-end, într-un browser real
npm run test:e2e
```

Aceleași comenzi rulează în CI la fiecare push, plus trei verificări de igienă:
niciun `.env` comis, niciun document contabil în repo, niciun caracter de
control în surse.

---

# POARTA FINALĂ DE GO-LIVE

**8 septembrie 2026.** Verificare independentă, pornită de la cod, nu de la
documentația scrisă până acum. Unde documentația și implementarea au spus lucruri
diferite, **codul a decis** și documentația a fost corectată.

## Ce s-a găsit la această poartă

Șase defecte reale, toate reproduse înainte de a fi reparate, toate cu test de
regresie verificat prin mutație.

### G-01 · P0 · CORECTITUDINE CONTABILĂ · Ecranul de reconciliere arăta alte rânduri

`GET /api/v1/bank/transactions` declara filtrele ca parametri separați
(`statement_id`, `client_id`), într-un contract care este **camelCase în ambele
direcții**. Interfața cerea `?statementId=...`; FastAPI nu recunoștea parametrul
și **îl ignora în tăcere**.

Rezultatul: ecranul de bancă arăta **toate tranzacțiile cabinetului**, nu pe cele
ale extrasului selectat. Fără nicio eroare, cu răspuns 200. Cine bifa „nimic
nepotrivit" pe un extras se uita, de fapt, la rândurile tuturor extraselor.

Aceeași scăpare era pe `GET /bank/statements` (`clientId`) și pe ruta de import
(șase parametri).

**Reparat** cu tiparul pe care restul aplicației îl folosea deja — un model
`ApiModel` cu `alias_generator=to_camel`, exact lecția scrisă în comentariile
rutei de perioade și a celei de rapoarte. Trei teste de regresie; la mutație, cad
două.

**De ce nu s-a văzut până acum:** backendul simulat, pe care se dezvoltă ecranul,
are un singur extras — filtrat sau nu, arăta la fel. Mockul aplică de acum
aceleași filtre și are testele lui.

### G-02 · P1 · PERFORMANȚĂ · O interogare per rând în lista de tranzacții

Aceeași rută încărca `transaction.matches` leneș: patruzeci de tranzacții
însemnau patruzeci de interogări în plus, un an de extrase câteva mii.
**Reparat** cu `selectinload`. La mutație, testul cade cu 5 interogări față de 40.

### G-03 · P1 · Lista de tranzacții nu avea nicio limită

Chemată fără filtru, întorcea fiecare tranzacție a cabinetului. **Reparat** cu un
plafon care **refuză explicit** peste `MAX_TRANSACTIONS`, în loc să trunchieze: o
listă tăiată la o mie arată exact ca una completă, iar într-o reconciliere rândul
care lipsește este chiar cel căutat.

### G-04 · P1 · SECURITATE · O variabilă care părea să schimbe hash-ul parolelor

`PASSWORD_HASH_ALGORITHM=argon2id` era enumerată în `.env.example` și **nu o citea
niciun modul**. Algoritmul este fixat în cod. Pusă pe altceva, ar fi lăsat pe
cineva să creadă că a schimbat o decizie de securitate pe care nu a schimbat-o.
**Scoasă**, cu explicația în locul ei.

### G-05 · P1 · Un provider inexistent pornea liniștit

`AI_PROVIDER` era singurul câmp de provider **fără validator**, iar `.env.example`
enumera `openai` și `azure_openai`, care nu există nicăieri în cod. `AI_PROVIDER=openai`
pornea, apărea pe ecranul de setări ca provider activ, și nu făcea nimic. Un
cabinet ar fi putut deschide un cont OpenAI pentru o valoare pe care n-o citește
nimeni. **Reparat**: validator, ca la ceilalți provideri; lista corectată.

Tot aici: `OCR_FALLBACK_PROVIDER` — fără corespondent în cod, nemarcată. Scoasă.

### G-06 · P2 · O alegere contabilă pe care nimeni n-o putea găsi

`REFERENCE_PERIOD_STRATEGY` decide **din ce dată se derivă luna contabilă** a unui
document (ADR-008) — una dintre cele mai consecvente alegeri din aplicație — și
lipsea din `.env.example`. Se putea afla doar citind sursa. **Adăugată.**

### Ce ține reparațiile pe loc

Un audit anterior curățase lista de variabile o dată, de mână; se umpluse la loc.
De aceea verificarea nu este un document, ci un test:
`backend/tests/test_env_example_contract.py` — patru reguli, toate confirmate prin
mutație. Cade dacă apare un câmp fără intrare în `.env.example`, o variabilă pe
care n-o citește nimeni, un marcaj `NEIMPLEMENTAT` pus pe ceva ce chiar există,
sau o valoare care arată a secret.

---

## Izolarea între cabinete — verificată pe toată suprafața

Testul nou `backend/tests/test_tenant_isolation_sweep.py` construiește **două
cabinete complete** — fiecare cu client, contact, document cu fișier real,
tranzacție bancară, declarație, profil, sarcină, alias, link de trimitere,
împuternicire ANAF, cutie IMAP, dosare OneDrive — și probează **fiecare rută
parametrizată a aplicației**, citită din tabela reală de rutare.

**64 de rute probate.** Pentru 43 dintre ele proba este **adâncă**: aceeași cerere
cu identificatorii proprii reușește, deci un 404 pe cei străini vine din graniță,
nu din altceva. Celelalte 21 sunt **enumerate explicit**, cu motivul fiecăreia, și
un test cade dacă lista crește sau se micșorează fără ca cineva să spună de ce.

Trei lucruri au fost întărite pe parcurs, fiindcă prima versiune trecea din
motive greșite:

1. **`folder_id` însemna două lucruri** — dosar de fișiere și dosar de email.
   Rutele de email primeau id-ul greșit și răspundeau 404 din „nu există", nu din
   „nu este al tău".
2. **Un corp gol producea 422 înainte de verificarea de organizație.** Douăzeci de
   rute erau „probate" fără să atingă vreodată granița. Corpurile vin acum din
   schema OpenAPI a aplicației, iar pentru rutele probate adânc se cere **exact
   404** — un 422 venit de dincolo de graniță dovedește că cererea a **ajuns** la
   resursa altcuiva.
3. **Codul de răspuns nu este toată dovada.** O scriere se poate executa și
   totuși răspunde 404, fiindcă răspunsul se recitește prin altă interogare, cu
   propriul filtru. Scoțând filtrul din interogarea de bază a documentelor,
   `PATCH /documents/{al altuia}` chiar modifica documentul celuilalt cabinet — și
   răspundea 404. De aceea există acum și un test care compară **starea** lui B
   înainte și după sweep. La mutație, el este singurul care cade.

În plus, verificate separat: descărcarea și previzualizarea **cu fișiere adevărate
în stocare** (altfel 404 ar fi venit din lipsa octeților), exporturile CSV,
căutarea liberă, acțiunile în masă, identificatorii străini trimiși în corp, și
tokenul de portal.

---

## Copie și restaurare — parcurse, nu inspectate

Procedura din [RUNBOOK.md](RUNBOOK.md), executată integral pe o instalare
separată:

| Pas | Rezultat |
|---|---|
| Bază goală → `alembic upgrade head` | 44 de tabele, 27 de migrări |
| Date reprezentative: 6 clienți, documente cu fișiere reale, extras bancar, 41 de depuneri | scrise prin aplicație, nu direct în bază |
| `check-storage` înainte de copie | baza și stocarea se potrivesc |
| `pg_dump --format=custom` (T1) + copia stocării (T2) | 174 KB + 2 fișiere |
| **Distrugere**: `DROP DATABASE` + ștergerea stocării | — |
| Restaurare: `createdb`, `pg_restore`, fișierele, `alembic upgrade head` | **6 secunde** |
| `check-storage` după restaurare | se potrivesc |
| Amprentă înainte/după (număr de rânduri + SHA-256 al fiecărui fișier) | **identice** |
| Aplicația pornită pe baza restaurată | `health` 200, autentificare 200, document 200, **descărcare 200, 915 octeți, PDF valid** |

Și cazul negativ, fiindcă altfel verificarea n-ar dovedi nimic: cu un fișier lipsă
`check-storage` iese cu 1 și îl numește; cu un fișier de altă dimensiune, la fel.

---

## Rezultatul pe fiecare capitol

| Capitol | Verdict | Cum s-a stabilit |
|---|---|---|
| **Securitate** | **PASS** | sweep de rute fără sesiune, antete, CORS fără `*`, rate limiting, secrete absente din cod și din istoria git |
| **Autentificare** | **PASS** | argon2id, politică de parole în amândouă capetele, cookie `HttpOnly`/`Secure`/`SameSite`, revocare de sesiuni, resetarea revocă tot |
| **Izolare între cabinete** | **PASS** | 64 de rute probate, 43 adânc, plus verificarea stării — vezi mai sus |
| **Bază de date** | **PASS** | migrări de la zero pe bază goală, 44 de tabele, constrângeri și indexuri aplicate |
| **Copie de siguranță** | **PASS** | executată, nu inspectată |
| **Restaurare** | **PASS** | executată, cu fișiere identice pe octet și aplicația pornită peste ea |
| **Procesarea documentelor** | **PASS** | încărcare → stocare → citire → verificare → arhivă → descărcare, pe fișiere reale |
| **Desfacerea teancurilor** | **PASS** | detecția paginilor, proveniența fiecărei bucăți, originalul păstrat |
| **Reconciliere bancară** | **PASS** *(după G-01, G-02, G-03)* | import, potrivire, parțiale, reversibilitate; `Decimal` peste tot |
| **Declarații** | **PASS** | catalogul, periodicitatea fără calendar, registrul; termenele rămân de confirmat de un contabil |
| **e-Factura** | **NOT VERIFIED** | parsarea, arhiva, împerecherea și izolarea sunt verificate; protocolul ANAF nu — cere certificat calificat |
| **SAGA** | **NOT IMPLEMENTED — BLOCAT** | lipsește formatul; nu se inventează |
| **Exporturi** | **PASS** | registru, raport, declarații, arhivă ZIP; CSV pentru Excel românesc |
| **Monitorizare** | **FAIL** | nu există nicio integrare. Vezi P1-01 |
| **Deployment** | **PASS cu avertisment** | stiva pornește local; nu există încă o instalare de producție |

## Integrările, una câte una

| Integrare | Stare |
|---|---|
| PostgreSQL | **verificat rulând** |
| Stocare locală | **verificat rulând** |
| Stocare S3 | `MOCK VERIFIED` (`moto`) |
| ANAF / SPV | `NOT VERIFIED — PROVIDER ACCESS REQUIRED` |
| Microsoft Graph | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| IMAP | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| SMTP | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| Anthropic — extragere | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| Anthropic — asistent | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| WhatsApp | `NOT IMPLEMENTED` — nu deschide cont Meta |
| SAGA | `NOT IMPLEMENTED` — lipsește formatul |
| Monitorizare | `NOT IMPLEMENTED` |

Detalii pe fiecare, cu adrese, variabile, expirări și ce anume s-a verificat:
[PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md](PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md).

---

## Blocante

| Prioritate | Blocant | De ce | Ce trebuie | Cine | Stare |
|---|---|---|---|---|---|
| **P0-01** | Copie de siguranță restaurată pe instalarea reală | O copie care nu s-a restaurat niciodată nu este o copie | Parcurgerea procedurii pe serverul real, o dată | proprietar + infra | **de făcut înainte de primul client** |
| **P0-02** | Secrete generate pentru instalare | `SECRET_KEY` implicit = oricine își semnează un token | `SECRET_KEY`, `DRIVE_TOKEN_KEY`, `CRON_SECRET` noi | infra | de făcut |
| **P0-03** | Primul administrator, fără parolă implicită | `seed-dev` refuză producția, dar contul se creează manual corect | `create-admin`, apoi schimbarea parolei din aplicație | proprietar | de făcut |
| **P1-01** | **Nimeni nu este anunțat când workerul moare** | Documentele intră și rămân în așteptare; ecranul arată coada, dar nu sună pe nimeni | Un serviciu care interoghează `/health/ready` (UptimeRobot, Healthchecks.io — plan gratuit) | infra | **neacoperit de aplicație** |
| **P1-02** | Catalogul de declarații neconfirmat | Termenele din cod sunt puncte de plecare, nu lege | Un contabil confirmă rând cu rând, din `/administrare/declaratii` | cabinet | de făcut |
| **P1-03** | `MS_CLIENT_SECRET` expiră | Cea mai frecventă cauză de „nu mai vin documente" | Data în calendar — vezi [PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md) | infra | de făcut la conectare |
| **P1-04** | Prima rulare a fiecărei integrări | Protocoalele externe nu au fost atinse | Cu **un singur client**, urmărită | proprietar | după credențiale |
| **P2-01** | SAGA | Formatul nu este public | Un fișier real exportat din SAGA | cabinet | **blocat pe intrare externă** |
| **P2-02** | Retenția automată | Nu există niciun job | Decizie a cabinetului, apoi implementare | cabinet | amânat deliberat |
| **P2-03** | Paginare pe lista de tranzacții | Astăzi are plafon cu refuz explicit | Paginare adevărată, dacă un extras trece de o mie de rânduri | — | nu blochează |

---

## Cele două concluzii, separate

### A. APLICAȚIA

**READY** — cu cele trei porți P0 parcurse în ziua pornirii.

Software-ul este sigur și corect pe ce depinde numai de el: autentificare,
izolare între cabinete, ciclul documentului, aritmetica banilor în `Decimal`,
termenele, rapoartele, banca din fișier, copiile de siguranță. Fiecare afirmație
de aici este verificată **rulând**, iar regulile noi sunt confirmate prin mutație.

### B. INTEGRĂRILE

**NOT READY** — și nu din cauza codului.

```text
PostgreSQL              — VERIFICAT RULÂND
Stocare (disc)          — VERIFICAT RULÂND
Stocare (S3)            — MOCK VERIFIED
Microsoft Graph         — NOT VERIFIED — credențiale
IMAP                    — NOT VERIFIED — credențiale
SMTP                    — NOT VERIFIED — credențiale
ANAF / SPV              — NOT VERIFIED — certificat calificat
Anthropic (extragere)   — NOT VERIFIED — credențiale
Anthropic (asistent)    — NOT VERIFIED — credențiale
WhatsApp                — NEIMPLEMENTAT (deliberat)
SAGA                    — NEIMPLEMENTAT — lipsește formatul
Monitorizare            — NEIMPLEMENTAT
```

Niciuna dintre ele nu împiedică pornirea: aplicația funcționează și este utilă
fără toate. Fiecare se adaugă separat, iar cât timp lipsește, ecranul ei spune că
nu este configurată.

---

## Cifrele porții

| | Valoare |
|---|---|
| Teste backend | **1.972**, toate verzi |
| Teste frontend | **415**, toate verzi |
| Teste end-to-end, în browser real pe backend real | **93**, toate verzi |
| `ruff check` + `ruff format --check` (312 fișiere) | curat |
| `mypy --strict` (176 de module) | curat |
| `npx tsc --noEmit` + `oxlint` + `npm run build` | curat |
| Rute parametrizate probate pentru izolare | **64** din 64 |
| … dintre ele, probate **adânc** | 43 |
| … enumerate explicit ca superficiale, cu motiv | 21 |
| Defecte găsite la această poartă | **6**, toate reparate |
| Reguli noi confirmate prin mutație | toate |
| Secrete în cod sau în istoria git | **0** |
| Documente contabile în repository | **0** |
| Integrări externe verificate live | **0** |

## VERDICT

## READY WITH WARNINGS

Aplicația poate ține date reale ale unui cabinet, cu condiția ca cele trei porți
**P0** să fie parcurse înainte de primul client. Avertismentele sunt despre
**integrări neverificate**, nu despre defecte cunoscute în cod: nu există niciun
blocant de securitate, de izolare, de copie/restaurare, de corectitudine contabilă
sau de pornire care să fie deschis.

Nu este `READY FOR PRODUCTION` fără rezerve fiindcă a spune asta despre lanțuri al
căror capăt nu a fost niciodată atins ar fi o afirmație pe care nu o pot susține.

---

# POARTA FINALĂ DE RELEASE

**8 septembrie 2026**, după poarta de Go-Live. Scopul acestei runde nu a fost un
audit nou, ci închiderea blocantelor operaționale rămase — și verificarea că ce
scrie în raportul anterior corespunde cu ce este în cod.

**Ce se păstrează mai jos, neatins:** raportul de construcție și poarta de
Go-Live, cu cele șase defecte găsite acolo. Ce urmează este runda **următoare**,
cu constatările ei.

---

## Ce s-a găsit acum

Trei defecte, plus o regresie introdusă și prinsă în timpul lucrului.

### R-01 · P1 · SECURITATE · Contul cel mai puternic, cel mai slab verificat

`create-admin` — comanda care creează **primul administrator al unei instalări
de producție** — verifica doar **lungimea** parolei, nu politica aplicației.

Deci `administrator2026` era refuzat la schimbarea parolei din interfață și
**acceptat aici**. Exact în momentul instalării, când cineva grăbit alege ceva
ușor de ținut minte, contul cu cele mai multe drepturi din tot sistemul trecea
prin cel mai slab control.

**Reparat:** aceeași `app/domain/passwords.py` ca peste tot — minimum 12
caractere, cel puțin 5 diferite, și interdicția de a conține fragmente din email
sau din nume. Șase teste noi; la mutație, două cad.

Restul comenzii era deja corect și a rămas: parola se citește cu `getpass`,
niciodată dintr-un argument (argumentele ajung în istoricul shell-ului și în
lista de procese); nu resetează parole, deci nu este o portiță; se oprește dacă
adresa există deja.

### R-02 · P1 · Un worker mort nu suna pe nimeni

Blocantul **P1-01** din raportul anterior. Ecranul de procesare arăta coada, dar
nu exista niciun semnal pe care un monitor extern să-l poată urmări: un worker
mort se descoperea a doua zi, la o sută de documente neprocesate.

**Reparat:** workerul scrie un semn de viață la fiecare tur, într-un rând din
baza de date; `/health/workers` răspunde **503** când semnul îmbătrânește peste
`WORKER_HEARTBEAT_TIMEOUT_SECONDS` — 90 de secunde pentru workerul continuu,
care bate la fiecare tur. Pe o platformă serverless, unde bătaia vine din cron,
pragul se ridică singur la trei ture de cron; altfel alarma ar suna între
oricare două bătăi. Vezi `docs/VERCEL_DEPLOYMENT_REPORT.md`, V-04.

Patru alegeri care fac diferența dintre un semnal util și unul decorativ:

- **se bate înaintea muncii, nu după.** Dacă turul se blochează într-un apel de
  rețea care nu se mai întoarce, ultimul semn rămâne cel de dinainte și
  îmbătrânește — exact ce trebuie să declanșeze alarma. Un proces blocat este viu
  pentru sistemul de operare și mort pentru cabinet;
- **ceasul este al bazei, nu al procesului.** Două mașini cu ceasuri
  nesincronizate ar fi produs o vechime imposibilă, iar alarma ar fi sunat pentru
  NTP, nu pentru worker;
- **un worker care nu a raportat niciodată nu este sănătos.** O instalare în care
  workerul nu a fost pornit deloc arată exact ce este, din prima zi;
- **`/health/ready` NU cade odată cu workerul.** Aici am deviat deliberat de la
  cererea inițială, și merită motivul: `ready` este citit de load balancer. Dacă
  un worker mort l-ar face să răspundă 503, load balancerul ar scoate din rotație
  **toate** instanțele de API — o problemă de procesare s-ar transforma într-o
  cădere totală, exact în clipa în care cabinetul are nevoie să deschidă ecranul
  cozii ca să înțeleagă ce se întâmplă. Un worker mort trebuie să **sune un om**,
  nu să oprească aplicația. Starea lui apare și în corpul lui `ready`, fără să-i
  influențeze codul HTTP.

Funcționează și pentru instalările care rulează workerul din cron.

### R-03 · P2 · Două ADR-uri descriau altceva decât codul

- **ADR-003** se numea „Procesare asincronă cu **Celery + Redis**". Coada este,
  de la M6, un outbox tranzacțional în PostgreSQL — deliberat, cu motivul scris
  în `app/worker.py`. Cine citea ADR-ul putea crede că trebuie să instaleze
  Redis.
- **ADR-005** enumera ca implementări Tesseract, Google Document AI, AWS Textract
  și Azure DI. Niciuna nu există în cod; singurul furnizor extern este Anthropic.

**Reparat fără rescrierea istoriei:** fiecare ADR primește un antet cu ce s-a
implementat de fapt și de ce s-a schimbat decizia; textul original rămâne
dedesubt, ca înregistrare a ce s-a hotărât atunci.

### R-04 · regresie introdusă și prinsă în aceeași rundă

Prima versiune a rutelor de sănătate primea sesiunea de bază de date prin
`Depends`. O dependență rulează **înaintea** funcției: cu baza căzută, cererea
murea acolo și ieșea **500 cu urmă de excepție**, în loc de 503-ul controlat pe
care îl așteaptă load balancerul.

Ruta de sănătate trebuie să răspundă **mai ales** când ceva este stricat. Sesiunea
se deschide acum în interiorul funcției, cu tratare de eroare, iar patru teste
noi verifică exact acest caz — inclusiv că nu iese niciun traceback pe o rută
publică. La mutație, revenirea la varianta veche cade.

---

## Ce s-a verificat, dincolo de reparații

### Clasa de defect G-01, pe toată aplicația

Defectul din poarta anterioară — un filtru `snake_case` într-un contract
camelCase, ignorat în tăcere — a fost căutat pe **toți cei 74 de parametri de
query** ai aplicației. **Zero** rămași.

Un test îl blochează de acum la sursă: citește schema OpenAPI publicată și cade
dacă vreun parametru iese `snake_case`, oricare ar fi calea aleasă în cod. Plus
unul care numește explicit filtrele băncii, ca o rescriere care le-ar scăpa cu
totul să nu treacă tăcut.

### Nicio reușită falsă la stocare

Simulat: disc plin, drept de scriere refuzat, fișier dispărut între rândul din
bază și stocare.

- încărcarea eșuează **zgomotos**, cu excepție, și nu lasă niciun rând în urmă;
- arhivarea **nu marchează** documentul ca `ARHIVAT` dacă scrierea copiei a
  eșuat.

Al doilea este cel care contează: un document `ARHIVAT` fără fișier în arhivă
arată identic cu unul arhivat corect — apare pe ecran, intră în raport, se numără
la închiderea lunii. Lipsa se descoperă la un control, luni mai târziu, când nu
mai există de unde să fie refăcut. Verificat prin mutație: mutând atribuirea
statusului înaintea copierii, două teste cad.

### N+1 pe ecranele netestate până acum

`test_documents_volume.py` apăra lista de documente. Ecranele adăugate după el nu
fuseseră niciodată măsurate. Acum sunt: clienți, tranzacții bancare, termene,
registrul declarațiilor, starea cozii — fiecare cu numărul de interogări care
**nu crește** cu numărul de rândurilor.

Nu se măsoară secunde: un test cronometrat cade când mașina e ocupată și trece
când nu e.

### Dependențe

`npm audit` — **0 vulnerabilități**, în runtime și în dev. Backendul rulează pe
versiuni curente (FastAPI 0.141, SQLAlchemy 2.0.52, cryptography 50.0.1, pyjwt
2.13, argon2-cffi 25.1). Nimic de actualizat forțat.

### Migrare de la zero

Bază goală → `alembic upgrade head` → **28 de migrări**, 45 de tabele. Migrarea
nouă creează o tabelă și nu atinge nimic existent, deci rollback-ul aplicației
este sigur fără `downgrade`.

---

## Documentația operațională, completă

Șapte documente noi, plus corecturile de mai sus. Toate derivate din cod, nu din
memorie.

| Document | Pentru cine, și la ce răspunde |
|---|---|
| [PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md) | ce trebuie configurat ca o problemă să sune un om; praguri, politica de alertare, ce **nu** este monitorizat |
| [PRODUCTION_INCIDENT_RUNBOOK.md](PRODUCTION_INCIDENT_RUNBOOK.md) | 14 incidente, fiecare cu semne, primul lucru, diagnostic, reparare, escaladare |
| [PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md) | ziua deployului, în ordine; rollback pe tipuri de migrare; RPO/RTO ca **ținte**, nu garanții |
| [RELEASE_MANIFEST.md](RELEASE_MANIFEST.md) | ce anume se lansează: commit, migrare, dependențe, limitări cunoscute |
| [ACCOUNTING_UAT_CHECKLIST.md](ACCOUNTING_UAT_CHECKLIST.md) | **pentru contabil**: fiecare regulă care cere confirmare umană, cu loc de semnătură |
| [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) | ziua unui operator, în ordinea ecranelor |
| [ACCOUNTANT_RUNBOOK.md](ACCOUNTANT_RUNBOOK.md) · [ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md) | ce face aplicația, în termeni de cabinet; ce ține administratorul în funcțiune |

`README.md` spune acum, în tabel, **ce nu face aplicația deliberat** — ca nimeni
să nu deschidă un cont Meta pentru WhatsApp sau să aștepte un export SAGA.

---

## Matricea finală

| Zonă | Rezultat | Dovada |
|---|---|---|
| Backend | **PASS** | 1.999 de teste, `ruff` + `mypy --strict` curate |
| Frontend | **PASS** | 415 teste, `tsc` + `oxlint` + build curate |
| Bază de date | **PASS** | 28 de migrări de la zero, 45 de tabele |
| Securitate | **PASS** | sweep de rute, secrete absente din cod și din istoria git, politica de parole peste tot |
| Izolare între cabinete | **PASS** | 64/64 rute parametrizate, plus verificarea stării |
| Documente | **PASS** | încărcare → citire → verificare → arhivă → descărcare, pe fișiere reale |
| OCR local | **PASS** | PDF cu text și e-Factura, fără rețea |
| AI (poze) | **NOT VERIFIED** | cere `AI_API_KEY`; limitele și plafonul de tokeni sunt verificate pe dublu |
| Email (SMTP) | **NOT VERIFIED** | cere credențiale |
| Microsoft Graph | **NOT VERIFIED** | cere credențiale |
| IMAP | **NOT VERIFIED** | cere o cutie poștală |
| ANAF / SPV | **NOT VERIFIED** | cere certificat calificat |
| Stocare | **PASS** | plus eșecurile: disc plin, fișier lipsă — fără reușite false |
| Copie de siguranță | **PASS** | executată |
| Restaurare | **PASS** | executată: 6 secunde, fișiere identice pe octet, aplicația pornită peste ea |
| Worker | **PASS** | semn de viață, recuperare de joburi, izolare pe organizație |
| Cron | **PASS** | secret obligatoriu, 404 fără el, serializare per organizație |
| **Monitorizare** | **PASS (aplicație) / DE CONFIGURAT (extern)** | adresele există și sunt testate; monitorul extern rămâne de pornit |
| Performanță | **PASS** | fără N+1 pe ecranele măsurate; fără liste nemărginite |
| Accesibilitate | **PASS** | verificată în browser real |
| Deployment | **PASS cu fereastră** | 5–15 minute, anunțate; nu se pretinde zero-downtime |
| Contabilitate | **ACCOUNTANT SIGN-OFF REQUIRED** | mecanismul e verificat; valorile cer un contabil |

---

## Notă

| Zonă | Notă | Justificare |
|---|---|---|
| Securitate | **9/10** | argon2id, RBAC, izolare probată pe toate rutele, secrete curate, cookie-uri corecte. Minus un punct: nu a existat un test de penetrare extern |
| Integritatea datelor | **9/10** | `Decimal` peste tot, fără reușite false la stocare, idempotență, audit. Minus: fără verificare de sumă de control la nivel de fișier în afara `check-storage` |
| Fiabilitate | **9/10** | coadă durabilă, recuperare după moartea procesului, semn de viață. Minus: fără rulare îndelungată sub sarcină reală |
| Backend | **9/10** | 1.999 de teste, tipuri stricte, reguli verificate prin mutație |
| Frontend | **8/10** | 415 teste + 93 în browser real. Minus: mai puțină acoperire pe ecranele rar folosite |
| Documente | **9/10** | tot lanțul verificat pe fișiere reale, inclusiv desfacerea teancurilor și perechea XML↔PDF |
| Contabilitate | **7/10** | mecanismul este corect și verificat; **valorile nu sunt confirmate de un contabil** — de aceea nu mai mult |
| Integrări | **4/10** | codul și tratarea erorilor sunt verificate pe dubluri; **niciun protocol extern nu a fost atins** |
| Monitorizare | **7/10** | semnalele există și sunt testate; alertarea rămâne complet externă și neconfigurată |
| Copii / recuperare | **9/10** | executate, nu inspectate. Minus: nu pe infrastructura reală de producție |
| Deployment | **7/10** | stiva pornește curat de la zero; nu există încă o instalare de producție, și există fereastră de întrerupere |
| Documentație | **9/10** | derivată din cod, cu vocabular explicit pentru ce nu este verificat |
| **General** | **8/10** | software-ul este gata; ce lipsește este contactul cu lumea din afară |

---

## Blocante rămase

| Prioritate | Blocant | De ce | Ce trebuie | Cine |
|---|---|---|---|---|
| **P0-01** | Copie restaurată pe instalarea reală | O copie nerestaurată nu este o copie | Procedura din RUNBOOK, o dată, pe serverul real | infra |
| **P0-02** | Secrete generate pentru instalare | Cheia implicită = oricine își semnează un token | `SECRET_KEY`, `DRIVE_TOKEN_KEY`, `CRON_SECRET` | infra |
| **P0-03** | Primul administrator | Fără el nu se poate intra; cu parolă slabă, nu are rost restul | `create-admin` (acum cu politica completă) | proprietar |
| **P1-01** | **Monitor extern pornit** | Aplicația expune semnalele, dar **nu sună pe nimeni** | Un serviciu pe `/health/ready` și `/health/workers` | infra |
| **P1-02** | Semnătura contabilului | Documentația nu are voie să pretindă validare fiscală | [ACCOUNTING_UAT_CHECKLIST.md](ACCOUNTING_UAT_CHECKLIST.md) | cabinet |
| **P1-03** | Datele de expirare în calendar | `MS_CLIENT_SECRET` este cea mai frecventă cauză de „nu mai vin documentele" | [PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md) | infra |
| **P1-04** | Prima rulare a fiecărei integrări | Protocoalele externe nu au fost atinse | Cu **un singur client**, urmărită | proprietar |
| **P2-01** | SAGA | Formatul nu este public | Un fișier real exportat din SAGA | cabinet |
| **P2-02** | Retenția | Nu există job; ce se șterge este o decizie a cabinetului | Decizie, apoi implementare | cabinet |
| **P3-01** | Paginare la tranzacții | Are plafon cu refuz explicit; extrasele reale au sute de rânduri | Doar dacă un cabinet trece de o mie | — |
| **P3-02** | Zero-downtime | Migrările rulează cu workerul oprit | Migrări compatibile în ambele sensuri, dacă devine necesar | — |

**Niciun P0 sau P1 nu este un defect al codului.** Toate sunt acțiuni de
instalare sau confirmări umane.

---

## Cele două concluzii

### A. APLICAȚIA

**GATA.** Nu există niciun defect cunoscut de securitate, izolare, integritate a
datelor, corectitudine contabilă mecanică, copie/restaurare sau pornire.

### B. INTEGRĂRILE

**NEVERIFICATE.** Niciuna nu a fost rulată împotriva serviciului real, fiindcă nu
există credențiale. Codul, tratarea erorilor și izolarea sunt verificate pe
dubluri — ceea ce **nu** este același lucru și nu se raportează ca atare.

```text
PostgreSQL              — VERIFICAT RULÂND
Stocare (disc)          — VERIFICAT RULÂND
Stocare (S3)            — MOCK VERIFIED
Microsoft Graph         — NOT VERIFIED — credențiale
IMAP                    — NOT VERIFIED — credențiale
SMTP                    — NOT VERIFIED — credențiale
ANAF / SPV              — NOT VERIFIED — certificat calificat
Anthropic (extragere)   — NOT VERIFIED — credențiale
Anthropic (asistent)    — NOT VERIFIED — credențiale
WhatsApp                — NEIMPLEMENTAT (deliberat)
SAGA                    — NEIMPLEMENTAT — lipsește formatul
Monitorizare externă    — DE CONFIGURAT
```

---

# DECIZIA DE RELEASE

## RELEASE READY WITH OPERATIONAL WARNINGS

Aplicația poate fi lansată. Avertismentele sunt **operaționale**, nu tehnice:
trei acțiuni de instalare (P0), un monitor de pornit, o semnătură de contabil, și
integrări care se vor verifica la prima rulare reală.

Nu este `RELEASE READY` fără rezerve pentru că trei lucruri depind de altcineva
decât de cod: copia restaurată pe serverul real, monitorul extern pornit, și
confirmarea contabilului. Fără ele, aplicația funcționează — dar prima problemă
serioasă s-ar descoperi mai târziu decât trebuie.

Nu este `RELEASE BLOCKED` pentru că nu există niciun defect de securitate, de
izolare, de corupere a datelor, de arhivă, de recuperare sau de pornire.
