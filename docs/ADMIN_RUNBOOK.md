# Ghidul administratorului

Pentru cine ține aplicația în funcțiune. Presupune acces la server și la ecranele
de administrare.

Când ceva s-a stricat deja:
[PRODUCTION_INCIDENT_RUNBOOK.md](PRODUCTION_INCIDENT_RUNBOOK.md).

---

## Utilizatori și roluri

**Administrare → Utilizatori**

| Rol | Ce poate |
|---|---|
| `ADMIN` | tot, inclusiv utilizatori, integrări, setări |
| `ACCOUNTANT` | clienți, documente, perioade, termene, rapoarte |
| `REVIEWER` | verifică și aprobă documente |
| `OPERATOR` | încarcă și pregătește documente, fără aprobare |
| `VIEWER` | citește |

Matricea completă: **Administrare → Roluri** — arată ce poate fiecare rol, nu
doar al tău.

### Un coleg nou

1. *Administrare → Utilizatori → Adaugă*;
2. alege rolul **cel mai mic** care îi permite să lucreze;
3. parola inițială o pui tu, iar el o schimbă la prima intrare din
   *Administrare → Securitate*.

Politica de parole (minimum 12 caractere, cel puțin 5 diferite, fără fragmente
din nume sau email) se aplică peste tot — inclusiv la primul administrator creat
din linia de comandă.

### Un coleg pleacă

**Dezactivează contul**, nu-l șterge: istoricul lui trebuie să rămână legat de un
nume. Dezactivarea îi închide accesul imediat.

Dacă bănuiești că parola i-a fost compromisă, **resetează-i parola** — asta îi
revocă **toate** sesiunile deschise.

### Sesiuni

**Administrare → Securitate**: sesiunile tale active, cu dispozitiv și ultima
folosire, și butonul care le închide pe toate celelalte.

---

## Primul cont, pe o instalare nouă

Nu există niciun drum prin interfață care să creeze primul utilizator — orice
creare de utilizator cere deja un utilizator autentificat.

```bash
uv run --directory backend python -m app.cli sync-roles
uv run --directory backend python -m app.cli create-admin
```

Comanda cere email, nume și parolă **de la tastatură**. Parola nu se dă niciodată
ca argument: argumentele ajung în istoricul shell-ului și în lista de procese.

Comanda **nu resetează** parole. Dacă adresa există deja, se oprește fără să
atingă contul — nu este o portiță.

Creează și organizația (dacă nu există), tipurile de documente și catalogul de
declarații.

> `seed-dev` **refuză** să ruleze în producție. Parolele lui sunt publice, iar
> datele sunt inventate.

---

## Clienți

Se adaugă din interfață, sau în masă din CSV: *CRM → Clienți → Import*. Importul
se citește de două ori — prima trecere spune ce s-ar întâmpla, fără să scrie
nimic.

**După fiecare client nou**, două lucruri care altfel îl fac invizibil:

- **ce așteptăm lunar** — altfel nu apare în „Documente lipsă";
- **ce declarații depune** — altfel nu apare în „Termene".

Pentru clienți cu același profil: șabloane de așteptări.

---

## Integrări

**Administrare → Surse documente** și **Administrare → e-Factura**

Fiecare ecran arată dacă integrarea este configurată, ultima sincronizare
reușită și ultima eroare. **O integrare care nu a mai adus nimic de o săptămână
se vede acolo** înainte să întrebe un client.

Ce trebuie obținut pentru fiecare, cu pași:
[PRODUCTION_SETUP_ACCOUNTS.md](PRODUCTION_SETUP_ACCOUNTS.md).

### Regula care se uită

**Client secretul Microsoft expiră** — la 6, 12 sau 24 de luni. Este cea mai
frecventă cauză de „nu mai vin documentele". Notează data în calendar când
conectezi contul: [PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md).

La fel, autorizarea ANAF ține aproximativ un an și se reface manual, cu
certificatul calificat în calculator.

---

## Configurarea

**Administrare → Setări** arată configurarea după care rulează procesul —
providerii, pragurile, comutatoarele. **Fără secrete**: valorile sensibile nu ies
niciodată pe acolo.

Se schimbă din mediu, nu din interfață, iar aplicația se repornește. Lista
completă a variabilelor:
[PRODUCTION_ENVIRONMENT_VARIABLES.md](PRODUCTION_ENVIRONMENT_VARIABLES.md).

