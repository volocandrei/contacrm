# Deploy

Un singur proiect Vercel, două servicii, aceeași origine.

```
                    ┌──────────────────────────────┐
   /api/*  ────────▶│  backend   (FastAPI, uvicorn) │──▶ Postgres
                    └──────────────────────────────┘    S3
                    ┌──────────────────────────────┐
   /*      ────────▶│  frontend  (Vite, static)     │
                    └──────────────────────────────┘
```

`vercel.json` de la rădăcina repo-ului descrie amândouă. **Root Directory rămâne
rădăcina**, nu `frontend/` — serviciile își declară singure rădăcinile.

---

## De ce aceeași origine, și nu două domenii

Nu este o preferință de estetică. Sesiunea trăiește într-un cookie `httpOnly`
cu `SameSite=Lax`, iar un cookie `Lax` **nu însoțește cererile pornite de
`<img>` sau `<object>`** de pe altă origine. Cu API-ul pe alt domeniu,
autentificarea ar merge și previzualizarea documentelor ar returna 401 — un bug
care nu apare în niciun test și se vede abia când cineva deschide o factură.

Alternativele ar fi fost `SameSite=None` (slăbește apărarea CSRF) sau un token în
URL (interzis, §27: URL-ul ajunge în loguri de proxy, în istoricul browserului și
în `Referer`). Rescrierea `/api/*` către serviciul de backend le face pe amândouă
inutile: pentru browser, totul vine de la aceeași origine.

De aceea frontendul nu primește `VITE_API_BASE_URL`. Implicit folosește calea
relativă `/api/v1`, care este exact ce trebuie.

---

## 1. Legarea proiectului

Aplicația Vercel pentru GitHub are nevoie de acces la repo. Pe
[vercel.com/new](https://vercel.com/new) → *Import Git Repository* → dacă
`contacrm` nu apare, **Adjust GitHub App Permissions**.

La import: `Root Directory` = rădăcina repo-ului. Restul vine din `vercel.json`.

## 2. Variabile de mediu

Pe serviciul **frontend**:

| Variabilă | Valoare | De ce |
|---|---|---|
| `VITE_API_MODE` | `http` | altfel rulează pe backendul simulat din browser |

`VITE_API_BASE_URL` rămâne **nesetată**. Vezi secțiunea de mai sus.

Pe serviciul **backend**:

| Variabilă | Valoare | De ce |
|---|---|---|
| `ENVIRONMENT` | `production` | ascunde `/docs` și pune `Secure` pe cookie-uri |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(64))"` | pornirea se oprește dacă a rămas cel implicit **sau dacă are sub 32 de caractere** — cheia semnează tokenurile de acces |
| `DATABASE_URL` | `postgresql+psycopg://…` | endpointul **cu pooler** al furnizorului |
| `DB_EXTERNAL_POOLER` | `true` | vezi §3 |
| `CORS_ALLOWED_ORIGINS` | domeniul real | caracterul universal este refuzat de configurare |
| `STORAGE_PROVIDER` | `s3` | vezi §4 |
| `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT_URL` | de la furnizor | |
| `CRON_SECRET` | un secret generat | vezi §5 |
| `TRUSTED_PROXY_COUNT` | `1` | Vercel este singurul proxy din față; fără el, jurnalul de audit notează adresa platformei la fiecare acțiune — **și limitarea autentificării ar număra toate încercările la aceeași adresă** |
| `LOGIN_ATTEMPTS_PER_MINUTE`, `LOGIN_ATTEMPTS_PER_ADDRESS_PER_MINUTE` | implicit `10` și `60` | câte încercări de autentificare acceptă o adresă pentru un cont, și în total. Contorul stă în proces: pe o platformă care pornește un proces per cerere nu limitează nimic, deci acolo limita trebuie pusă la marginea rețelei |
| `OCR_PROVIDER` | `local` | citește și facturi electronice, și PDF-uri; pornirea în producție refuză `mock` — vezi mai jos |
| `FILING_DEADLINE_DAY` | implicit `25` | ziua din luna următoare până la care se depun declarațiile lunii încheiate. Panoul principal numără zilele rămase după ea |

