# Lista de control pentru pornirea în producție

Documentul acesta se parcurge **în ordine, o singură dată**, în ziua în care
aplicația începe să țină date reale ale clienților unui cabinet. Nu explică cum
se face fiecare lucru — pentru asta sunt [DEPLOY.md](DEPLOY.md) și
[RUNBOOK.md](RUNBOOK.md). Spune **ce trebuie să fie adevărat înainte de primul
client real** și cum se verifică fiecare, rulând, nu citind.

Trei porți sunt marcate **STOP**. Dacă una nu trece, pornirea se amână — nu se
notează ca „de făcut după".

---

## 0. Înainte de a atinge serverul

- [ ] Cine este responsabilul de date în cabinet, și știe că este.
- [ ] S-a citit [CREDENTIALE.md](CREDENTIALE.md) și s-a decis **cu ce se pornește**.
      Aplicația funcționează fără nicio integrare externă; fiecare se poate adăuga
      după. A porni cu toate deodată înseamnă a depana cinci lucruri simultan.
- [ ] S-a citit secțiunea „Ce nu face aplicația" din [INTEGRATIONS.md](INTEGRATIONS.md),
      ca nimeni din cabinet să nu aștepte o depunere automată la ANAF.

## 1. Secretele — STOP

- [ ] `SECRET_KEY` generat pentru **această** instalare
      (`python -c "import secrets; print(secrets.token_urlsafe(64))"`), nu copiat
      din documentație, din dezvoltare sau din alt proiect.
- [ ] `DRIVE_TOKEN_KEY` generat separat de `SECRET_KEY`. Sunt distincte
      deliberat: prima se rotește după o scurgere, iar rotirea ei nu are voie să
      rupă tăcut legăturile cu OneDrive și cu email.
- [ ] `CRON_SECRET` generat.
- [ ] Niciun secret în repo, în `.env.example`, în frontend, în documentație sau
      în baza de date în clar. `.env.example` conține **doar nume**.
- [ ] Secretele stau în managerul de secrete al platformei, nu într-un fișier
      trimis pe email sau pe chat.

**Verificare:**

```bash
git ls-files | grep -E "^\.env$" && echo "STOP: .env este în repo"
grep -rnE "(SECRET_KEY|API_KEY|PASSWORD)\s*=\s*['\"][^'\"]{8,}" backend/app frontend/src
```

A doua comandă are, la data acestui document, exact **două** rezultate așteptate,
niciunul secret: parola setului de dezvoltare (`backend/app/cli.py`, `DEV_PASSWORD`)
și o parolă de test din frontend. Comanda `seed-dev` care o folosește **refuză să
ruleze în producție** (`settings.is_production`). Orice al treilea rezultat se
citește ca un secret real și se tratează ca atare.

CI-ul rulează la fiecare push verificările pentru `.env` comis, pentru documente
contabile ajunse în repo și pentru caractere de control în surse
(`.github/workflows/ci.yml`).

Dacă un secret a fost vreodată într-un fișier comis, chiar și șters ulterior:
**ROTATION REQUIRED** — se generează altul, istoria git îl păstrează pe primul.

## 2. Configurarea care oprește pornirea

`Settings.assert_production_ready()` refuză să pornească dacă lipsește ceva
esențial. Nu ocoli mesajul; el spune exact ce lipsește.

- [ ] `DATABASE_URL` — PostgreSQL 17, nu SQLite, nu baza de dezvoltare.
- [ ] `PUBLIC_BASE_URL` — adresa reală. Linkurile de încărcare ajung la clienți;
      greșită, duc nicăieri și clientul crede că aplicația e stricată.
- [ ] `CORS_ALLOWED_ORIGINS` — originile reale, enumerate.
- [ ] `VITE_API_MODE=http` la build-ul frontendului. Fără ea build-ul se oprește
      și spune de ce — implicitul ar fi fost backendul simulat, cu clienți
      inventați.
- [ ] `DEFAULT_TIMEZONE` — fusul cabinetului. Termenele se calculează pe ziua
      cabinetului, nu pe a serverului.
- [ ] `ANAF_ENVIRONMENT=prod`, dacă se folosește e-Factura. Lăsat pe `test`,
      raportează „nicio factură" la nesfârșit, fără nicio eroare.
- [ ] `client_max_body_size` în proxy-ul din față, cel puțin cât
      `MAX_UPLOAD_SIZE_MB`. Aplicația refuză fișierele mari în timp ce le
      citește, dar corpul cererii ajunge la proxy înainte.

