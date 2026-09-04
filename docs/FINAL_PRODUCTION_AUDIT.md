# Audit de pregătire pentru producție

**Data:** 3 septembrie 2026 · **Versiune auditată:** `5920bde` (M10), plus
reparațiile descrise aici · **Metodă:** inspecție, apoi rulare — server real,
PostgreSQL real, browser real.

---

## Rezumat

**Verdict: PREGĂTIT, CU REZERVE.**

Aplicația poate fi livrată unui cabinet real după cele patru lucruri din secțiunea
*Ce trebuie făcut înainte de livrare*. Niciunul nu este cod: sunt înregistrarea
aplicației la Microsoft, două variabile de configurare și decizia despre OCR-ul
pentru documente scanate.

Am găsit **treisprezece probleme reale**, dintre care opt ar fi afectat un cabinet
în prima săptămână. Una l-ar fi oprit din prima zi — nu exista niciun mod de a
adăuga un client — și una i-ar fi stricat cifrele fără ca nimic să pară în neregulă:
o factură de 1190 de lei era citită ca 119.

Toate sunt rezolvate, fiecare cu un test care cade fără reparație. Niciuna nu
fusese prinsă de cele 948 de teste existente, pentru că fiecare trăia exact acolo
unde testele nu se uitau: în concurență, în configurarea de build, în ce se
întâmplă când nu există cron, într-un ecran pe care niciun test nu îl deschidea,
sau — cea mai instructivă — într-un caz de intrare pe care toată suita îl ocolea
din întâmplare.

### Cifre

| | Înainte | După |
|---|---|---|
| Teste backend | 948 | 1004 |
| Teste frontend | 113 | 117 |
| Teste end-to-end | 22 | 26 |
| Defecte deschise găsite de audit | — | 0 |
| Dependențe frontend nefolosite | 5 | 0 |
| Avertismente de lint | 2 | 0 |
| Pachet de producție (gzip) | 142 KB | 135 KB |
| Rute cerute de frontend și inexistente în backend | 2 | 0 |

### Ce s-a verificat rulând, nu citind

Un server pornit pe o bază proprie, cu **două organizații** și **20.000 de
documente** semănate, interogat direct: autentificare, RBAC pe toate rolurile,
IDOR încrucișat pe opt rute, metacaractere de căutare, marginile paginării,
încărcări cu nume ostile, tipuri false, fișiere de 150 MB, patru încărcări
simultane ale acelorași octeți, patru aprobări simultane pe același document,
antete HTTP, CORS, rotația sesiunii, planurile de execuție ale interogărilor.

Și, separat, o **instalare complet nouă pe drumul de producție** — bază goală,
migrări, `sync-roles`, `create-admin`, `add-client`, fără `seed-dev` — dusă până la
capăt: încărcare, extracție, verificare, aprobare, arhivare cu nume standardizat,
descărcare, jurnal de audit, deconectare. Acolo a apărut A-11.

---

## Defecte găsite

**MAJOR** = afectează corectitudinea datelor sau fluxul principal ·
**MINOR** = real, dar limitat.

---

### A-01 · MAJOR · Preluarea automată nu se întâmpla niciodată pe un server propriu

**Unde:** `backend/app/worker.py`

Sincronizarea cu OneDrive și cu cutia poștală era pornită dintr-un singur loc:
`/api/v1/internal/run-queue`, ruta pe care o bate cronul de pe Vercel. Workerul —
procesul pe care îl pornește `docker compose`, adică exact varianta descrisă în
documentația de deploy — executa coada de procesare și **nimic altceva**.

Consecința: un cabinet instalat pe serverul propriu conecta contul Microsoft,
alegea dosarele clienților, vedea în interfață o legătură activă și dosare
urmărite, și nu primea niciun document. Nimic nu se plângea. Preluarea automată
este exact ce a cerut clientul.

**Cauză:** funcționalitatea a fost construită pentru mediul în care se făcea
deploy-ul atunci — Vercel, fără proces continuu — și nu a fost legată și de
celălalt drum de rulare.

**Reparat:** workerul întreabă sursele externe la pornire și apoi la fiecare două
minute; `--once` face același lucru, în aceeași ordine ca bucla. Un cabinet căruia
i-a expirat tokenul nu oprește workerul.

**Test:** `tests/test_worker.py::test_worker_asks_the_external_sources_at_startup`.
Verificat: scoțând apelul, testul cade.

---

### A-02 · MAJOR · Detecția duplicatelor pierdea cursa

**Unde:** `backend/app/services/document_upload.py`

Căutarea duplicatului era un `SELECT` urmat de un `INSERT`, fără nimic între ele.
Sub concurență asta nu decide nimic: două tranzacții se caută una pe alta înainte
ca vreuna să fi comis, nu găsesc nimic, și intră amândouă ca documente noi.