**Pornirea în producție refuză `OCR_PROVIDER=mock`.** Providerul acela inventează
furnizori, sume și date, iar ecranul de verificare le arată cu proveniență și scor
de încredere — adică exact ca pe niște valori citite de pe document. Într-o
demonstrație este util; într-o instalare reală ar scrie valori false în câmpuri
contabile, fără ca operatorul să aibă cum să le deosebească. Pentru demonstrații
rămâne `ENVIRONMENT=staging`.

`local` citește ce se poate citi cu certitudine, pe mașina noastră, fără rețea și
fără cheie de API: facturile electronice (XML, UBL 2.1) prin cititorul de
e-Factura, restul prin stratul de text al PDF-ului. Din punctul de vedere al GDPR
este identic cu `mock` — nimic nu pleacă nicăieri — doar că rezultatul este
adevărat. Un provider bazat pe model ar însemna că documentele părăsesc
infrastructura noastră: o decizie cu implicații GDPR (R2), nu o schimbare de
configurare.

## 3. Baza de date

Orice PostgreSQL gestionat (Neon, Supabase). Două lucruri contează:

**Conectează-te prin pooler și spune-i aplicației.** Într-un mediu unde procesele
apar și dispar odată cu traficul, fiecare instanță ar deschide propriile
conexiuni și baza ar rămâne fără exact în vârf. `DB_EXTERNAL_POOLER=true` oprește
poolul propriu al SQLAlchemy — poolerul este deja poolul — și oprește
instrucțiunile pregătite, pe care un pooler în mod tranzacție le rupe tăcut:
sesiunea din spate se schimbă între tranzacții, iar la a doua cerere apare un
`prepared statement "_pg3_0" does not exist` venit aparent din senin.

**Migrările nu rulează din deploy.** Se aplică separat, de la o mașină cu acces
la baza de date, **înainte** de a promova versiunea:

```bash
cd backend
DATABASE_URL=… uv run alembic upgrade head
DATABASE_URL=… uv run python -m app.cli sync-roles
DATABASE_URL=… uv run python -m app.cli create-admin
```

`create-admin` există pentru că nu există niciun drum prin interfață care să
creeze primul utilizator: orice creare de cont cere deja un cont. Parola se
citește de la tastatură, niciodată dintr-un argument — argumentele ajung în
istoricul shell-ului și în lista de procese.

## 4. Stocarea documentelor

`LocalStorageProvider` presupune un disc care supraviețuiește repornirii. În
containere efemere, discul dispare — iar o probă contabilă nu are voie să dispară
(R8). De aceea `STORAGE_PROVIDER=s3`.

`S3StorageProvider` vorbește **protocolul**, nu cu un furnizor anume: AWS S3,
Supabase Storage, Cloudflare R2, MinIO. Se schimbă doar `S3_ENDPOINT_URL` (gol
înseamnă AWS). Aceleași teste de contract rulează pe el și pe providerul local —
`tests/test_storage.py` pune fiecare întrebare de două ori.

**Bucket-ul trebuie să fie privat.** Nu se generează URL-uri semnate și nu se
servește nimic direct: tot ce iese trece prin API, care verifică organizația
(§51, §72). Un bucket citibil anonim ar face inutilă fiecare verificare de
autorizare din aplicație.

## 5. Workerul

Workerul face **două** lucruri: execută coada de procesare și întreabă periodic
sursele externe (OneDrive, cutia poștală) dacă a apărut ceva nou. Al doilea
contează la fel de mult ca primul — fără el, preluarea automată nu se întâmplă,
iar interfața arată totuși o conexiune activă și dosare urmărite.

**Exact unul dintre cele două trebuie să existe într-o instalare:**

| Instalare | Ce pornește procesarea și sincronizarea |
| --- | --- |
| server propriu (`docker compose`) | `python -m app.worker`, proces continuu |
| Vercel sau altă platformă scalată la zero | cronul din `vercel.json`, la 5 minute |

`python -m app.worker` presupune un proces care trăiește. Într-un mediu care
scalează la zero, procesul acela nu are unde să existe; ce rămâne este un ceas
din afară. `vercel.json` declară un cron la 5 minute către
`/api/v1/internal/run-queue`, iar Vercel trimite `Authorization: Bearer
$CRON_SECRET`.

