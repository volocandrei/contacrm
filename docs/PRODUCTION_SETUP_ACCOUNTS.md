# Ce conturi îmi trebuie înainte de LIVE

Lista este pentru **proprietarul aplicației**, nu pentru un programator. Conține
numai serviciile de care aplicația chiar are nevoie — derivate din cod, nu dintr-o
listă generică. Detaliile tehnice ale fiecăruia sunt în
[PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md](PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md).

**Citește întâi asta:** aplicația funcționează și este utilă cu **doar primele
patru** de mai jos. Clienți, documente încărcate de mână sau trimise de client
printr-un link, termene, onorarii, rapoarte, bancă din fișier — toate merg fără
nicio integrare. Restul se adaugă pe rând, iar cât timp lipsesc, ecranul lor
spune că nu sunt configurate. **Nu le lua pe toate deodată**: înseamnă să depanezi
cinci lucruri simultan.

---

# OBLIGATORII

## 1. Domeniu

- **furnizor:** oricare registrar (ROTLD pentru `.ro`, sau internațional)
- **la ce folosește:** adresa la care intră cabinetul și la care ajung linkurile
  trimise clienților
- **ce trebuie configurat:**
  - un `A`/`CNAME` către serverul aplicației;
  - **certificat TLS** (gratuit cu Let's Encrypt, sau făcut de platformă);
  - dacă vei trimite emailuri de pe domeniu: `SPF`, `DKIM`, `DMARC` — vezi §4.
- **cost:** ~10–50 lei/an pentru `.ro`
- **expiră:** da, anual. Pune reînnoire automată.

## 2. Server de producție

- **furnizor:** oricare (Hetzner, DigitalOcean, un VPS românesc, sau serverul
  cabinetului)
- **la ce folosește:** rulează API-ul, workerul care procesează documentele, și
  interfața
- **ce trebuie:** Docker, sau Python 3.13 + Node 24
- **acces necesar:** SSH, drept de a deschide porturi și de a instala
- **cost:** de la ~25 lei/lună
- **de reținut:** documentele se scriu pe disc. Discul trebuie să fie
  **persistent** — nu unul care se șterge la fiecare pornire.

## 3. PostgreSQL 17

- **furnizor:** pe același server, sau găzduit (Supabase, Neon, RDS)
- **la ce folosește:** toate datele: clienți, documente, termene, bancă, jurnal
- **credențiale:** un utilizator dedicat cu parola lui — **nu** `postgres`
- **cost:** inclus dacă e pe serverul tău; de la ~25 lei/lună găzduit
- **obligatoriu:** baza **nu** trebuie să fie accesibilă din internet
- **obligatoriu:** copie de siguranță zilnică, **restaurată o dată** înainte de
  primul client real (vezi §12)

## 4. Adresă de email pentru trimitere (SMTP)

- **furnizor:** cel al domeniului, Microsoft 365, Google Workspace, sau un
  serviciu tranzacțional (SendGrid, Mailgun, Postmark)
- **la ce folosește:** solicitările de documente către clienți, linkurile de
  încărcare, memento-urile, rezumatul zilnic
- **ce îți trebuie:** gazdă, port, utilizator, parolă
- **cost:** de obicei inclus; serviciile tranzacționale au un plan gratuit mic
- **atenție:** fără `SPF`, `DKIM` și `DMARC` pe domeniu, mesajele ajung în spam.
  Este cea mai frecventă cauză de „clientul spune că nu a primit nimic".
- **fără el:** aplicația **spune** că trimiterea nu este configurată; nu se preface
  că a trimis.

---

# OPȚIONALE — se adaugă când cabinetul le vrea

## 5. Microsoft 365 (OneDrive/SharePoint + email)

**Ia-l dacă:** vrei ca documentele să se preia **singure** din dosarele clienților
sau din cutia poștală a cabinetului.

- **cont:** tenant Microsoft 365 pe care cabinetul îl are deja
- **ce se creează:** o „aplicație înregistrată" în Azure Portal → Entra ID
- **credențiale:** `client id`, `client secret`, `tenant id`
- **permisiuni cerute:** doar **citire** (`Files.Read.All`, `Mail.Read`)
- **cost:** inclus în abonamentul Microsoft 365
- **⚠ expiră:** **client secretul expiră** la 6, 12 sau 24 de luni, după cum e
  creat. Este cea mai frecventă cauză de „nu mai vin documente". **Notează data
  în calendar.**

## 6. Cutie poștală obișnuită (IMAP) — alternativa la §5

**Ia-o dacă:** cabinetul nu e pe Microsoft 365, ci pe Gmail, Yahoo sau găzduire.

- **cont:** cutia poștală a cabinetului
- **ce trebuie:** IMAP activat, plus o **parolă de aplicație** (Gmail și Yahoo o
  cer; parola contului nu merge)
- **cost:** niciunul peste contul de email
- **se configurează din interfață**, nu din fișiere.

## 7. ANAF / e-Factura (SPV)

**Ia-l dacă:** vrei ca facturile electronice ale clienților să se descarce singure
din SPV.

- **cont:** contul SPV al cabinetului
- **ce se creează:** o aplicație înregistrată în portalul OAuth al ANAF
- **credențiale:** `client id`, `client secret`, **plus un certificat digital
  calificat** (certSIGN, DigiSign, Trans Sped — cel pe care cabinetul îl folosește
  deja pentru SPV)
- **mai trebuie:** **împuternicire în SPV pentru fiecare client** ale cărui
  facturi le preiei. Fără ea, ANAF nu returnează nimic pentru acel CUI.
- **cost:** certificatul, ~200–400 lei/an. API-ul ANAF nu se plătește.
- **⚠ expiră:** certificatul (1–3 ani) și autorizarea (~1 an, apoi se reface
  manual, tot cu certificatul în calculator). **O intervenție pe an.**
- **de reținut:** aplicația **descarcă** facturi. **Nu depune** nimic la ANAF.

## 8. Citirea automată a pozelor (Anthropic)

**Ia-o dacă:** clienții trimit **poze** de bonuri și facturi, nu PDF-uri.

- **cont:** console.anthropic.com, cu credit
- **credențiale:** o cheie de API
- **cost:** **da, pe utilizare.** Fiecare poză citită costă. Pune un plafon în
  contul Anthropic dacă vrei o limită fermă — aplicația mărginește costul unei
  singure cereri, nu totalul lunii.
- **⚠ confidențialitate:** pozele documentelor **părăsesc sediul cabinetului** și
  ajung la Anthropic. Este o decizie pe care o iei explicit.
- **fără ea:** PDF-urile cu text — cele emise de orice ERP, adică majoritatea — se
  citesc **local**, fără rețea și fără cost. Aceasta este configurația implicită
  și cea recomandată.

## 9. Asistentul care răspunde la întrebări (Anthropic, separat)

**Ia-l dacă:** vrei întrebări în limbaj liber („ce lipsește la clientul X").

- **cont:** același furnizor, **cheie separată** de cea de la §8 — deliberat: poți
  vrea un asistent fără ca documentele clienților să plece nicăieri
- **cost:** pe utilizare
- **fără el:** asistentul funcționează cu reguli deterministe, fără cont și fără
  să trimită nimic.

## 10. Stocare în cloud (S3) — alternativa la discul serverului

**Ia-o dacă:** nu vrei să ții documentele pe discul serverului.

- **furnizor:** AWS S3, Cloudflare R2, Supabase Storage, sau MinIO propriu
- **ce se creează:** un bucket **nepublic**, plus chei de acces dedicate
- **cost:** mic, dar pe volum
- **de reținut:** aici ajung **documentele contabile ale clienților**. Bucketul nu
  are voie să fie public — verifică cerând un fișier fără credențiale.

---

# NU ÎȚI TREBUIE (deși poate te aștepți)

Verificat prin căutare în tot codul:

| Serviciu | De ce nu |
|---|---|
| **Meta Business / WhatsApp API** | Nu există integrare. Butonul de WhatsApp deschide o conversație pe telefon, cu mesajul scris; nu trece prin server. Documentele primite pe WhatsApp se încarcă manual, cu proveniența notată. |
| **Twilio** | Nu se trimit SMS-uri și nu există integrare. |
| **Google Cloud / AWS Textract / Azure** | Nu există cod de OCR pentru ei. |
| **OpenAI / Azure OpenAI** | Au stat enumerate într-un fișier de configurare fără să existe în cod. Acum aplicația refuză să pornească cu ele. |
| **Redis / RabbitMQ** | Coada de procesare este un tabel PostgreSQL, deliberat. |
| **Sentry / serviciu de monitorizare** | Nu există integrare. Logurile sunt structurate și merg la ieșirea standard. **Aceasta este o lipsă reală** — vezi §11 de mai jos. |
| **Serviciu de plăți** | Aplicația ține evidența onorariilor; nu încasează bani. |
| **Analytics** | Nicio urmă către un terț. |
| **SAGA** | Nu există conversie. Vezi mai jos. |

---

# 11. Monitorizare — de decis

**Aplicația nu are astăzi nicio integrare de monitorizare.** Logurile sunt
structurate și merg la ieșirea standard; `/health/ready` spune dacă aplicația și
baza răspund.

**Ce lipsește și contează:** dacă workerul moare, documentele intră și rămân în
așteptare. Ecranul *Documente → În procesare* arată starea cozii și spune „cea mai
veche cerere așteaptă de 40 de minute" — dar **nu sună pe nimeni**. Cineva trebuie
să se uite.

**Minimul rezonabil**, fără să adaugi cod: un serviciu care interoghează
`https://domeniul-tău/health/ready` la fiecare câteva minute și trimite un email
când nu răspunde (UptimeRobot, Better Stack, Healthchecks.io — toate au plan
gratuit). Asta acoperă „aplicația a căzut", nu și „workerul s-a blocat".

---

# 12. Copiile de siguranță — obligatorii, și nu doar configurate

- **unde:** pe **alt** sistem decât cel care rulează aplicația
- **ce se copiază:** baza de date **și** fișierele documentelor. Una fără cealaltă
  nu reface nimic.
- **ordinea contează:** întâi baza, apoi fișierele. Invers, ajungi cu o bază care
  știe de documente ale căror fișiere lipsesc.
- **criptare:** copiile conțin datele financiare ale clienților. Criptează-le.
- **⚠ obligatoriu înainte de primul client real:** **restaurează o copie**, măcar
  o dată, pe o instalare de test. Procedura completă, cu comenzi, în
  [RUNBOOK.md](RUNBOOK.md). O copie care nu s-a restaurat niciodată nu este o
  copie; este o speranță.

Procedura a fost parcursă integral pe o instalare de test: copie, distrugere,
restaurare, verificare — 6 secunde, cu fișierele identice pe octet.

---

# 13. SAGA — ce trebuie să-mi dai tu

**Stare: neimplementat, deliberat.**

Formatul de import al SAGA nu este public. Un format ghicit ar produce fișiere
care se încarcă și pun cifre greșite în contabilitate — cel mai scump fel de
eșec, fiindcă nu se vede la timp.

**Ca să se poată face, îmi trebuie una dintre:**

1. **un fișier real exportat din SAGA** de la cabinet (orice lună, orice client),
   sau
2. documentația formatului de import, de la producător.

Cu oricare dintre ele, conversia este muncă de câteva zile și verificabilă.

**Până atunci**, ce se poate folosi imediat: exportul CSV al registrului lunii, în
formatul pe care Excel-ul românesc îl deschide corect.

---

# Ordinea în care le iei

1. domeniu + server + PostgreSQL + copii de siguranță → **aplicația funcționează**
2. SMTP → **poți cere documente clienților**
3. una dintre §5 sau §6 → **documentele vin singure pe email/OneDrive**
4. ANAF → **facturile electronice se descarcă singure**
5. §8, dacă clienții trimit poze
6. monitorizare

Fiecare pas se testează **cu un singur client**, urmărit, înainte de a-l porni
pentru tot cabinetul.