**Măsurat pe server real**, patru încărcări simultane ale acelorași octeți:

```
tur 1: ['RECEIVED', 'RECEIVED', 'DUPLICATE', 'DUPLICATE']  ->  2 din 3 marcate
tur 2: ['RECEIVED', 'RECEIVED', 'RECEIVED', 'RECEIVED']    ->  0 din 3 marcate
tur 3: ['RECEIVED', 'RECEIVED', 'RECEIVED', 'RECEIVED']    ->  0 din 3 marcate
```

Nu este un caz teoretic. Aceeași factură ajunge la cabinet pe mai multe drumuri
deodată — dosarul din OneDrive, atașamentul de pe email, omul care o încarcă de
mână — iar sincronizarea și uploadul rulează în procese diferite.

**Reparat:** o încuietoare consultativă Postgres pe `(organizație, sha256)`, luată
înainte de căutare și eliberată la commit — adică exact după ce rândul devine
vizibil pentru următorul. Fișiere diferite nu se așteaptă niciodată: cheia le
separă. După reparație, aceeași probă dă `3 din 3` în toate rulările.

Odată cu ea, sincronizarea cu Microsoft ia o încuietoare per organizație: o bătaie
de cron peste alta nu mai citește aceleași dosare de două ori.

**Test:** `tests/test_upload_concurrency.py` — patru fire, sesiuni și conexiuni
proprii. Cade de fiecare dată fără încuietoare (verificat de trei ori), trece cu ea.

---

### A-03 · MAJOR · Două ecrane livrate cereau rute care nu există

**Unde:** `frontend/src/features/communication/`, `frontend/src/features/clients/`

`Comunicare → Mesaje` cerea `GET /messages`. Fila `Comunicare` din fișa clientului
cerea `GET /clients/{id}/messages`. Backendul nu are niciuna dintre ele și nu are
niciun model de mesaje.

În modul simulat ambele mergeau perfect — backendul din browser le răspundea. În
modul real, prima arăta o eroare, iar a doua **rămânea goală fără să spună nimic**:
componenta trata doar `isLoading`, nu și eroarea.

**Cauză:** ecranele au fost construite pe backendul simulat, iar echivalentul real
nu a fost scris niciodată. Nimic nu compara cele două liste de rute.

**Reparat:** ecranele spun acum ce există cu adevărat și trimit acolo — documentele
primite de la client, și configurarea surselor. **Nu am inventat un model de
mesaje** ca să umplu un ecran: forma cerută de interfață avea câmpuri
(`preview`, `attachmentCount`, mesaje trimise) pe care sistemul nu le are, iar a le
fabrica din `document_intakes` ar fi însemnat exact ce acest sistem nu face. Codul
rămas fără apelant — rutele simulate, datele sintetice, tipul — a fost șters.

**Test:** `e2e/pages.spec.ts` deschide **fiecare** ecran din navigație și cade dacă
vreunul cere ceva ce serverul nu are, sau lasă o eroare în consolă. Verificat:
schimbând o rută într-una inexistentă, testul o prinde.

---

### A-04 · MAJOR · Un build de producție fără o variabilă livra aplicația falsă

**Unde:** `frontend/src/api/client.ts`

`VITE_API_MODE` alegea între API-ul real și backendul simulat din browser.
Implicit, în **orice** build, era cel simulat.

Un `npm run build` fără variabila aceea — uitată în panoul de deploy — livra
aplicația completă, arătoasă și funcțională, rulând pe date inventate: clienți
inventați, documente inventate, și o autentificare care acceptă orice parolă.
Nimic din interfață nu semnala nimic. Un cabinet ar fi putut lucra ore întregi
într-o aplicație care nu scrie nicăieri.

Backendul refuză deja să pornească în producție cu providerul care inventează date
(`OCR_PROVIDER=mock`). Frontendul nu avea protecția echivalentă.

**Reparat:** într-un build de producție alegerea trebuie să fie explicită. Fără ea,
aplicația nu pornește și afișează motivul — nu un ecran alb, care ar fi la fel de
mut ca problema pe care o semnalează. În development implicitul rămâne `mock`.

În plus, backendul simulat se încarcă acum dinamic: nu mai face parte din pachetul
de producție (−27 KB, −7 KB comprimat) și nu se poate executa fără să fie cerut.

**Test:** `src/api/client.test.ts` — patru cazuri, inclusiv o valoare scrisă greșit
(`"HTTP"`), care nu are voie să cadă tăcut înapoi pe date inventate.

---

### A-05 · MAJOR · CI ar fi trecut verde cu suita sărită

**Unde:** `backend/tests/conftest.py`