## 3. Baza de date

- [ ] `alembic upgrade head` rulat **înainte** de a promova versiunea nouă.
      Niciodată `create_all()`: schema de producție se naște din migrări, altfel
      prima migrare reală se aplică peste o schemă pe care nimeni nu a văzut-o.
- [ ] Baza nu este accesibilă din internet.
- [ ] Utilizatorul aplicației nu este `postgres`.

```bash
uv run --directory backend alembic current   # trebuie să fie la head
uv run --directory backend alembic heads     # capul așteptat
```

`alembic check` și `--autogenerate` **nu** se folosesc ca verificare aici: pe
schema aceasta raportează constant ~180 de operații fantomă — indexuri pe
expresii (`unaccent`, `trgm`) și valori implicite pe care comparatorul lor nu le
recunoaște. Toate migrările sunt scrise de mână din acest motiv, iar fiecare îl
spune în docstring-ul ei. Un „check" care iese mereu roșu nu se citește după a
treia oară.

## 4. Primul cont, și de ce contează ordinea — STOP

- [ ] Contul de administrator se creează cu o parolă aleasă **atunci**, nu una
      din documentație. Politica de parole (12 caractere, fără fragmente din
      nume sau email) se aplică și aici.
- [ ] Parola implicită de dezvoltare (`DEV_PASSWORD`) nu există în producție.
      Comanda de populare cu date de demonstrație **nu** se rulează pe baza reală.
- [ ] S-a intrat o dată cu contul creat, s-a schimbat parola din aplicație și
      s-a verificat că ecranul de securitate arată sesiunea curentă.
- [ ] Al doilea administrator există. Un singur cont cu drepturi depline este un
      singur telefon pierdut.

**Verificare, cu contul de administrator:**

```
/administrare/securitate → sesiunile active, revocarea celorlalte
/administrare/utilizatori → rolurile, permisiunile fiecăruia
```

## 5. Stocarea documentelor

- [ ] `STORAGE_PATH` (sau bucket-ul S3) este pe un volum **persistent**, nu în
      containerul care se recreează la fiecare deploy.
- [ ] Bucket-ul nu este public. Se verifică cerând un obiect fără credențiale.
- [ ] `storage/` și `ARHIVA/` sunt ignorate de git. Niciun document contabil nu
      ajunge vreodată în repo; CI-ul verifică asta la fiecare push.

## 6. Copiile de siguranță — STOP

Nu „configurate". **Restaurate o dată, pe o instalare de test, înainte de primul
client real.** O copie care nu s-a restaurat niciodată nu este o copie; este o
speranță.

- [ ] Copia bazei rulează automat, zilnic.
- [ ] Copia fișierelor rulează **după** cea a bazei. Ordinea contează: un fișier
      apărut între cele două se regăsește pe disc fără rând în bază, ceea ce se
      repară; invers, un rând fără fișier arată ca un document pierdut.
- [ ] S-a parcurs restaurarea completă din [RUNBOOK.md](RUNBOOK.md), inclusiv
      pasul de verificare:

```bash
uv run --directory backend python -m app.cli check-storage
```

Comanda iese cu cod 1 dacă baza și fișierele sunt din momente diferite. Un cod 0
după restaurare este singura dovadă că a mers.

- [ ] Se știe **unde** ajung copiile și cine are acces la ele. Sunt datele
      financiare ale clienților, în întregime.

## 7. Observabilitate

- [ ] `/health/ready` răspunde 200 și este ce interoghează load balancer-ul.
- [ ] Logurile ajung undeva unde se pot citi peste o săptămână, nu doar în
      consola containerului.
- [ ] Cineva primește o alertă când workerul moare. Fără el, documentele intră și
      rămân în `PENDING` — ecranul nu arată nicio eroare, doar o coadă care crește.

## 8. Prima zi cu date reale

- [ ] Clienții s-au importat, iar numărul din aplicație se potrivește cu al
      cabinetului. Un client lipsă nu se semnalează singur.
- [ ] Catalogul de declarații s-a **confirmat cu un contabil**, rând cu rând.
      Termenele din cod sunt puncte de plecare uzuale, nu lege — vezi
      [DECLARATIONS.md](DECLARATIONS.md). Se ajustează din
      `/administrare/declaratii`.
- [ ] Fiecărui client i s-au bifat declarațiile pe care le depune. Un client fără
      nicio bifă nu apare **niciodată** în „Termene", tăcut.
- [ ] S-a încărcat un document real, s-a urmărit până la aprobare, și s-a
      descărcat registrul lunii ca fișier.
