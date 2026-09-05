# Ce credențiale trebuie adunate

Lista completă a lucrurilor pe care aplicația le cere din exterior, în ordinea în
care merită obținute. Pentru fiecare: **cine o dă**, **ce deblochează**, și **ce
se întâmplă fără ea**.

Regula generală a proiectului: fără o credențială, funcția respectivă **spune că
nu este configurată** — nu se oferă și apoi eșuează. Se poate lucra cu jumătate
din listă.

---

## 0. Fără nimic din exterior

Astea nu se cer de la nimeni; se generează sau se aleg.

| Variabilă | Cum se obține | Fără ea |
|---|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(64))"` | **Pornirea în producție se oprește.** Semnează tokenurile de sesiune; una slabă înseamnă că oricine își semnează singur un token valabil |
| `DATABASE_URL` | Adresa PostgreSQL 17 al instalării | Nu pornește nimic |
| `PUBLIC_BASE_URL` | Adresa reală a aplicației, ex. `https://contacrm.cabinet.ro` | **Pornirea în producție se oprește.** Linkurile de trimitere ajung la clienți și nu duc nicăieri |
| `DRIVE_TOKEN_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | Nu se pot lega OneDrive/email/ANAF: criptează refresh tokenurile lor înainte de bază |
| `CRON_SECRET` | Un secret aleatoriu | Rutele interne de sincronizare periodică nu se pot apela |

`DRIVE_TOKEN_KEY` este **separată de `SECRET_KEY`**, deliberat: aceea se rotește
după o scurgere, iar rotirea ei nu are voie să rupă tăcut legăturile cu OneDrive.

---

## 1. Microsoft Entra ID — OneDrive, SharePoint și email

**De unde:** [Azure Portal](https://portal.azure.com) → Entra ID → App registrations
→ New registration. Pașii în `docs/DEPLOY.md`.

| Variabilă | Ce este |
|---|---|
| `MS_CLIENT_ID` | Application (client) ID al aplicației înregistrate |
| `MS_CLIENT_SECRET` | Client secret generat pentru ea |
| `MS_TENANT_ID` | `common` acceptă orice cont Microsoft; id-ul propriu restrânge la utilizatorii cabinetului |
| `MS_REDIRECT_URI` | Trebuie **identic** cu ce e înregistrat în Entra ID, altfel consimțământul eșuează cu o eroare opacă |

**Deblochează:** citirea dosarelor de OneDrive/SharePoint și a atașamentelor din
email — două surse de documente, un singur consimțământ.

**Fără ea:** ecranul „Surse documente" spune că integrarea nu este configurată.
Documentele intră prin încărcare manuală și prin portalul clientului.

---

## 2. ANAF — e-Factura / SPV

**De unde:** portalul OAuth al ANAF. Pașii în `docs/DEPLOY.md`.

| Variabilă | Ce este |
|---|---|
| `ANAF_CLIENT_ID` | Din aplicația înregistrată la ANAF |
| `ANAF_CLIENT_SECRET` | Idem |
| `ANAF_REDIRECT_URI` | Identic cu ce e înregistrat la ANAF |
| `ANAF_ENVIRONMENT` | `prod` pe facturi reale, `test` pe mediul lor de test — baze complet separate |

**Două condiții care NU se rezolvă din configurare:**

1. **Certificatul digital calificat înrolat în SPV**, prezentat de browser la
   autorizare. Se face o dată pe an, de la calculatorul cu tokenul USB în port.
2. **Împuternicirea fiecărui client în SPV** (formularul 150) pentru certificatul
   cabinetului. Fără ea, ANAF nu întoarce eroare — **întoarce gol**, ceea ce e mai
   greu de observat.

**Deblochează:** preluarea automată a facturilor electronice ale clienților.

---

## 3. Model de limbaj — citirea pozelor

**De unde:** [console.anthropic.com](https://console.anthropic.com) → API Keys.

| Variabilă | Ce este |
|---|---|
| `AI_API_KEY` | Cheia de API |
| `AI_MODEL` | Implicit `claude-sonnet-5`; trebuie să vadă imagini și PDF-uri |
| `OCR_PROVIDER` | `hybrid` — local întâi, model doar pentru ce n-are strat de text |

**Deblochează:** citirea documentelor **fotografiate sau scanate**. Fără ea, o
poză ajunge la verificare cu toate câmpurile goale și se tastează de mână.

**Decizie de luat conștient:** cu `hybrid`, pozele **părăsesc cabinetul** și
ajung la furnizorul modelului. Pentru un cabinet de contabilitate asta are
implicații GDPR — de verificat înainte, nu după. PDF-urile care se pot citi local
nu pleacă nicăieri.

**Fără ea:** `OCR_PROVIDER=local` citește PDF-urile digitale și facturile
electronice, tot fără să trimită nimic nicăieri.

---

## 4. Model de limbaj — asistentul din aplicație

**De unde:** aceeași consolă. Poate fi **aceeași cheie** ca la punctul 3, sau alta.

| Variabilă | Ce este |
|---|---|
| `ASSISTANT_API_KEY` | Cheia de API |
| `ASSISTANT_PROVIDER` | `anthropic` ca să folosească modelul; `rules` este implicit |
| `ASSISTANT_MODEL` | Implicit `claude-sonnet-5` |

**De ce e separată de `AI_API_KEY`:** sunt două decizii diferite. Un cabinet poate
vrea un asistent care răspunde la întrebări **fără** să trimită nicăieri
documentele clienților.

**Fără ea:** asistentul merge pe motorul cu reguli — determinist, fără nicio
credențială, acoperă întrebările scurte și frecvente. `ASSISTANT_PROVIDER=anthropic`
fără cheie **oprește pornirea**, ca să nu pară că plătești pentru un model care de
fapt nu răspunde.

---

## 5. Stocare S3 (opțional)

Doar dacă documentele nu stau pe discul serverului.

| Variabilă | Ce este |
|---|---|
| `STORAGE_PROVIDER` | `s3` |
| `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` | Ale furnizorului |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Credențialele |

**Fără ele:** `STORAGE_PROVIDER=local`, documentele stau în `STORAGE_PATH`.

---

## Ce NU trebuie adunat încă

Variabilele astea există în `.env.example` ca plan, dar **niciun cod nu le
citește**. Nu pierde timp cu ele:

- `SMTP_*` — trimiterea de email nu e implementată. Solicitările de documente se
  copiază și pleacă din clientul de email al contabilului.
- `WHATSAPP_*` — trimiterea pe WhatsApp nu e implementată.
- `SENTRY_DSN`, `OTEL_EXPORTER_OTLP_ENDPOINT` — logurile sunt structurate și merg
  la stdout; nu există încă export.

---

## Ordinea în care le-aș obține

1. **Punctul 0** — se generează în cinci minute, fără nimeni.
2. **Punctul 3** (citirea pozelor) — cel mai mare câștig pe zi de muncă, o
   singură cheie.
3. **Punctul 2** (ANAF) — cel mai lung de obținut din cauza certificatului și a
   formularelor 150; merită început devreme chiar dacă se termină târziu.
4. **Punctul 1** (Microsoft) — util dacă documentele vin deja pe email sau în
   OneDrive.
5. **Punctul 4** (asistentul) — plăcut, nu esențial: motorul cu reguli acoperă
   întrebările frecvente.

---

## Ce nu e verificat cu credențiale reale

Tot ce vorbește cu exteriorul este exercitat în teste cu transporturi false: ce
se trimite, ce se face cu răspunsul, ce se întâmplă când nu vine. **Prima cerere
adevărată rămâne de făcut o dată, manual, la instalare** — pentru ANAF, Microsoft
Graph, asistent și citirea pozelor.