Testele care au nevoie de PostgreSQL **sar** când baza nu răspunde — corect pe
laptop: un eșec de infrastructură nu spune nimic despre cod. Dar aceeași regulă se
aplica și în CI, unde aproape toată suita cere baza. Un serviciu `postgres` care nu
pornește ar fi produs o rulare **verde, cu peste 900 de teste sărite**.

**Reparat:** în CI (`$CI`), o bază inaccesibilă oprește rularea cu un mesaj
explicit. Pe laptop, comportamentul rămâne neschimbat.

**Verificat:** cu `CI=1` și o adresă de bază greșită, `pytest` se oprește la
încărcarea `conftest`-ului.

---

### A-06 · MAJOR · Trei indexuri de căutare erau moarte

**Unde:** `backend/app/repositories/document.py`, `client.py`

Migrările creează indexuri GIN trigram pe `app_unaccent(lower(coloană))`.
Interogarea compara însă `app_unaccent(lower(coalesce(coloană, '')))`. Expresiile
nu se potrivesc, deci Postgres nu putea folosi niciun index și scana tot tabelul.

**Măsurat pe 20.000 de documente**, un singur predicat:

```
cu coalesce (ce făcea codul)        Seq Scan             44,7 ms
fără coalesce (ce indexa indexul)   Bitmap Index Scan     6,9 ms
```

Căutarea completă din interfață: **931 ms → 346 ms**.

`coalesce` nu era necesar: `NULL LIKE '%x%'` este `NULL`, adică nu adevărat — exact
ce însemna și `'' LIKE '%x%'`. Rezultatele sunt identice, verificat pe zece
interogări incluzând diacritice și metacaractere.

**Rest cunoscut:** din cele 346 ms rămase, 140 sunt `COUNT(*)` — totalul exact
peste un `OR` care traversează tabela clienților. Pagina propriu-zisă se ia în
2 ms. Vezi *Riscuri rămase*.

---

### A-07 · MINOR · Modelele și baza de date spuneau lucruri diferite

**Unde:** `backend/app/models/`

Trei constrângeri `CHECK` scrise de mână rămăseseră în urma migrărilor:

| Constrângere | Modelul spunea | Baza de date spunea |
|---|---|---|
| `documents.source` | 4 valori | 5 (`ONEDRIVE`) |
| `document_intakes.source` | 4 valori | 5 (`ONEDRIVE`) |
| `document_processing_jobs.status` | 4 valori | 5 (`SKIPPED`) |

Testul de derivă model↔migrare trecea, pentru că `compare_metadata` din Alembic
**nu compară corpul constrângerilor CHECK**. Nimic nu s-a plâns timp de două
milestone-uri.

**Reparat:** constrângerile se derivă acum din enum (`enum_check`), deci nu mai pot
diverge prin construcție. `document_processing_jobs.status` a primit enumul care îi
lipsea.

**Test:** `tests/test_migrations.py` compară, pentru fiecare coloană cu enum,
mulțimea de valori din constrângerea **reală** din baza migrată cu enumul, și
verifică separat că modelul chiar derivă din el. Cele două verificări închid
lanțul: model == enum == bază. Verificat: repunând lista veche, testul cade.

---

### A-08 · MINOR · Niciun antet de securitate pe răspunsurile API

**Unde:** `backend/app/core/middleware.py`

Antetele existau în două locuri: pe fișierele servite, și în `vercel.json`. O
instalare pe serverul cabinetului nu avea niciunul. Măsurat pe un server pornit, pe
un răspuns JSON obișnuit: `X-Content-Type-Options`, `Referrer-Policy`,
`Content-Security-Policy`, `X-Frame-Options`, `Permissions-Policy` — toate lipsă.

**Reparat:** `SecurityHeadersMiddleware` le pune pe orice răspuns, inclusiv pe cele
de eroare, care nu trec prin nicio rută. `Strict-Transport-Security` doar în afara
development-ului — trimis pe `http://localhost`, ar bloca munca luni de zile.

Antetele nu suprascriu ce există deja: previzualizarea documentelor își păstrează
politica ei, mai strictă (`sandbox`), și încadrarea de pe aceeași origine, fără de
care ecranul de verificare ar fi rămas gol.

**Test:** `tests/test_security_headers.py`, 12 cazuri.

---

### A-09 · MINOR · Un ecran de demonstrație, public, în producție

**Unde:** `frontend/src/App.tsx`, `src/pages/demo.tsx`

Ruta `/demo` era **în afara** autentificării și randa un panou de referință din
registry, cu date fixe. Nu expunea date reale, dar era o pagină de demonstrație
livrată în producție, accesibilă oricui.

**Reparat:** ruta și componenta (477 de linii) au fost scoase. Odată cu ele au
rămas fără apelant cele patru primitive shadcn și cinci dependențe
(`react-hook-form`, `zod`, `@hookform/resolvers`, `class-variance-authority`,
`radix-ui`) — verificat prin căutare în tot `src/`, apoi scoase. Cele două
avertismente de lint ale proiectului veneau de acolo și au dispărut.
`components.json` rămâne: `npx shadcn add <componentă>` le aduce înapoi când chiar
sunt necesare.