Aplicația **refuză să pornească** în producție cu o configurare periculoasă:
cheie implicită, `PUBLIC_BASE_URL` pe localhost, provider de extragere care
inventează date, sau un provider necunoscut. Mesajul spune exact ce lipsește.

---

## Copiile de siguranță

Procedura completă, cu comenzi: [RUNBOOK.md](RUNBOOK.md).

Ce trebuie să fie adevărat:

```text
[ ] Copie zilnica a bazei, automata
[ ] Copie a fisierelor, DUPA cea a bazei
[ ] Copiile stau pe alt sistem decat aplicatia
[ ] Copiile sunt criptate
[ ] O restaurare a fost facuta cel putin o data, cu check-storage trecut
```

**Ordinea contează.** Baza la T1, fișierele la T2 > T1. Invers, ajungi cu o bază
care știe de documente ale căror fișiere lipsesc.

Verificarea care spune dacă cele două sunt din același moment:

```bash
uv run --directory backend python -m app.cli check-storage
```

Iese cu cod diferit de zero dacă a găsit ceva. **O restaurare nu este terminată
până când comanda asta nu trece.**

---

## Monitorizare

Ce trebuie configurat, cu valori:
[PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md).

Pe scurt — două adrese urmărite de un serviciu extern:

| Adresă | Interval | 503 înseamnă |
|---|---|---|
| `/health/ready` | 1–5 min | aplicația sau baza sunt jos |
| `/health/workers` | 5 min | nu mai procesează nimeni documentele |

**Aplicația nu trimite alerte singură.** Fără monitorul extern, un worker mort
se descoperă a doua zi.

---

## Planificatorul (cron)

Trei rute interne, chemate periodic, care se legitimează cu `CRON_SECRET`:

| Rută | Ce face | Cât de des |
|---|---|---|
| `/api/v1/internal/run-queue` | procesează coada, întreabă sursele externe | 1–5 minute |
| `/api/v1/internal/daily-digest` | rezumatul zilnic către cabinet | o dată pe zi |
| `/api/v1/internal/reminders` | memento-urile către clienți | o dată pe zi |

Fără secret răspund **404, nu 401** — un 401 ar confirma că ruta există.

**`CRON_SECRET` gol înseamnă oprit**: rutele refuză orice, inclusiv o cerere
corectă. Dacă rotești secretul, actualizează-l **și** în planificator, altfel
sincronizările se opresc tăcut.

Alternativa, dacă nu ai cron: workerul rulat ca proces continuu
(`python -m app.worker`) face aceeași muncă singur.

---

## Comenzi utile

```bash
# Rolurile, dupa o actualizare care le schimba
uv run --directory backend python -m app.cli sync-roles

# Joburile ramase de la un proces mort, repuse in coada
uv run --directory backend python -m app.cli recover-processing

# Baza si stocarea se potrivesc?
uv run --directory backend python -m app.cli check-storage

# La ce migrare este baza
uv run --directory backend alembic current
```

---

## Actualizări

Ordinea și verificările: [PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md).

Trei lucruri care nu se sar:

1. **copie de siguranță înainte de orice**;
2. **migrările înainte de a promova versiunea nouă**, cu workerul oprit;
3. **proba de fum după**, cu ochii pe ecran.

Aplicația **nu suportă deploy fără întrerupere** și nu se pretinde că suportă.
Fereastră așteptată: 5–15 minute, anunțată, în afara programului.

---

## Securitate — ce verifici periodic

```text
[ ] Nimeni nu are drepturi mai mari decat ii trebuie
[ ] Conturile celor plecati sunt dezactivate
[ ] Certificatul TLS nu expira curand
[ ] Datele de expirare din PRODUCTION_EXPIRY_CHECKLIST.md sunt in calendar
[ ] Copiile de siguranta ruleaza si au fost restaurate cel putin o data
[ ] Jurnalul de audit nu are actiuni pe care nu le recunosti
[ ] Baza de date nu este accesibila din internet
[ ] Bucketul de stocare (daca folosesti S3) nu este public
```

Dacă bănuiești un incident de securitate: incidentul 14 din
[PRODUCTION_INCIDENT_RUNBOOK.md](PRODUCTION_INCIDENT_RUNBOOK.md). Primul lucru
acolo este **nu șterge nimic** — jurnalul de audit este proba.