Ruta face exact ce face workerul la pornire: repune în coadă ce a rămas de la o
rulare moartă, apoi execută un lot mic. Într-un mediu fără proces continuu, „o
rulare moartă" este cazul normal — o funcție care a depășit timpul maxim lasă
aceeași urmă ca un proces ucis.

**Fără `CRON_SECRET`, ruta răspunde 404** — același răspuns ca pentru un secret
greșit, deci nimic din afară nu află care dintre ele s-a întâmplat. Un endpoint
care execută muncă nu are voie să fie deschis nici măcar o clipă.

Consecința pe care merită s-o știi dinainte: un document încărcat așteaptă până
la 5 minute înainte să înceapă procesarea. Cu un proces continuu, așteptarea este
de ordinul secundelor.

---

## 6. OneDrive / SharePoint — preluarea automată a documentelor

Cabinetul are deja un dosar per client în OneDrive, unde clienții își pun
documentele. Integrarea le citește singură, le atribuie clientului dosarului și
le arhivează cu numele standardizat — adică exact munca de descărcat și
redenumit, făcută de sistem.

**Se cere acces doar la citire.** Nimic nu se scrie și nimic nu se redenumește în
dosarele clienților: un sistem care umblă în fișierele altcuiva le strică
într-o zi.

### Înregistrarea aplicației (o singură dată)