---

### A-10 · MAJOR · Nu exista niciun mod de a adăuga un client în producție

**Unde:** suprafața API și interfața, amândouă

CRM-ul este de citire, deliberat: nu există rute de scriere pentru clienți, iar
interfața nu oferă niciun formular — drumul de scriere al aplicației sunt
documentele. Asta este o decizie de scop, nu un defect.

Defectul este ce urmează din ea: `seed-dev` refuză să ruleze în producție (și bine
face — datele lui sunt inventate, parolele publice), deci un cabinet nou nu putea
adăuga **niciun** client. Fără clienți nu se poate lega niciun dosar din OneDrive,
niciun email nu poate fi atribuit, și nu se poate deschide nicio perioadă. Singurul
drum rămas era SQL direct în baza de producție.

**Reparat, cât trebuie:** o comandă, `add-client`, în aceeași familie cu
`create-admin` — care există exact din același motiv, pentru primul utilizator.
Verifică unicitatea CUI-ului printre clienții neșterși (aceeași regulă ca indexul
parțial din migrare, dar cu un mesaj în loc de o eroare de bază), refuză să
ghicească atunci când baza are mai multe cabinete, și creează opțional contactul —
adresa după care un atașament primit ajunge la clientul potrivit.

La momentul auditului nu am construit și ecranul: un modul de administrare a
clienților este o funcționalitate nouă, nu o reparație, iar un audit nu este locul
unde se decide că apare.

**A fost construit imediat după**, ca prim element din lista de mai jos:
`POST/PATCH /clients`, `POST/PATCH /clients/{id}/contacts`, permisiunea
`clients:write` — care exista în hartă și nu era folosită de nicio rută —, formulare
în „Clienți" și în fișa clientului, și aceleași două verificări în backendul
simulat. Comanda `add-client` rămâne pentru instalarea de la zero, când încă nu
există niciun cont prin care să te autentifici.

**Test:** `tests/test_cli.py`, 8 cazuri — inclusiv CUI duplicat, bază cu două
cabinete, și client fără email.

---

### A-11 · MAJOR · O factură de 1190 de lei era citită ca 119

**Unde:** `backend/app/domain/romanian_documents.py`

Tiparul care găsește o sumă în textul unei facturi:

```
(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)
```

Prima ramură descrie o sumă cu separator de mii — `1.190,00` — dar grupurile de
mii sunt **opționale** (`*`). Pe `1190,00`, ea se potrivește cu primele trei
cifre și se oprește: `119`. Alternativa a doua, care ar fi citit numărul întreg,
nu mai este încercată, pentru că prima a reușit.

Efectul: **orice sumă de peste 999 scrisă fără separator de mii este trunchiată
la primele trei cifre.** O factură de 1190 de lei intră în contabilitate ca 119.
Tăcut, și perfect plauzibil — nimic nu arată ca o eroare.

Amândouă convențiile apar pe facturi românești reale; care dintre ele iese la
tipar ține de programul care a emis-o.

**De ce nu a prins-o nimic.** Toate sumele din întreaga suită — teste unitare și
end-to-end — aveau ori separator de mii (`1.234,56`, `1.190,00`), ori mai puțin
de patru cifre (`12,50`, `250,00`, `99,00`). Adică exact cele două forme pe care
tiparul le citea corect. Cazul din mijloc nu exista nicăieri.

**Găsit** la proba de fum pe o instalare complet nouă, urcând o factură cu
`Total de plata: 1190,00 lei` și citind ce a ajuns în baza de date.

**Reparat:** prima ramură cere acum **cel puțin un** grup de mii (`+`), deci un
număr fără separator cade pe a doua ramură și se citește întreg. Verificat pe
douăsprezece scrieri: `1190,00`, `1.190,00`, `1 190,00`, `1190.00`, `1190`,
`119,00`, `1.234.567,89`, `12,50`, `100000`, `2.000`, `2.00`, `1234.56` — toate
corecte.

**Test:** `tests/test_romanian_documents.py` — cele douăsprezece scrieri, plus
TVA-ul și baza impozabilă, care foloseau același tipar. Verificat: repunând `*`,
cad.

---

### A-12 · MAJOR · O protecție care exista doar în configurare

**Unde:** `backend/app/core/config.py`, `.env.example`

`RATE_LIMIT_PER_MINUTE=120` stătea în configurare și în exemplul de configurare de
la primul commit. **Nu îl citea niciun modul.** O variabilă care promite o
protecție inexistentă este mai rea decât absența ei: cine o vede acolo crede că
autentificarea este limitată.

