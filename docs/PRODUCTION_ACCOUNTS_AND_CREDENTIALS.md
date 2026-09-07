# Conturi și credențiale pentru producție

Ce trebuie obținut din exterior înainte ca aplicația să ruleze pentru un cabinet
real, cine dă fiecare lucru, și ce se întâmplă fără el.

**Regula generală a proiectului:** fără o credențială, funcția respectivă **spune
că nu este configurată** — nu se oferă și apoi eșuează. Se poate porni cu jumătate
din listă.

> Lista detaliată, cu pașii de obținere, este în [`CREDENTIALE.md`](CREDENTIALE.md).
> Fișierul de față este **lista de bifat înainte de livrare**, cu starea fiecărei
> integrări așa cum este ea astăzi, verificată.

---

## 1. Fără de care nu pornește

| Ce | De unde | Fără el |
|---|---|---|
| Domeniu + certificat TLS | registrar / Let's Encrypt | cookie-urile de sesiune sunt `Secure` în producție: fără HTTPS nu există autentificare |
| PostgreSQL 17 | găzduire sau serverul cabinetului | nu pornește nimic |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(64))"` | **pornirea se oprește** |
| `PUBLIC_BASE_URL` | adresa reală a aplicației | **pornirea se oprește**: linkurile trimise clienților n-ar duce nicăieri |
| Stocare documente | disc local sau S3 compatibil | nu se poate încărca nimic |
| `DRIVE_TOKEN_KEY` | `Fernet.generate_key()` | nu se poate lega nicio integrare externă |
| `CRON_SECRET` | un secret aleatoriu | rutele periodice nu se pot apela; nimic nu se sincronizează singur |

## 2. Prima parolă de administrator

Se pune la instalare, de la tastatură:

```bash
uv run python -m app.cli create-admin
```

Comanda **cere parola interactiv**, niciodată dintr-un argument: argumentele ajung
în istoricul shell-ului și în lista de procese.

Parola trebuie să aibă minimum 12 caractere, cel puțin 5 caractere diferite, și
să nu conțină numele sau adresa contului. Nu se cere majusculă sau simbol —
motivul este scris în `backend/app/domain/passwords.py`.

**Se poate schimba din aplicație**, din *Administrare → Securitate*. Schimbarea
cere parola actuală și închide toate celelalte sesiuni.

## 3. Integrări externe — starea reală

| Integrare | Ce cere | Stare |
|---|---|---|
| **SMTP** (solicitări, remindere, rezumat zilnic) | server, utilizator, parolă | `NEVERIFICAT — NECESITĂ CREDENȚIALE` |
| **IMAP** (email de la orice furnizor) | cutie + **parolă de aplicație** | `NEVERIFICAT — NECESITĂ CREDENȚIALE` |
| **Microsoft Graph** (OneDrive + email M365) | aplicație în Entra ID, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` | `NEVERIFICAT — NECESITĂ CREDENȚIALE` |
| **e-Factura / SPV ANAF** | aplicație OAuth ANAF + **certificat digital calificat** înrolat în SPV | `NEVERIFICAT — NECESITĂ CREDENȚIALE` |
| **Citire documente cu model** (`vision`, `hybrid`) | `AI_API_KEY` | `NEVERIFICAT — NECESITĂ CREDENȚIALE` |
| **Asistent cu model** | `ASSISTANT_API_KEY` | `NEVERIFICAT — NECESITĂ CREDENȚIALE` |
| **WhatsApp — trimitere automată** | — | `NEIMPLEMENTAT`. Există doar linkul `wa.me`, compus din numărul de pe fișă |
| **SAGA** | — | `NEIMPLEMENTAT`. Lipsește un fișier de import model de la un cabinet care folosește SAGA |

Ce **s-a** verificat pentru fiecare integrare neconfirmată: interfața, dublura de
test, tratarea erorilor, reluarea, izolarea între cabinete și comportarea turului
periodic când un cabinet cade. Ce nu s-a putut: că serverul din partea cealaltă
răspunde așa cum credem.

### Două condiții ANAF care nu se rezolvă din configurare

1. Autorizarea cere **certificatul digital calificat înrolat în SPV**, prezentat
   de browser. Se face o dată pe an, de la calculatorul cu tokenul USB în port.
2. Fiecare client trebuie să depună **împuternicirea în SPV** (formular 150) pentru
   certificatul cabinetului. Fără ea, ANAF nu întoarce eroare — întoarce gol.

## 4. Ce nu are nevoie de niciun cont

- încărcarea documentelor și arhivarea lor;
- citirea facturilor electronice primite ca fișier (XML UBL), **inclusiv liniile
  cu cota de TVA pe fiecare produs**;
- citirea stratului de text al PDF-urilor (`pdf_text`);
- linkul de trimitere către client;
- asistentul, pe motorul cu reguli;
- toate rapoartele și exporturile.

Un cabinet poate lucra util **din prima zi**, fără nicio credențială externă.

## 5. Operațional

| Ce | De ce |
|---|---|
| Copii de siguranță pentru **bază** și pentru **documente** | Procedura, cu comenzi, în [`RUNBOOK.md`](RUNBOOK.md). Backupul bazei singur **nu** este suficient |
| Un loc unde rulează cronul | fără el nu se sincronizează nimic și nu pleacă niciun reminder |
| Monitorizare | logurile sunt structurate, la `stdout`. Export către Sentry/OTLP: `NEIMPLEMENTAT` |
| Rotația secretelor | `SECRET_KEY` se rotește după o scurgere; `DRIVE_TOKEN_KEY` **nu** trebuie rotită odată cu ea, altfel toate integrările cer reconectare |

## 6. GDPR — ce trebuie decis, nu configurat

- **`OCR_PROVIDER=vision` sau `hybrid` trimit documentul în afara cabinetului**,
  la furnizorul modelului. Pentru un cabinet de contabilitate este o decizie cu
  implicații legale. Implicit rămâne `local`, care nu trimite nimic.
- **Retenția automată nu există** (`NEIMPLEMENTAT`). Ștergerea documentelor vechi
  se face de mână, de un om, cu urmă în jurnal.
- Datele personale din documente nu părăsesc serverul decât prin exporturile pe
  care le cere explicit cineva, și fiecare export lasă urmă în jurnalul de audit.
