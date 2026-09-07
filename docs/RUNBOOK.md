# Runbook

Ce faci când sistemul rulează în producție și ceva trebuie verificat, salvat sau
readus la viață. Documentul de deploy (`docs/DEPLOY.md`) spune cum se pune în
funcțiune; acesta spune cum se ține în funcțiune.

---

## Ce rulează

| Proces | Ce face | Ce se întâmplă dacă lipsește |
| --- | --- | --- |
| API (`uvicorn app.main:app`) | răspunde la cereri, primește încărcări | aplicația nu răspunde deloc — se vede imediat |
| Worker (`python -m app.worker`) | execută coada de procesare **și** întreabă OneDrive/emailul la 2 minute | documentele rămân în `RECEIVED` și nu mai sosește nimic din surse — **nu se vede imediat** |
| Postgres | baza de date | `/health/ready` răspunde 503 |
| Stocarea | fișierele | rândurile există, fișierele nu se pot descărca |

Pe Vercel nu există worker: îi ține locul cronul din `vercel.json`, care bate
`/api/v1/internal/run-queue` la 5 minute. Oriunde altundeva, workerul este
obligatoriu — fără el preluarea automată nu se întâmplă.

---

## Verificări rapide

```bash
curl -s https://<domeniu>/health/live     # procesul trăiește
curl -s https://<domeniu>/health/ready    # și baza de date răspunde
```

`/health/ready` întoarce 503 când baza nu răspunde: exact ce trebuie să vadă un
orchestrator ca să nu trimită trafic într-un proces care nu poate lucra.

Că workerul trăiește **nu** se vede dintr-un endpoint. Se vede din două locuri:

- panoul principal semnalează cererile rămase `PENDING`/`RUNNING` mai vechi decât
  pragul — dacă numărul crește, workerul nu mai consumă coada;
- logul lui scrie `worker_started`, apoi `drive_sync_run` la fiecare tur.

---

## Copii de siguranță

Sistemul ține date în **două** locuri care nu împart o tranzacție: baza de date și
stocarea documentelor. O copie a bazei singură nu poate reface nimic — rândurile
ar trimite către fișiere care nu există.

### Ordinea contează: întâi baza, apoi fișierele

Un document este scris **întâi** în stocare și abia apoi comis în baza de date.
La fel arhivarea: copia se scrie, apoi rândul o notează. Nimic nu suprascrie și
nimic nu șterge fișiere în funcționare normală.

Din asta rezultă ordinea corectă a copiei:

1. **baza de date**, la momentul T1;
2. **stocarea**, la un moment T2 după T1.

Așa, orice rând din copia bazei are fișierul lui în copia stocării — fișierul a
fost scris înaintea rândului, deci înainte de T1. În stocare rămân în plus câteva
fișiere ale documentelor apărute între T1 și T2, pe care baza restaurată nu le
cunoaște: sunt inofensive.

Ordinea inversă produce exact problema pe care nu o vrei: o bază care cunoaște
documente ale căror fișiere lipsesc din copie.

```bash
# 1. baza de date
pg_dump --format=custom --no-owner "$DATABASE_URL" > contacrm-$(date +%F).dump

# 2. stocarea, după ce dump-ul s-a terminat
rsync -a --delete /var/lib/contacrm/storage/ /backup/storage-$(date +%F)/
```

Pentru S3, pasul 2 este versionarea bucket-ului sau o replicare — cu aceeași
regulă de ordine.

### Cât se păstrează

Documentele contabile se păstrează 10 ani (vezi `RETENTION_DOCUMENTS_YEARS`).
O copie săptămânală păstrată un an și una lunară păstrată zece este minimul
rezonabil. Copia trebuie să stea pe alt sistem decât cel care rulează aplicația.

---

## Restaurare

```bash
# 1. baza
createdb contacrm_restaurat
pg_restore --no-owner --dbname=contacrm_restaurat contacrm-2026-09-03.dump

# 2. fișierele
rsync -a /backup/storage-2026-09-03/ /var/lib/contacrm/storage/

# 3. migrările, dacă versiunea aplicației este mai nouă decât copia
DATABASE_URL=... uv run alembic upgrade head

# 4. VERIFICAREA — pasul care nu se sare
DATABASE_URL=... uv run python -m app.cli check-storage
```

`check-storage` parcurge fiecare document nefiind șters și verifică dacă fișierul
lui — originalul, plus copia din arhivă dacă a fost arhivat — există și are
dimensiunea din baza de date. Nu scrie nimic. Iese cu cod diferit de zero dacă a
găsit ceva, deci poate sta într-un script.