Singura barieră reală era costul Argon2id — măsurat pe un server pornit, ~200 ms
pe încercare. Asta mărginește un atac la câteva mii de parole pe oră, ceea ce
pentru o listă de parole comune nu este de ajuns.

**Reparat:** limitarea există acum, cu **două** contoare, pentru că sunt două
atacuri diferite:

| Contor | Prag implicit | Ce oprește |
|---|---|---|
| per (adresă, cont) | 10 eșecuri/minut | multe parole încercate pe un cont |
| per adresă | 60 eșecuri/minut | o parolă încercată pe multe conturi |

Cheia include adresa, nu doar contul: un contor legat numai de cont ar fi lăsat pe
oricine să blocheze de la distanță autentificarea unui contabil — protecția ar fi
devenit un atac. Răspunsul este `429` cu `Retry-After`, ca browserul să nu ghicească
cât să aștepte.

**Prima variantă a reparației era greșită, iar suita end-to-end a găsit-o imediat.**
Număra toate încercările, nu doar eșecurile. Consecința: al unsprezecelea login cu
parola **corectă** dintr-un minut era refuzat. Două teste E2E au căzut — al 11-lea și
al 12-lea din suită, exact acolo unde contorul se umplea — și au căzut departe de
cauză, în mijlocul unui flux de documente.

Numărarea reușitelor nu apăra nimic: cine ghicește parola este oricum înăuntru.
Contorul numără acum eșecuri, `blocked` și `record` sunt operații separate — una
înaintea încercării, cealaltă după, și numai dacă a eșuat.

**Ce nu acoperă**, scris atât în cod cât și în `.env.example`: contorul stă în
proces. Două procese de API înseamnă două contoare, iar pe o platformă care
pornește un proces per cerere nu limitează nimic. Este protecția potrivită pentru
instalarea din documentație — un container de API — și trebuie dublată la marginea
rețelei acolo unde există un proxy.

**Test:** `tests/test_rate_limit.py`, 10 cazuri: pragul exact, chei independente,
fereastra care se redeschide, `Retry-After`, un prag de zero care înseamnă „fără
limită" și nu „blochează tot", cele două contoare prin HTTP, și — cazul care a
căzut în E2E — o parolă corectă repetată de mai multe ori decât pragul, care nu
are voie să fie refuzată.

---

### A-13 · MINOR · Pe un telefon, fiecare pagină ieșea din ecran

**Unde:** `frontend/src/components/layout/app-shell.tsx`

Bara laterală deschisă are 256px și rămânea deschisă la orice lățime. Măsurat pe
un ecran de 390px: **fiecare pagină depășea pe orizontală cu 50px**, iar titlul
din antet se strângea la lățime zero — adică dispărea. Tableta (820px) și
desktopul erau în regulă.

Niciun test nu se uita vreodată la altă lățime decât cea implicită.

**Reparat:** bara pornește închisă sub 900px și se închide singură dacă fereastra
se micșorează sub prag. Invers nu se forțează: cine a închis-o pe un ecran lat a
închis-o pentru că a vrut.

**Test:** `e2e/accessibility.spec.ts` măsoară depășirea pe orizontală și lățimea
titlului pe trei lățimi × șapte ecrane. Același test verifică și că fiecare buton,
link și câmp are un nume accesibil — acolo nu era nimic de reparat.

> Prima versiune a verificării de accesibilitate a raportat opt câmpuri „fără
> etichetă". Erau toate corecte: verificarea nu cunoștea eticheta **implicită** —
> câmpul care stă înăuntrul unui `<label>`. A fost reparată verificarea, nu
> aplicația.

---

## Ce s-a verificat și era în regulă

Enumerat pentru că absența unei probleme este tot un rezultat.

