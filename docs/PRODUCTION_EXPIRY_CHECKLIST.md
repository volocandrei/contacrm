# Ce expiră, și când

Tot ce are o dată de expirare într-o instalare ContaCRM. **Fiecare intrare de aici
se termină, la un moment dat, cu „nu mai merge X" fără ca nimeni să fi schimbat
nimic** — și de fiecare dată cauza pare altceva.

Completează coloanele goale la punerea în funcțiune și pune-le într-un calendar,
cu o alarmă cu **30 de zile înainte**.

**Niciun secret nu se scrie în acest fișier.** Doar unde este configurat, cine
răspunde, și când expiră.

---

## Tabelul de completat

| # | Ce expiră | Unde este configurat | Cine îl reînnoiește | Valabilitate tipică | Expiră la | Ce se strică fără el |
|---|---|---|---|---|---|---|
| 1 | Certificat TLS al domeniului | proxy / platformă | administrator infra | 90 zile (Let's Encrypt, automat) | ________ | **Nimeni nu se poate autentifica**: cookie-urile de sesiune sunt `Secure` în producție |
| 2 | Înregistrarea domeniului | registrar | proprietar | 1 an | ________ | Aplicația devine inaccesibilă, linkurile trimise clienților mor |
| 3 | `MS_CLIENT_SECRET` (Entra ID) | mediul aplicației | administrator Microsoft 365 | **6, 12 sau 24 luni** | ________ | Nu mai vin documente din OneDrive **și** de pe email |
| 4 | Certificat digital calificat (ANAF) | calculatorul administratorului | proprietar | 1–3 ani | ________ | Autorizarea ANAF nu se mai poate reface |
| 5 | Autorizarea ANAF (refresh token) | baza de date, criptat | administrator | **~1 an** | ________ | Facturile electronice nu se mai descarcă din SPV |
| 6 | `ANAF_CLIENT_SECRET` | mediul aplicației | proprietar | după politica ANAF | ________ | Autorizarea eșuează |
| 7 | Parolă de aplicație IMAP | baza de date, criptat | administrator | până e revocată | ________ | Nu mai vin documente de pe email |
| 8 | Parolă / cheie SMTP | mediul aplicației | administrator | până e revocată | ________ | Nu mai pleacă solicitări și memento-uri |
| 9 | `AI_API_KEY` (Anthropic) | mediul aplicației | proprietar | până e revocată; **creditul se epuizează** | ________ | Pozele rămân necitite (PDF-urile cu text merg mai departe) |
| 10 | `ASSISTANT_API_KEY` | mediul aplicației | proprietar | idem | ________ | Asistentul cade pe motorul cu reguli |
| 11 | Chei S3 | mediul aplicației | administrator infra | după politica furnizorului | ________ | **Documentele nu se mai pot citi sau scrie** |
| 12 | Parola utilizatorului de bază de date | mediul aplicației | administrator infra | după politica cabinetului | ________ | Aplicația nu mai pornește |

---

## Cele două care nu expiră, dar se rotesc

Nu au dată, dar au o procedură — și una dintre ele are o capcană.

### `SECRET_KEY`

Semnează tokenurile de sesiune. Se rotește **după o scurgere**. Rotirea
**deconectează pe toată lumea** — acceptabil, dar trebuie știut dinainte, nu
descoperit luni dimineața.

### `DRIVE_TOKEN_KEY` — capcana

Criptează, înainte de a atinge baza de date: refresh tokenul Microsoft, refresh
tokenul ANAF, și parolele cutiilor IMAP.

**Este separată de `SECRET_KEY` tocmai ca să nu se rotească odată cu ea.** Dacă o
pierzi sau o schimbi, datele criptate **nu se mai pot descifra**: fiecare cabinet
trebuie să reconecteze contul Microsoft, să refacă autorizarea ANAF (cu
certificatul) și să reintroducă parolele IMAP. Nu există recuperare.

Păstreaz-o în managerul de secrete, inclus în copia de siguranță a secretelor —
separat de copia bazei.

### `CRON_SECRET`

Se rotește oricând. După rotire, actualizează-l și în planificator, altfel
sincronizările se opresc **tăcut**: rutele răspund 404, iar 404 nu alarmează pe
nimeni.

---

## Cum se verifică, fără să aștepți să se strice

```bash
# 1. Certificatul TLS — câte zile mai are
echo | openssl s_client -connect domeniul-tău:443 2>/dev/null \
  | openssl x509 -noout -enddate

# 2. Aplicația și baza răspund
curl -sS https://domeniul-tău/health/ready

# 3. Ce configurare rulează de fapt (fără secrete: doar nume și provideri)
#    Administrare → Setări, în interfață.
```

Pentru integrări, **ecranul lor spune starea**: *Administrare → Surse documente*
și *Administrare → e-Factura* arată ultima sincronizare reușită și ultima eroare.
O integrare care nu a mai adus nimic de o săptămână se vede acolo înainte să
întrebe un client.

---

## Ordinea în care se descoperă, dacă nimeni nu se uită

Din experiența acestor sisteme, în ordinea probabilității:

1. **`MS_CLIENT_SECRET` a expirat** (luna 6 sau 12) → „nu mai vin documentele";
2. **autorizarea ANAF a expirat** (după un an) → „nu mai vin facturile";
3. **creditul Anthropic s-a epuizat** → „nu mai citește pozele";
4. **certificatul TLS** — de obicei automat, dar când nu e, nimeni nu se poate
   autentifica.

Toate patru arată la fel din partea utilizatorului: *ceva nu mai merge, deși
nimeni n-a schimbat nimic*. De aceea tabelul de mai sus merită completat înainte,
nu după.