O restaurare **nu** este terminată până când comanda asta nu trece. Este singurul
lucru care spune dacă cele două copii sunt din același moment.

### Ce mai trebuie verificat după restaurare

- autentificarea (`SECRET_KEY` neschimbat, altfel toate sesiunile pică — ceea ce
  este acceptabil, dar trebuie știut);
- `DRIVE_TOKEN_KEY` neschimbat, altfel legăturile cu OneDrive nu se mai pot
  decripta și fiecare cabinet trebuie să reconecteze contul Microsoft;
- un document deschis în interfață, previzualizat și descărcat.

---

## Situații

### A venit un coleg nou / a plecat unul

*Administrare → Utilizatori → **Coleg nou***. Parola o alegi tu și i-o spui
direct: aplicația trimite mesaje clienților, dar niciodată o parolă, deci nu
pleacă nicio invitație. Minimum 12 caractere, la fel ca la `create-admin`.

Când pleacă cineva: **Dezactivează** pe rândul lui. Nu există ștergere, și e
intenționat — numele lui apare în jurnalul de audit ca autor al unor acțiuni
contabile, iar ștergerea ar rupe urma. Un cont dezactivat nu se mai poate
autentifica.

Dacă un coleg și-a uitat parola: **Resetează parola**, tot de pe rândul lui.
Jurnalul reține cine a resetat cui — este singurul moment în care cineva capătă
acces la contul altcuiva — dar nu reține nicio parolă.

**Pe tine nu te poți dezactiva și nu îți poți schimba rolul.** Un cabinet cu un
singur administrator care greșește acolo rămâne afară din propria aplicație, iar
remediul ar fi un terminal și un SQL. Roagă alt administrator.

### Cabinetul abia a început: cum intră cei două sute de clienți

