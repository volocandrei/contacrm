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
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(64))"` | pornirea se oprește dacă a rămas cel implicit |
| `DATABASE_URL` | `postgresql+psycopg://…` | endpointul **cu pooler** al furnizorului |
| `DB_EXTERNAL_POOLER` | `true` | vezi §3 |
| `CORS_ALLOWED_ORIGINS` | domeniul real | caracterul universal este refuzat de configurare |
| `STORAGE_PROVIDER` | `s3` | vezi §4 |
| `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT_URL` | de la furnizor | |
| `CRON_SECRET` | un secret generat | vezi §5 |
| `TRUSTED_PROXY_COUNT` | `1` | Vercel este singurul proxy din față; fără el, jurnalul de audit notează adresa platformei la fiecare acțiune |
| `OCR_PROVIDER` | `local` | citește și facturi electronice, și PDF-uri; pornirea în producție refuză `mock` — vezi mai jos |

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

---

## Alternativa: un singur serviciu cu proces continuu

Railway, Render, Fly.io sau un VPS cu `docker compose` rulează API, worker și
Postgres exact cum rulează azi local, fără cron și fără S3 — `docker-compose.yml`
descrie deja stiva completă, worker inclus. Procesarea pornește imediat, nu la
următoarea bătaie de ceas.

Vercel câștigă la altceva: frontend și API pe aceeași origine, fără nimic de
administrat. Alege în funcție de care dintre cele două contează mai mult.

---

## Înainte de orice deploy în producție

`Settings.assert_production_ready()` oprește pornirea dacă `SECRET_KEY` a rămas
cel implicit, dacă `STORAGE_PROVIDER=s3` fără `S3_BUCKET`, sau dacă providerii de
OCR/AI sunt configurați inconsistent. În plus, de verificat manual:

- bucket-ul nu este public;
- `CORS_ALLOWED_ORIGINS` enumeră originile reale;
- migrările sunt aplicate **înainte** de a promova versiunea nouă;
- documentele nu se comit niciodată în repo — `storage/` și `ARHIVA/` sunt
  ignorate.