| Zonă | Cum a fost verificat | Rezultat |
|---|---|---|
| **Izolarea între organizații** | două organizații reale, opt rute încercate încrucișat (detaliu, previzualizare, descărcare, aprobare, respingere, modificare, reprocesare, duplicat) | `404` peste tot; acțiunea în masă raportează „inexistent", nu execută |
| **RBAC** | fiecare rol pe rutele de administrare | `403` unde trebuie; harta din backend este sursa de adevăr, iar meniul nu mai oferă uși încuiate |
| **Autentificare** | parolă greșită, email inexistent, cont dezactivat | răspuns identic, `401`, fără scurgere de informație |
| **Sesiuni** | rotația refresh tokenului, refolosirea unuia vechi, refresh trimis ca access | vechi refolosit → `401`; refresh ca access → `401`; logout invalidează pe server |
| **Metacaractere în căutare** | `%`, `_`, `'`, `"`, `\`, `../`, `' OR 1=1 --`, 500 de caractere | escapate corect: `%` caută procent, nu tot; textul prea lung → `422` |
| **Diacritice** | `Serban` ↔ `Șerbănescu`, `DISTRIBUTIE` ↔ `Distribuție`, în ambele direcții | găsește în toate cazurile |
| **Paginare** | pagina 0, negativă, `pageSize` 0, negativ, 100.000, pagina 999999 | `422` pentru valori invalide, listă goală pentru pagină peste sfârșit |
| **Nume de fișier ostile** | `../../../etc/passwd.pdf`, `..\..\windows\`, `CON.pdf`, `NUL.pdf`, byte nul, `<script>`, 400 de caractere | păstrate ca **text**, niciodată folosite ca traseu; cheia de stocare se derivă din id-ul documentului; `Content-Disposition` întoarce doar ultimul segment, curățat |
| **Tipuri false** | executabil redenumit `.pdf`, PDF corupt, fișier gol, `.zip` declarat, PDF declarat `image/png` | tipul se ia din primii octeți, nu din declarație; executabilul respins |
| **Fișiere mari** | 30 MB și 150 MB, cu limita la 25 | respinse cu motiv, în timpul citirii |
| **Aprobări simultane** | patru cereri deodată pe același document | exact una poate reuși; restul `409` |
| **Previzualizare / descărcare** | antetele răspunsului | `nosniff`, `sandbox`, `no-store`, nume curățat; **niciun token în URL** |
| **CORS** | preflight din trei origini | numai originea configurată trece |
| **Ruta internă** | fără secret, cu secret greșit, cu secret corect | `404`, `404`, `200` — comparație în timp constant |
| **Volum** | 20.000 de documente, 2.000 de clienți | toate ecranele sub 350 ms; răspunsurile mărginite; **niciun text OCR în liste** |
| **Bani** | căutare după `float` în calcule financiare | `Decimal`/`Numeric` peste tot; singura verificare numerică este `subtotal + TVA = total` |
| **Fus orar** | marcajele de timp din API | conștiente de fus (`+03:00`, Europe/București) |
| **Constrângeri în bază** | inventarul `pg_constraint` | 22 de constrângeri `CHECK`, inclusiv `DONE ⇔ completed_at`, „arhivat ⇒ are nume, cale și copie", „duplicat ⇒ are original" |
| **Migrări** | toate cele 11 | fiecare are `downgrade`; niciun `upgrade` nu șterge tabele, coloane sau rânduri |
| **Jurnalul de audit** | suprafața API | numai citire; nicio rută nu modifică sau șterge intrări |
| **Secrete în repo** | căutare în toate fișierele urmărite | niciunul |
| **Dependențe** | `npm audit` | 0 vulnerabilități |
| **Documente scanate** | PDF valid fără strat de text | ajunge la verificare cu câmpuri goale, **fără valori inventate** |
| **Numele furnizorului** | factură cu „Furnizor: X SRL" scris explicit | **nu** se citește, deliberat: pe o factură reală numele stă într-un bloc de adresă, fără etichetă, iar o regulă care l-ar ghici ar prinde la fel de des antetul tipografiei. Operatorul îl completează, iar aprobarea îl cere |
| **Instalarea de la zero** | bază goală → migrări → roluri → `create-admin` → `add-client` → flux complet | trece capăt la capăt; perioada contabilă se deschide singură la primul document |
| **Coerența bază ↔ stocare** | comanda nouă `check-storage`, pe 33 de fișiere reale | se potrivesc; ascunzând un fișier, comanda îl raportează și iese cu cod diferit de zero |

---

## Ce trebuie făcut înainte de livrare

Niciunul nu este cod.

1. **Înregistrarea aplicației în Microsoft Entra ID** — `MS_CLIENT_ID`,
   `MS_CLIENT_SECRET`, `MS_REDIRECT_URI`. Pașii sunt în `docs/DEPLOY.md §6`. Fără
   ele, ecranul „Surse documente" spune că integrarea nu este configurată.
   **Neverificat capăt la capăt: nu există credențiale reale.** Ce s-a verificat
   este interfața, tratarea erorilor, idempotența și fluxul complet pe un client
   fals care implementează același protocol.
2. **`VITE_API_MODE=http`** la build. Fără ea, aplicația refuză acum să pornească
   și spune de ce.
3. **`OCR_PROVIDER=local`** și un `SECRET_KEY` generat. Pornirea în producție le
   verifică singură.
4. **Decizia despre documentele scanate.** Providerul actual citește stratul de
   text al PDF-ului și facturile electronice. O poză de bon nu are text de citit:
   documentul ajunge la verificare cu câmpuri goale — corect, dar înseamnă muncă
   manuală. OCR real înseamnă ori Tesseract local (gratuit, calitate variabilă),
   ori un serviciu în cloud (mai bun, dar documentele pleacă de pe infrastructura
   cabinetului — decizie GDPR).

---

## Riscuri rămase

| Risc | Severitate | Ce se știe |
|---|---|---|
| Corpul cererii de upload este primit **întreg** înainte de a putea fi refuzat | Medie | Măsurat: 150 MB refuzați în 1,3 s, dar transferați integral. Limita trebuie pusă și în proxy (`client_max_body_size`). Documentat în `docs/DEPLOY.md` |
| `COUNT(*)` la căutarea textuală în documente | Mică | 140 ms pe 20.000 de documente; crește liniar. Se rezolvă doar denormalizând numele clientului pe document sau renunțând la totalul exact — niciuna nu merită încă |
| Jurnalul de audit nu este imutabil **la nivel de bază de date** | Mică | Nicio rută nu îl modifică, dar aplicația se conectează cu un utilizator care are drept de `DELETE`. Imutabilitatea reală cere un al doilea rol de bază de date, adică o decizie de infrastructură |
| Permisiunile `documents:delete` și `communication:send` nu au nicio rută | Cosmetic | Există în hartă pentru completitudine; nimic nu le folosește |
| Codul `INTERNAL_ERROR` pe un răspuns `405` | Cosmetic | Eticheta e greșită, comportamentul nu: frontendul decide reîncercarea după status, nu după cod |
| O eroare de teardown, văzută **o singură dată** | Mică | La una dintre rulările complete, ultimul test a raportat `ERROR` (972 trecute, 1 eroare). Nu s-a reprodus în trei rulări complete consecutive și mesajul a fost trunchiat. Ipoteza este o cursă la `DROP DATABASE ... WITH (FORCE)` din teardown-ul fixture-ului de sesiune. Dacă reapare, trebuie rulat cu ieșirea completă salvată — nu tratat ca zgomot |
| Integrările Microsoft, neverificate cu credențiale reale | — | Vezi punctul 1 de mai sus |
| Integrarea ANAF (M11), neverificată cu certificat real | — | Autorizarea cere un certificat digital calificat prezentat de browser; nu există cont de serviciu, iar mediul de test al ANAF îl cere la fel. Se verifică o singură dată, manual, la instalare |

---

## Ce merită construit după livrare

În ordinea valorii pentru cabinet, nu a dificultății.

1. ~~**Ecranul de administrare a clienților.**~~ Construit imediat după audit —
   vezi A-10. Rămâne fără interfață un singur lucru din CRM: etichetele, care au
   propria semantică și propriul ecran.
2. ~~**ANAF SPV — e-Factura.**~~ Construit imediat după ecranul de clienți (M11):
   facturile de intrare apar singure, cu toate trei fișierele — XML, arhiva cu
   sigiliul ANAF, PDF-ul oficial. Vezi [ADR-009](adr/ADR-009-efactura-anaf.md).
   Blocajul rămas nu este tehnic și nu se poate rezolva de aici: cere certificat
   digital înrolat în SPV și **împuternicire de la fiecare client** (formular
   150). Drumul întreg către ANAF rămâne **NOT VERIFIED — EXTERNAL CREDENTIAL
   REQUIRED**.
3. **Remindere automate.** Ecranul „Documente lipsă" știe deja ce nu a venit de la
   fiecare client. Cu conexiunea Microsoft de acum, trimiterea este la un pas
   (`Mail.Send`). Ar închide bucla: sistemul nu doar așteaptă documentele, ci le
   și cere.
4. **Cronologia reală a mesajelor**, pe `document_intakes` — cine a trimis, ce,
   când. Ecranul scos la A-03 se poate întoarce, dar cu datele care există.
5. **WhatsApp.** Mulți clienți trimit poze de bonuri. Infrastructura există
   (`WHATSAPP` este în enum din M1). Cere API-ul de business Meta și, ca să aibă
   sens, OCR real — deci merge împreună cu decizia 4 din secțiunea anterioară.
6. **Google Drive / Dropbox.** Ieftin: protocolul `DriveClient` există, ar fi un al
   doilea `graph.py`. Merită doar dacă există clienți care le folosesc.

---

## Verificare finală

```
backend  1004 teste · ruff · ruff format · mypy --strict     toate curate
frontend  117 teste · oxlint (0 avertismente) · tsc · build  toate curate
e2e        26 teste, într-un browser real, pe build-ul real  toate trec
bază      contacrm_e2e reconstruită de la zero prin migrări la fiecare rulare
```

Suita backend a fost rulată integral de mai multe ori pe parcurs, iar la final
de trei ori consecutiv, curat.

## Documentația

`README.md` și `docs/ARCHITECTURE.md` descriau lucruri care nu mai existau sau nu
existaseră niciodată: coada pe „Celery + Redis" (aleasă a fi un outbox în Postgres
încă din ADR-003), un `docker-compose` cu Redis, directoare `workers/`, `prompts/`
și `integrations/` care nu există, ruta `/demo`, primitivele shadcn, și șapte
tabele de comunicare care nu au fost create niciodată — enumerate lângă cele reale,
fără nicio distincție.

Toate au fost aduse la realitate. Tabelele care rămân doar proiectate sunt acum
într-o secțiune care spune limpede că nu există. Au fost adăugate cele patru tabele
reale pe care documentația nu le cunoștea (`microsoft_connections`,
`drive_folders`, `mail_folders`, `client_expectations`).

Documente noi: `docs/RUNBOOK.md` (operare, copii de siguranță, restaurare,
incidente) și acest raport. Starea repository-ului rămâne în `docs/STATUS.md`.

---

## Lista de control

Bifat = verificat **rulând**, nu citind. Unde scrie altceva, scrie ce anume.

- [x] Autentificare — parolă greșită, email inexistent, cont dezactivat, răspuns identic
- [x] Autorizare și RBAC — fiecare rol pe rutele de administrare
- [x] Izolarea între organizații — două organizații reale, opt rute încrucișate
- [x] IDOR — documente, clienți, contacte, note, perioade, descărcări, previzualizări, acțiuni în masă
- [x] CSRF — cookie `SameSite=Lax`; nicio mutație nu se face prin `GET` de utilizator
- [x] XSS — text ostil salvat brut, servit ca JSON, randat escapat; niciun `dangerouslySetInnerHTML`
- [x] CORS — preflight din trei origini, doar cea configurată trece
- [x] Încărcare de fișiere — tip din octeți, nu din declarație; executabil respins
- [x] Traversare de cale — opt nume ostile, niciunul nu devine traseu
- [x] Previzualizare și descărcare — `sandbox`, `nosniff`, `no-store`, **fără token în URL**
- [x] Ciclul de viață al documentului — mașină de stări cu tranziții explicite, aprobări simultane
- [x] Detecția duplicatelor — inclusiv sub concurență (**reparat**)
- [x] OCR / AI — document fără text nu primește valori inventate; sumele se citesc întregi (**reparat**)
- [x] Joburi de fundal — outbox, `SKIP LOCKED`, idempotență, recuperare
- [x] Reîncercare — limită configurată, stare finală, buton care dispare la epuizare
- [x] Idempotență — cheie unică pe job; intake unic pe `(sursă, mesaj, atașament)`
- [x] Migrări — 11, toate reversibile, niciun `upgrade` distructiv
- [x] Constrângeri de bază — 22 `CHECK`, derivate acum din enum (**reparat**)
- [x] Tranzacții — fișier scris înaintea rândului; curățare la eșec
- [x] Căutare — metacaractere escapate, diacritice în ambele direcții, indexuri folosite (**reparat**)
- [x] Paginare — margini și valori invalide
- [x] Performanță — 20.000 de documente, planuri de execuție citite
- [x] Logare — fără parole, fără tokenuri, fără text OCR; `request_id` peste tot
- [x] Health — `/live`, `/ready` (503 fără bază), `/info` fără secrete
- [x] Copii de siguranță — procedură scrisă, cu ordinea corectă (**nou**)
- [x] Restaurare — procedură scrisă, cu pas de verificare executabil (**nou**)
- [x] Docker — utilizator neprivilegiat, healthcheck, multi-stage
- [x] Dependențe — `npm audit` curat; cinci nefolosite scoase
- [x] Secrete — niciunul în repo
- [x] CI/CD — nu mai poate trece verde fără bază de date (**reparat**)
- [x] Frontend — fiecare ecran deschis, fără cereri eșuate, fără erori în consolă (**nou**)
- [x] End-to-end — 26 de teste într-un browser real, pe build-ul real
- [x] Accesibilitate — nume accesibile pe toate elementele interactive; layout pe trei lățimi (**nou**)
- [x] Documentație — adusă la realitate; ce nu există este marcat ca inexistent
- [x] Configurare de producție — `assert_production_ready()`, plus refuzul frontendului (**reparat**)
- [ ] **Antete de securitate peste HTTPS** — `Strict-Transport-Security` se trimite doar în afara
      development-ului, deci nu a putut fi observat local. Codul îl pune; efectul se vede la
      primul deploy
- [ ] **Integrările Microsoft, capăt la capăt** — NEVERIFICAT: nu există credențiale. Verificate:
      interfața, tratarea erorilor, idempotența, fluxul complet pe un client fals care implementează
      același protocol
- [x] Rate limiting pe autentificare — două contoare, per (adresă, cont) și per adresă (**reparat**)
- [ ] **Restaurare exersată pe date reale** — procedura este scrisă și pasul de verificare
      funcționează pe date sintetice; un exercițiu pe o copie reală rămâne de făcut de cabinet