În [Microsoft Entra ID](https://entra.microsoft.com) → *App registrations* →
*New registration*:

| Câmp | Valoare |
|---|---|
| Name | ContaCRM |
| Supported account types | *Accounts in any organizational directory and personal Microsoft accounts* |
| Redirect URI | **Web** → `https://<domeniul-tău>/administrare/surse` |

Apoi, în aplicația creată:

1. *Certificates & secrets* → *New client secret* → copiază **valoarea** (nu id-ul);
   se afișează o singură dată.
2. *API permissions* → *Microsoft Graph* → *Delegated* → adaugă `Files.Read.All`,
   `User.Read`, `offline_access`. Pentru un cont de firmă, apasă și
   *Grant admin consent*.
3. *Overview* → copiază **Application (client) ID**.

### Variabile

| Variabilă | Valoare |
|---|---|
| `MS_CLIENT_ID` | Application (client) ID |
| `MS_CLIENT_SECRET` | valoarea secretului |
| `MS_TENANT_ID` | `common`, sau id-ul tenantului pentru a restrânge accesul |
| `MS_REDIRECT_URI` | **identic** cu cel din Entra ID |
| `DRIVE_TOKEN_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

`MS_REDIRECT_URI` trebuie să fie caracter cu caracter același cu cel înregistrat;
o diferență de slash final produce o eroare Microsoft care nu spune care este
problema.

**`DRIVE_TOKEN_KEY` este separată de `SECRET_KEY`, deliberat.** Refresh tokenul
Microsoft nu poate fi stocat hash-uit — trebuie folosit, deci trebuie citit
înapoi — iar ce se citește înapoi dintr-un dump de bază de date dă acces la
OneDrive-ul cabinetului. `SECRET_KEY` se rotește exact după o scurgere, adică
exact când nimeni nu vrea să descopere că a pierdut și legăturile cu OneDrive.
Fără cheie, conectarea este refuzată cu un mesaj explicit: nu se scrie niciun
token în clar „doar de data asta".

**Rotirea cheii invalidează conexiunile existente.** Nu se pierde niciun
document; ecranul spune că trebuie reconectat contul.

### Punerea în funcțiune

Din aplicație: *Administrare → Surse documente* → **Conectează OneDrive** →
răsfoiește până la dosarul fiecărui client → **Urmărește** → alege clientul.
Maparea se face o singură dată.

De atunci, fiecare bătaie de cron aduce ce e nou. Un dosar rămas fără client
atribuit nu blochează nimic: documentele intră și ajung la verificare
neatribuite, ca oricare altele.

### Emailul, pe aceeași conexiune

Același consimțământ acoperă și cutia poștală (scope-ul `Mail.Read`, tot doar
citire). În aceeași pagină, secțiunea **Dosare de email urmărite**: alege dosarul
în care ajung mesajele clienților — de obicei unul creat cu o regulă de Outlook,
nu Inbox-ul întreg.

**Aici clientul îl dă expeditorul, nu dosarul.** Într-o cutie poștală intră toți
clienții deodată, deci adresa de pe mesaj se caută printre contactele din CRM.
Consecința practică: ce trebuie ținut la zi sunt **adresele de contact ale
clienților**, nu o mapare de dosare. Un expeditor necunoscut nu oprește nimic —
atașamentul intră și ajunge la verificare neatribuit.

Nu tot ce e atașat este document: logo-urile din semnături sunt sărite (marcate
`inline`, sau sub 8 KB), la fel ca fișierele de tip neacceptat.

---

## 7. e-Factura — preluarea facturilor din SPV-ul ANAF

De la 1 iulie 2024 factura electronică este obligatorie între firme. Practic asta
înseamnă că partea covârșitoare a facturilor unui cabinet **nu mai vine pe email
și nu mai ajunge în niciun dosar**: stă în Spațiul Privat Virtual al fiecărui
client. Integrarea le aduce singură.

Fiecare factură ajunge ca **trei fișiere**, pe un singur document:

| Fișier | De unde vine | Se poate reface? |
|---|---|---|
| **XML-ul** (UBL 2.1) | membru al arhivei ANAF, scos nemodificat | — este originalul fiscal |
| **Arhiva ZIP** cu sigiliul ANAF | `descarcare`, exact cum o dă ANAF | **nu** — este dovada acceptării |
| **PDF-ul oficial** | convertorul public al ANAF | da, oricând, din XML |

Toate trei se descarcă din fișa documentului, secțiunea *Fișierele documentului*.

### Cele două condiții care nu se rezolvă din configurare

**1. Autorizarea cere certificatul digital calificat**, prezentat de browser.
Nu există cont de serviciu și nu există `client_credentials`: ANAF vrea o
persoană identificată. Pasul se face **de la calculatorul cu tokenul USB în
port**, o dată pe an — după el, preluarea merge nesupravegheat.

**2. Fiecare client trebuie să depună împuternicirea în SPV** (formularul 150),
pentru certificatul cabinetului. Fără ea, ANAF **nu întoarce eroare — întoarce
gol**, ceea ce este mai neplăcut: nimic nu se strică vizibil, pur și simplu nu
vine nicio factură. De aceea aplicația arată refuzul pe rândul clientului, cu ce
are de făcut, în loc să îl lase în tăcere.

Costul real al funcționalității este al doilea punct, și este administrativ:
clienții se strâng unul câte unul.

### Înregistrarea aplicației (o singură dată)

În portalul OAuth al ANAF, cu certificatul în port, se înregistrează o aplicație
și se declară adresa de redirect. Rezultatul sunt un `client_id` și un
`client_secret`.

| Variabilă | Valoare |
|---|---|
| `ANAF_CLIENT_ID` | id-ul aplicației înregistrate |
| `ANAF_CLIENT_SECRET` | secretul ei |
| `ANAF_REDIRECT_URI` | **identic** cu cel înregistrat: `https://<domeniu>/administrare/e-factura` |
| `ANAF_ENVIRONMENT` | `prod`, sau `test` pentru mediul de test |
| `DRIVE_TOKEN_KEY` | aceeași cheie ca la OneDrive — vezi mai sus |

`ANAF_ENVIRONMENT` nu este un nivel de log: `test` și `prod` sunt **baze complet
separate** la ANAF. Un token de test nu vede nimic în producție, iar o instalare
lăsată pe `test` raportează „nicio factură" la nesfârșit.

### Punerea în funcțiune

Din aplicație: *Administrare → e-Factura* → scrie al cui este certificatul →
**Autorizează la ANAF** → apoi, pentru fiecare client cu împuternicire depusă,
**Adaugă împuternicirea**.

De atunci, fiecare bătaie de cron aduce ce e nou. Prima sincronizare a unui
client se uită `ANAF_LOOKBACK_DAYS` în urmă (implicit 30); ANAF nu acceptă
ferestre mai lungi de 60 de zile într-o singură cerere, deci un client adăugat
după un an nu recuperează tot istoricul.

**Autorizarea expiră după un an.** Ecranul o anunță cu 30 de zile înainte.
Reînnoirea este același drum, cu același token USB; împuternicirile rămân.

### Ce nu face, deliberat

**Nu trimite facturi.** `/upload` și `stareMesaj` există în API-ul ANAF și nu
sunt implementate: a emite un document fiscal în numele unui client este altă
răspundere decât a-l descărca pe cel deja emis, și nu se strecoară într-o
funcție de preluare.

---

## Alternativa: un singur serviciu cu proces continuu

Railway, Render, Fly.io sau un VPS cu `docker compose` rulează API, worker și
Postgres exact cum rulează azi local, fără cron și fără S3 — `docker-compose.yml`
descrie deja stiva completă, worker inclus. Procesarea pornește imediat, nu la
următoarea bătaie de ceas.

Vercel câștigă la altceva: frontend și API pe aceeași origine, fără nimic de
administrat. Alege în funcție de care dintre cele două contează mai mult.

---

## Primii pași într-o bază de producție

```bash
uv run alembic upgrade head
uv run python -m app.cli sync-roles      # rolurile și permisiunile din cod
uv run python -m app.cli create-admin    # primul cont; cere parola la tastatură
uv run python -m app.cli add-client      # un client, cu emailul lui de contact
```

`seed-dev` **nu** rulează în producție și bine face: parolele lui sunt publice, iar
datele sunt inventate.

`add-client` există pentru instalarea de la zero, când încă nu ai niciun cont cu
care să te autentifici. După primul client, restul se adaugă din interfață:
*Clienți → Client nou*.

**Emailul de contact contează**: după el ajunge un atașament primit la clientul
potrivit. Un client fără contact primește documente doar prin dosarul lui din
OneDrive sau prin e-Factura, dacă a depus împuternicirea în SPV.

---

## Copii de siguranță, restaurare, incidente

`docs/RUNBOOK.md`. Pe scurt, partea care se greșește cel mai des: **copia bazei de
date se face înaintea copiei fișierelor**, nu invers. Un document este scris în
stocare înainte de a fi comis în baza de date, deci o bază de la T1 cu fișiere de
la T2 > T1 este coerentă; ordinea inversă produce rânduri fără fișiere.

După orice restaurare:

```bash
uv run python -m app.cli check-storage
```

Comanda compară fiecare document din baza de date cu fișierul lui din stocare și
iese cu cod diferit de zero dacă nu se potrivesc. O restaurare nu este terminată
până când nu trece.

---

## Înainte de orice deploy în producție

`Settings.assert_production_ready()` oprește pornirea dacă `SECRET_KEY` a rămas
cel implicit, dacă `STORAGE_PROVIDER=s3` fără `S3_BUCKET`, sau dacă providerii de
OCR/AI sunt configurați inconsistent. În plus, de verificat manual:

- bucket-ul nu este public;
- `CORS_ALLOWED_ORIGINS` enumeră originile reale;
- migrările sunt aplicate **înainte** de a promova versiunea nouă;
- documentele nu se comit niciodată în repo — `storage/` și `ARHIVA/` sunt
  ignorate;
- **`VITE_API_MODE=http`**. Fără ea, build-ul frontendului refuză să pornească
  și spune de ce — implicitul ar fi fost backendul simulat din browser, cu
  clienți și documente inventate;
- limita de dimensiune a corpului cererii, în proxy-ul din față
  (`client_max_body_size 30m` în nginx). Aplicația refuză fișierele peste
  `MAX_UPLOAD_SIZE_MB` **în timp ce le citește**, dar corpul cererii este primit
  de server înainte de asta;
- antetele de securitate vin din aplicație (`SecurityHeadersMiddleware`), deci
  există pe orice instalare. Cele din `vercel.json` rămân ca al doilea strat;
- dacă folosești e-Factura: `ANAF_ENVIRONMENT=prod`, nu `test`. Cele două sunt
  baze separate la ANAF, iar o instalare lăsată pe `test` raportează „nicio
  factură" la nesfârșit, fără nicio eroare.