- [ ] S-a trimis un link de încărcare unui client real și s-a confirmat că
      funcționează de pe telefonul lui.

## 9. Ce rămâne explicit neverificat

Se scrie aici, la pornire, ce integrări nu au fost probate cu credențiale reale,
ca nimeni să nu presupună că merg. Starea la data acestui document, cu detalii în
[INTEGRATIONS.md](INTEGRATIONS.md):

| Integrare | Stare la livrare |
|---|---|
| ANAF / SPV (e-Factura) | NOT VERIFIED — EXTERNAL CREDENTIAL REQUIRED |
| Microsoft Graph (OneDrive, email) | MOCK VERIFIED |
| IMAP | MOCK VERIFIED |
| SMTP | MOCK VERIFIED |
| Model de extragere (poze, scanuri) | MOCK VERIFIED |
| SAGA | neimplementat, deliberat — lipsește formatul |

Prima rulare a fiecăreia se face **cu un singur client**, urmărită, nu pe tot
cabinetul deodată.

---

## Lista de bifat, pentru tipărit

Exact serviciile pe care le folosește **această** aplicație — nu o listă generică.
Ordinea contează: primele patru fac aplicația să funcționeze, restul se adaugă pe
rând. Detaliile fiecăruia în
[PRODUCTION_SETUP_ACCOUNTS.md](PRODUCTION_SETUP_ACCOUNTS.md).

```text
OBLIGATORII
[ ] Domeniu cumpărat și DNS configurat
[ ] Certificat TLS activ (fără el, nimeni nu se poate autentifica)
[ ] Server de producție, cu volum PERSISTENT pentru documente
[ ] PostgreSQL 17, utilizator dedicat, inaccesibil din internet
[ ] SECRET_KEY generat pentru această instalare
[ ] DRIVE_TOKEN_KEY generat, separat de SECRET_KEY
[ ] CRON_SECRET generat
[ ] PUBLIC_BASE_URL pus pe adresa reală
[ ] CORS_ALLOWED_ORIGINS enumerat explicit
[ ] VITE_API_MODE=http la build-ul frontendului
[ ] OCR_PROVIDER pus pe local (mock este refuzat în producție)
[ ] alembic upgrade head rulat înainte de promovare
[ ] Primul administrator creat, cu parolă aleasă atunci
[ ] Al doilea administrator creat
[ ] Copie de siguranță zilnică: bază ÎNTÂI, apoi fișiere
[ ] Copie RESTAURATĂ o dată, cu check-storage trecut
[ ] Planificator (cron) configurat pentru rutele interne

RECOMANDATE
[ ] Monitorizare externă pe /health/ready (aplicația nu are alerte)
[ ] SMTP configurat, cu SPF + DKIM + DMARC pe domeniu
[ ] NOTIFICATIONS_ENABLED=true, după un test către cabinet
[ ] Catalogul de declarații confirmat de un contabil, rând cu rând
[ ] Declarațiile bifate pentru fiecare client

OPȚIONALE, PE RÂND
[ ] Microsoft 365: aplicație în Entra ID + data de expirare a secretului notată
[ ] SAU o cutie IMAP, cu parolă de aplicație
[ ] ANAF: aplicație OAuth + certificat calificat + împuternicire per client
[ ] ANAF_ENVIRONMENT=prod (nu test)
[ ] AI_API_KEY, dacă clienții trimit poze
[ ] S3, dacă documentele nu stau pe discul serverului

PRIMA ZI
[ ] Clienții importați; numărul se potrivește cu al cabinetului
[ ] Un document real urcat, urmărit până la arhivă
[ ] Un link de trimitere testat de pe telefonul unui client
[ ] Prima rulare a fiecărei integrări, cu UN SINGUR client, urmărită
[ ] Datele de expirare trecute în calendar
    (PRODUCTION_EXPIRY_CHECKLIST.md)
```

**Nu îți trebuie:** cont Meta/WhatsApp, Twilio, Google Cloud, AWS Textract,
OpenAI, Redis, serviciu de plăți sau analytics. Niciunul nu este folosit de
aplicație — verificat prin căutare în tot codul.

---

## Dacă ceva nu trece

Nu se pornește „și se repară luni". Cele trei porți **STOP** — secretele, primul
cont, copiile restaurate — sunt lucrurile care, greșite, nu se observă până când
nu mai contează: o parolă implicită rămasă activă, un secret în istorie, o copie
care nu se restaurează. Restul se poate rezolva cu aplicația pornită.