`CRM → Clienți → Importă`. Fișierul poate fi orice CSV salvat din Excel — cu `;`
sau cu `,`, cu diacritice, în codificarea veche. Singura coloană obligatorie este
denumirea; antetul se recunoaște și scris altfel („Nume", „CIF", „Reg com").
Modelul se descarcă din același ecran.

**Se citește întâi, se scrie a doua oară.** Primul pas nu atinge nimic și arată
ce s-ar întâmpla, rând cu rând. Abia butonul „Importă N" scrie.

Ce nu face: **nu suprascrie** un client care există deja (potrivirea se face pe
CUI), deci același fișier importat de două ori nu dublează pe nimeni. Un CUI care
nu trece verificarea cifrei de control intră totuși, cu o notă — sunt firme
străine și PFA-uri care nu trec.

Adaugă coloanele de email și telefon din prima: fără adresă, clientul nu poate
primi nici solicitarea de documente, nici reminderul, iar asta se descoperă abia
la sfârșitul primei luni.

### A venit un client nou

Din interfață: **Clienți → Client nou**. Salvarea duce direct pe fișa lui, unde
pasul următor este **Contacte → Contact nou**.

**Emailul contactului contează cel mai mult**: după el ajunge un atașament primit
la clientul potrivit. Un client fără contact primește documente doar prin dosarul
lui din OneDrive, care se leagă din `Administrare → Surse documente`, sau prin
e-Factura, dacă a depus împuternicirea în SPV (vezi mai jos).

Două lucruri sunt refuzate, și amândouă din același motiv — altfel preluarea
automată s-ar opri **fără nicio eroare**:

- același CUI la doi clienți, oricum ar fi scris (`RO14399840` și `14399840` sunt
  același cod): identificarea ar găsi doi candidați și n-ar mai atribui nimic;
- aceeași adresă de email la doi clienți: adresele ambigue sunt scoase din harta
  de preluare, deci mesajele de la ea n-ar mai ajunge la nimeni.

Pentru instalarea de la zero, când încă nu există niciun cont prin care să te
autentifici, aceeași treabă o face:

```bash
uv run python -m app.cli add-client
```

### Onorariile lunii: cine cât plătește și cine a plătit

`CRM → Onorarii`. Se cere `fees:read` pentru a vedea și `fees:manage` pentru a
schimba ceva — implicit, doar administratorii le au. Nu pentru că suma ar fi un
secret, ci pentru că lista completă este ordinea în care cabinetul își ține
clienții după bani, iar pentru procesarea documentelor nu folosește nimănui.

Ordinea în care se face treaba:

1. **Suma se pune pe fișa clientului**, în `Clienți → [client] → Contabilitate →
   Onorariu lunar`. Câmpul gol înseamnă „nu-l facturez"; zero înseamnă „îl servesc
   gratuit" și produce totuși un rând de 0 lei. Sunt două lucruri diferite.
2. **„Generează luna"** creează rândurile lipsă. Se poate apăsa de câte ori vrei:
   nu dublează nimic și nu pierde încasările marcate între timp.
3. **„Am încasat"** se apasă când banii au intrat, nu când s-a trimis factura.
   Butonul are pereche — „Anulează încasarea" — pentru cazul apăsat din greșeală.

Ce trebuie știut, ca ecranul să nu surprindă:

- **Suma unei luni generate nu se mai schimbă.** Dacă renegociezi onorariul, luna
  deja facturată rămâne cât a fost; noul preț se aplică de la luna următoare pe
  care o generezi. Registrul nu își rescrie trecutul.
- **Un client contractat luna aceasta nu apare pe lunile trecute.** Data de la care
  se facturează se pune tot din fișa lui.
- **Un client care a plecat rămâne pe lunile deja facturate**, mai ales dacă sunt
  neîncasate. Ce se oprește este generarea lunilor următoare.
- **Restanțele din lunile trecute** stau într-un panou separat, deasupra listei.
  Este singurul loc din aplicație unde se mai văd: luna trece, ecranul se schimbă,
  banii rămân neîncasați.
- **Sumele în altă monedă se totalizează separat.** Lei plus euro nu este o sumă.
- **Coloana „lei/doc."** este onorariul împărțit la câte documente a trimis
  clientul în luna aceea. Nu este o măsură a efortului — o factură cu treizeci de
  poziții și un bon de benzină se numără la fel — dar este singura pe care o are
  cabinetul, și arată cine este subevaluat.
- **„Descarcă luna"** scoate un CSV cu un rând pe client: onorariu, încasare,
  număr de documente. Se deschide direct în Excel românesc.

Când clientul sună și spune „eu am plătit în martie", răspunsul stă pe fișa lui:
`Clienți → [client] → Contabilitate → Onorariu lunar`, sub „Ultimele luni
facturate" — douăsprezece luni, cu suma fiecăreia și data încasării.

### Un client spune că primește prea multe mesaje

Deschide `Comunicare → Remindere`. Rândul lui arată câte au plecat luna asta și
de ce mai pleacă. Aplicația trimite cel mult **două pe lună**, numai după patru
zile de tăcere și numai dacă i s-a cerut deja — dar la ele se adaugă solicitările
apăsate de oameni, care nu au plafon. Dacă numărul vine de acolo, problema nu este
aplicația, ci că doi colegi cer aceluiași client.

Pentru a opri complet trimiterea automată, pune `CLIENT_REMINDERS_ENABLED=false`
și repornește. Ecranul rămâne, cu butonul lui: se poate trimite mai departe la
apăsare.

### Un client nu apare niciodată în „Documente lipsă"

Cel mai probabil nu i s-a spus **ce** se așteaptă de la el. Checklistul lunii,
raportul de documente lipsă și starea perioadei se derivă toate din aceeași
listă: `Clienți → [client] → Contabilitate → Ce așteptăm lunar`.

Un client fără nicio bifă apare mereu complet, pentru că nu i se cere nimic —
tăcut, fără nicio eroare. Se bifează tipurile de document și, unde e cazul, câte
bucăți pe lună (cinci facturi de intrare, un extras de cont).

Se cere `periods:manage`: a hotărî ce datorează un client este un act contabil,
nu o editare de fișă. Aceeași permisiune ca închiderea lunii.

### Un client vrea și facturile din e-Factura

1. Clientul depune **împuternicirea în SPV** (formularul 150) pentru certificatul
   digital al cabinetului. Pasul ăsta nu se face din aplicație și nu depinde de
   noi; fără el, ANAF nu întoarce eroare — **întoarce gol**.
2. `Administrare → e-Factura` → **Adaugă împuternicirea** → alege clientul.
   CUI-ul se ia din fișa lui, normalizat (`RO14399840` și `14399840` sunt același
   cod, iar API-ul ANAF îl vrea pe al doilea).
3. `Sincronizează acum`, ca să se vadă imediat dacă ANAF acceptă. Dacă
   împuternicirea nu a ajuns încă, mesajul apare **pe rândul clientului**, nu pe
   conexiune.

Prima sincronizare se uită 30 de zile în urmă (`ANAF_LOOKBACK_DAYS`). ANAF nu
acceptă ferestre mai lungi de 60 de zile, deci istoricul mai vechi nu se poate
recupera pe drumul ăsta.

Fiecare factură intră ca **trei fișiere pe un singur document** — XML-ul, arhiva
ANAF cu sigiliul de acceptare și PDF-ul oficial — și se descarcă din fișa
documentului, secțiunea *Fișierele documentului*. La un control, arhiva este cea
care contează: ea poartă dovada acceptării și este singura care nu se poate
reface.

### Nu mai vine nicio factură din e-Factura

1. `Administrare → e-Factura`. Trei lucruri, în ordinea în care se strică:
   - **autorizarea a expirat.** Ține un an; ecranul o anunță cu 30 de zile
     înainte. Reînnoirea se face de la calculatorul cu tokenul USB în port, și
     păstrează toate împuternicirile.
   - **împuternicirea unui client a expirat sau nu a fost depusă.** Apare pe
     rândul lui. Se rezolvă la ANAF, de client, nu de noi.
   - **mediul este `test`.** `ANAF_ENVIRONMENT=test` interoghează o bază complet
     separată a ANAF, care nu conține nicio factură reală. Se raportează „nicio
     factură" la nesfârșit, fără nicio eroare.
2. Dacă totul e în regulă acolo, verifică dacă **workerul rulează** — la fel ca
   la OneDrive.
3. În log: `anaf_sync_run` la fiecare tur. `anaf_message_rejected` înseamnă un
   mesaj care nu conținea o factură (de obicei un raport de erori al ANAF);
   `anaf_pdf_failed` înseamnă că doar convertorul a căzut — factura și arhiva
   sunt salvate, iar PDF-ul se reia singur la un tur următor (`anaf_pdf_recovered`
   când reușește). **Reprocesarea nu ajută aici**: ea cheamă extracția, care
   citește XML-ul deja stocat, nu convertorul ANAF.

### Conectarea unei cutii poștale obișnuite (Gmail, Yahoo, găzduire)

`Administrare → Surse documente → Cutii poștale (IMAP) → Adaugă o cutie`.

Ai nevoie de patru lucruri: serverul (`imap.gmail.com`, `imap.mail.yahoo.com`,
sau ce spune găzduirea), portul (**993**, aproape întotdeauna), utilizatorul
(adresa completă) și parola.

⚠️ **La Gmail și la Microsoft trebuie o parolă de aplicație**, nu parola contului.
Amândouă resping de mult IMAP cu parola obișnuită, iar mesajul lor de eroare nu
spune asta. Se generează din setările de securitate ale contului, după ce
activezi autentificarea în doi pași.

Butonul **verifică înainte să salveze**: dacă serverul refuză, cutia nu se
adaugă. Un refuz aici înseamnă că datele chiar nu merg, nu că aplicația a greșit
ceva.

Ce se întâmplă apoi: la fiecare bătaie de cron se citesc mesajele noi, iar
atașamentele care arată a documente intră singure. Clientul se recunoaște după
adresa expeditorului; una necunoscută nu oprește nimic — documentul intră
neatribuit și așteaptă un om.

**Aplicația nu scrie în cutia ta.** Nu marchează mesaje ca citite, nu le mută, nu
le șterge. Ține minte doar unde a rămas.

### Nu vin documente dintr-o integrare

`Administrare → Surse documente`. Rândul integrării spune una din trei:

- **merge acum** — atunci uită-te la numărul de documente de lângă el. Zero
  înseamnă că drumul este deschis, dar n-a venit nimic pe el: caută cauza la
  celălalt capăt (dosarul e gol, clientul nu trimite acolo).
- **de configurat** — scrie exact ce lipsește: o variabilă de mediu, o conectare,
  o împuternicire. Cele trei se rezolvă în locuri diferite.
- **nu există încă** — nu aștepta documente pe acolo. Scrie ce ar fi nevoie.

Capcana care nu seamănă cu o eroare: **e-Factura conectată, fără împuterniciri.**
ANAF nu răspunde cu eroare, răspunde **gol**. Ecranul spune „niciun client
împuternicit"; fiecare client trebuie să depună formularul 150 în SPV.

### Documentele nu mai sosesc din OneDrive sau de pe email

1. `Administrare → Surse documente` spune dacă legătura mai este activă. Un token
   expirat apare acolo ca mesaj, nu tăcut.
2. Dacă legătura este activă, verifică dacă **workerul rulează**. Sincronizarea se
   face din el (la 2 minute) sau din cronul care bate `/internal/run-queue`. Fără
   niciunul dintre ele, nu se întâmplă nimic și nimic nu se plânge.
3. În log: `drive_sync_run` la fiecare tur, cu câte documente a adus.
   `drive_sync_skipped_busy` înseamnă că un tur anterior încă rulează — normal
   când sunt multe fișiere de adus, îngrijorător dacă se repetă ore în șir.

### Cineva nu se poate autentifica: „Prea multe încercări"

Autentificarea este limitată: **10 încercări pe minut** pentru o pereche
(adresă IP, cont) și **60 pe minut** pentru o adresă, peste toate conturile.
Răspunsul este `429` cu `Retry-After`; după un minut se deschide singur.

Dacă un birou întreg iese la internet printr-o singură adresă publică și lovește
pragul de 60, ridică `LOGIN_ATTEMPTS_PER_ADDRESS_PER_MINUTE`. Dacă în log apar
multe `login_rate_limited` de la o adresă necunoscută, cineva încearcă parole —
pragul își face treaba.

`LOGIN_ATTEMPTS_PER_MINUTE=0` oprește limitarea. Contorul stă în proces: mai multe
procese de API înseamnă mai multe contoare, iar pe o platformă care pornește un
proces per cerere nu limitează nimic — acolo limita se pune în proxy.

### Un document a rămas în `ERROR`

Motivul este scris pe document, în interfață. `Reprocesează` îl trimite din nou,
până la `MAX_PROCESSING_ATTEMPTS` încercări. După limita aceea butonul dispare —
un document care a eșuat de trei ori nu se repară a patra oară; se corectează de
mână, cu câmpurile completate de operator.

### Cererile rămân `PENDING` și numărul crește

Workerul nu consumă coada. Repornește-l. La pornire repune singur în coadă ce a
rămas de la o rulare moartă; manual, aceeași treabă o face:

```bash
uv run python -m app.cli recover-processing
```

### Un proces a murit în mijlocul procesării

Cererea rămâne `RUNNING` și este considerată abandonată după
`PROCESSING_STALE_AFTER_MINUTES`. Nu se pierde: următoarea pornire de worker sau
`recover-processing` o repune în coadă.

### Trebuie oprit totul

`SIGTERM` este suficient. Workerul termină documentul în lucru și abia apoi iese;
un job întrerupt oricum ar fi fost recuperat.

---

## Ce nu face sistemul singur

- **Nu șterge nimic.** Regulile de retenție există în configurare, dar sunt oprite
  implicit (`RETENTION_ENABLED=false`) și nu rulează până când cineva nu le
  pornește explicit.
- **Nu scrie în OneDrive.** Accesul cerut este de citire; dosarele clienților nu
  se ating.
- **Trimite singur un singur fel de mesaj către clienți: reminderul.** Pleacă la
  ora planificatorului (`GET /api/v1/internal/reminders`), numai către clienții
  cărora **li s-a cerut deja** și n-au răspuns de patru zile, cel mult de două ori
  pe lună și niciodată după termenul de depunere. Se oprește din
  `CLIENT_REMINDERS_ENABLED=false`; butonul „Trimite acum" din
  `Comunicare → Remindere` rămâne, fiindcă un om care apasă nu face automatizare.
  Nimic nu pleacă fără `SMTP_*` configurat.
- **Nu trimite nimic altceva de la sine către clienți.** Prima solicitare de
  documente pleacă doar când o apasă cineva; fără SMTP, textul se copiază și se
  trimite de mână, sau pe WhatsApp, dintr-un buton. Rezumatul zilnic merge la
  colegii din cabinet, nu la clienți.
- **Nu trimite niciodată singur pe WhatsApp.** Butoanele deschid conversația cu
  mesajul scris în câmpul de trimitere; ce pleacă hotărăște omul, iar aplicația
  nu are cum să afle dacă a plecat — deci nu scrie nicăieri că s-a trimis.
- **Nu emite facturi.** „Onorarii" este registrul cabinetului — cine cât plătește
  și cine a plătit. Nu are serie, număr, TVA sau e-Factura, iar marcarea unei
  încasări este gestul omului care a văzut extrasul.
- **Nu trimite facturi la ANAF.** e-Factura este, deocamdată, doar preluare: a
  emite un document fiscal în numele unui client este altă răspundere decât a-l
  descărca pe cel deja emis.
