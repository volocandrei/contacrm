# Runbook de incidente

Ce faci când ceva nu merge. Fiecare incident are aceeași structură: **semne →
primul lucru → diagnostic → reparare → când escaladezi → după**.

Comenzile presupun că ești pe serverul aplicației, cu `DATABASE_URL` și
`STORAGE_PATH` din mediul de producție.

> **Regula numărul unu:** nu șterge nimic ca să repari ceva. Documentele
> contabile nu se pot reface. Dacă o comandă are `DROP`, `rm` sau `--force`,
> oprește-te și citește de două ori.

---

## Verificarea de treizeci de secunde

Înainte de orice diagnostic, cele trei întrebări:

```bash
curl -s https://domeniul-tău/health/ready    | head -c 300   # aplicația + baza
curl -s https://domeniul-tău/health/workers  | head -c 300   # mai procesează cineva?
curl -sI https://domeniul-tău/ | head -1                     # ajunge cineva la ea?
```

---

## 1. Aplicația nu răspunde

**Semne:** nimeni nu se poate autentifica; `/health/ready` nu răspunde sau dă
timeout; monitorul a sunat.

**Primul lucru:** verifică dacă procesul trăiește.

```bash
docker compose ps            # sau: systemctl status contacrm
docker compose logs --tail=100 backend
```

**Diagnostic:**

| Ce vezi | Cauza probabilă |
|---|---|
| Procesul lipsește | a căzut sau nu a pornit după deploy |
| `Configurare invalidă pentru producție: …` | o variabilă lipsă sau greșită — mesajul spune care |
| `connection refused` către bază | vezi incidentul 2 |
| Procesul există, dar nu răspunde | epuizare de conexiuni sau blocare |

**Reparare:** repornește; dacă nu pornește, mesajul de la pornire spune exact ce
lipsește — `assert_production_ready()` refuză să pornească pe jumătate.

**Escaladare:** dacă nu pornește după două încercări și mesajul nu este despre
configurare.

**După:** dacă a căzut singură, caută în jurnal ce s-a întâmplat înainte.

---

## 2. Baza de date indisponibilă

**Semne:** `/health/ready` → 503 cu `"database": false`.

**Primul lucru:**

```bash
psql "$DATABASE_URL" -c "select 1"
```

**Diagnostic:** serverul de bază oprit; parola schimbată; disc plin pe serverul
de bază; prea multe conexiuni; rețea.

**Reparare:** pornește baza, sau repară conexiunea. **Nu** rula migrări ca să
„repari" — o bază care nu răspunde nu are nevoie de schemă nouă.

**Escaladare:** dacă baza a pierdut date, treci direct la incidentul 13 și la
[RUNBOOK.md](RUNBOOK.md) pentru restaurare.

**După:** verifică `db_pool_size` și `db_max_overflow` dacă a fost epuizare de
conexiuni; pune `DB_EXTERNAL_POOLER=true` dacă e un pooler în față.

---

## 3. Workerul mort sau blocat

**Semne:** `/health/workers` → 503; documentele rămân în „Primit"; ecranul
*Documente → În procesare* spune că cea mai veche cerere așteaptă de mult.

**Primul lucru:**

```bash
curl -s https://domeniul-tău/health/workers          # cât de vechi e semnul
docker compose logs --tail=100 worker
docker compose restart worker
```

**Diagnostic:** un worker **blocat** este mai frecvent decât unul mort: procesul
există, dar stă într-un apel de rețea care nu se mai întoarce. De aceea semnul de
viață se scrie înaintea muncii — un worker blocat nu mai bate.

**Reparare:** după repornire, repune în coadă ce a rămas pe drum:

```bash
uv run --directory backend python -m app.cli recover-processing
```

Joburile rămase `RUNNING` de la procesul mort se readuc în `PENDING`. `attempt`
**nu** crește: nu este o încercare nouă, este aceeași care nu a apucat să se
termine.

**Escaladare:** dacă workerul moare din nou în câteva minute, oprește-l și
escaladează — o buclă de repornire pe același document poate consuma bani la
extragere.

**După:** verifică ce document îl bloca. Ecranul de procesare arată eșecurile
recente cu motivul scris.

---

## 4. Discul plin

**Semne:** încărcările eșuează; în jurnal `StorageError`, `No space left on
device`.

**Primul lucru:**

```bash
df -h                                  # cât a mai rămas
du -sh "$STORAGE_PATH"/* | sort -h | tail -10
```

**Diagnostic:** documentele cresc monoton — nimic nu le șterge automat. Vezi și
copiile de siguranță, dacă stau pe același disc (nu ar trebui).

**Reparare, în ordinea siguranței:**

1. mută copiile de siguranță pe alt volum, dacă sunt aici — **nu le șterge**;
2. extinde volumul;
3. mută stocarea pe un disc mai mare, apoi `check-storage` (mai jos).

**Ce NU faci:** nu șterge fișiere din `STORAGE_PATH`. Fiecare are un rând în bază
care îl așteaptă.

**Escaladare:** dacă discul e plin și nu poate fi extins în aceeași zi.

**După:** pune un prag de avertizare la 20% liber — vezi
[PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md).

---

## 5. Stocare coruptă sau fișiere lipsă

**Semne:** un document nu se deschide; „Fișierul documentului nu mai există în
stocare"; după o restaurare.

**Primul lucru — comanda care spune adevărul:**

```bash
uv run --directory backend python -m app.cli check-storage
```

Parcurge fiecare document neșters și verifică dacă fișierul lui — originalul,
plus copia din arhivă — există și are dimensiunea din baza de date. **Nu scrie
nimic.** Iese cu cod diferit de zero dacă a găsit ceva.

**Diagnostic:**

| Ce raportează | Ce înseamnă |
|---|---|
| `LIPSĂ` | baza și stocarea sunt din momente diferite — de obicei o restaurare făcută în ordinea greșită |
| `MĂRIME` | fișierul a fost înlocuit sau trunchiat |

**Reparare:** restaurează stocarea din copia potrivită momentului bazei —
[RUNBOOK.md](RUNBOOK.md). Ordinea contează: baza întâi, fișierele după.

**Escaladare:** dacă lipsesc documente și nu există copie din care să vină
înapoi — este pierdere de date, anunță imediat proprietarul.

**După:** verifică ordinea copiilor. Baza la T1, fișierele la T2 > T1.

---

## 6. Emailurile nu mai pleacă

**Semne:** clienții spun că nu au primit nimic; ecranul de remindere arată
eșecuri.

**Primul lucru:** verifică dacă trimiterea este pornită.

```bash
# In aplicatie: Administrare -> Setari. Cauta NOTIFICATIONS_ENABLED si SMTP_HOST.
docker compose logs backend | grep -i "mail\|smtp" | tail -20
```

**Diagnostic:**

| Ce vezi | Cauza |
|---|---|
| „trimiterea nu este configurată" | `NOTIFICATIONS_ENABLED=false` sau `SMTP_HOST` gol |
| autentificare respinsă | parola contului sau parola de aplicație s-a schimbat |
| mesajele pleacă, dar nu ajung | SPF/DKIM/DMARC — ajung în spam |

**Reparare:** corectează credențialele; trimite un test **către o adresă a
cabinetului** înainte de a scrie unui client.

**Escaladare:** dacă domeniul a ajuns pe o listă de blocare.

**După:** dacă erau mesaje în așteptare, retrimite-le din ecranul de remindere.
Nu pleacă de două ori: blocarea per organizație împiedică asta.

---

## 7. Autentificarea Microsoft a expirat

**Semne:** nu mai vin documente din OneDrive **și** de pe email, deodată;
ecranul *Administrare → Surse documente* arată o eroare.

**Cauza, în majoritatea cazurilor:** **client secretul din Entra ID a expirat.**
Este cea mai frecventă cauză de „nu mai vin documentele" și se întâmplă la 6, 12
sau 24 de luni de la creare.

**Reparare:**

1. Azure Portal → Entra ID → App registrations → aplicația → Certificates &
   secrets → **New client secret**;
2. pune noul `MS_CLIENT_SECRET` în mediu și repornește;
3. dacă și consimțământul a expirat, un administrator reconectează contul din
   *Administrare → Surse documente*;
4. verifică: forțează o sincronizare și urmărește să apară documente.

**Escaladare:** dacă nu ai acces la Azure Portal.

**După:** notează noua dată de expirare în
[PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md) **și** în
calendar, cu alarmă cu 30 de zile înainte.

---

## 8. ANAF indisponibil

**Semne:** nu mai vin facturi electronice; ecranul *e-Factura* arată erori.

**Diagnostic — trei cauze, în ordinea probabilității:**

| Cauză | Cum o recunoști |
|---|---|
| Autorizarea a expirat (~1 an) | eroare de autentificare; trebuie refăcută **cu certificatul** |
| ANAF este jos | erori de rețea; se întâmplă și se rezolvă singur |
| `ANAF_ENVIRONMENT=test` | „nicio factură" la nesfârșit, **fără nicio eroare** |

**Reparare:** pentru autorizare, un administrator o reface din *Administrare →
e-Factura*, cu certificatul calificat în calculator. Pentru indisponibilitate,
așteaptă: turul următor continuă de unde a rămas, iar un eșec **nu** marchează
documente ca eșuate.

**Escaladare:** dacă certificatul a expirat — trebuie cumpărat altul, durează.

**După:** verifică `ANAF_ENVIRONMENT=prod`. O instalare lăsată pe `test`
raportează liniștit că nu are nimic de adus.

---

## 9. Furnizorul de AI indisponibil

**Semne:** pozele și scanurile rămân necitite; documentele ajung la verificare cu
câmpurile goale.

**Ce NU se strică:** PDF-urile cu text — cele emise de orice ERP, adică
majoritatea — se citesc **local**, fără rețea. Cabinetul poate lucra mai departe.

**Diagnostic:** cheie invalidă, credit epuizat, sau 429/500 de la furnizor.

**Reparare:** verifică creditul în consola furnizorului. Documentele afectate se
reprocesează din ecranul lor, după ce revine.

**Escaladare:** rar necesară — nu blochează cabinetul.

**După:** dacă s-a epuizat creditul, pune un plafon în contul furnizorului.

---

## 10. Documente blocate în procesare

**Semne:** documente rămase în „Primit" sau „În procesare"; coada crește.

**Primul lucru:** deschide *Documente → În procesare*. Panoul spune verdictul
într-o propoziție: câte așteaptă, câte s-au blocat, de când așteaptă cea mai
veche, și ce a eșuat recent, cu motivul scris.

**Diagnostic:**

| Ce arată panoul | Ce este |
|---|---|
| „cea mai veche așteaptă de N minute" | procesarea nu rulează → incidentul 3 |
| „N cereri au rămas pornite" | procesul a murit la mijloc |
| eșecuri recente cu motiv | documentele în sine, nu sistemul |

**Reparare:** `recover-processing` pentru cele blocate; reprocesare individuală
pentru cele eșuate, de pe documentul lor.

**După:** dacă același document eșuează de trei ori, deschide-l. `MAX_PROCESSING_ATTEMPTS`
îl lasă în `ERROR` — corect: o buclă infinită pe un document stricat ar consuma
bani la fiecare încercare.

---

## 11. Documente duplicate

**Semne:** același document apare de două ori.

**Diagnostic:** detecția de duplicate lucrează pe **conținut** (SHA-256), nu pe
nume. Două fișiere identice pe octet se marchează automat. Două scanări diferite
ale aceleiași facturi sunt fișiere diferite — acelea le vede un om.

**Ce nu este un duplicat:** perechea XML + PDF a aceleiași facturi electronice.
Amândouă rămân, legate una de alta: XML-ul este originalul fiscal, PDF-ul este ce
se poate privi. Vezi [EFACTURA.md](EFACTURA.md).

**Reparare:** marchează manual duplicatul, din ecranul documentului. **Nu se
șterge fizic** — rămâne, marcat, cu trimitere la original.

---

## 12. Clasificare greșită a documentelor

**Semne:** o factură a intrat ca bon, sau clientul e greșit.

**Ce nu faci:** nu schimba regulile pentru un caz. Corectează documentul.

**Reparare:** din ecranul de verificare — tipul, clientul, câmpurile. Fiecare
corectură se scrie în istoricul documentului, cu cine a făcut-o. Sistemul învață
expeditorii, deci același expeditor va nimeri clientul data viitoare.

**După:** dacă se repetă la același client, verifică aliasurile lui în fișa
clientului.

---

## 13. Copia de siguranță a eșuat

**Semne:** jobul de backup a raportat eroare, sau nu a rulat.

**Primul lucru:** verifică **acum** dacă ultima copie bună există și cât de
veche este. O copie de acum trei zile înseamnă că poți pierde trei zile de
muncă.

**Reparare:** repară jobul, apoi rulează o copie manuală imediat —
[RUNBOOK.md](RUNBOOK.md).

**Escaladare:** dacă nu există nicio copie recentă, este cel mai grav incident
din acest document. Anunță proprietarul.

**După — pasul care se sare cel mai des:** **restaurează** copia nouă pe o
instalare de test și rulează `check-storage`. O copie care nu s-a restaurat
niciodată nu este o copie.

---

## 14. Suspiciune de incident de securitate

**Semne:** autentificări nereușite repetate; un cont care se comportă altfel; un
secret publicat din greșeală.

**Primul lucru — în ordinea asta:**

1. **Nu șterge nimic.** Jurnalul de audit este proba.
2. Dezactivează contul suspect: *Administrare → Utilizatori*.
3. Revocă-i sesiunile — resetarea parolei de către administrator revocă
   **toate** sesiunile acelui utilizator.

**Diagnostic:** *Administrare → Audit* arată cine, ce, când, de la ce adresă.
Jurnalul aplicației poartă `request_id` și `user_id` pe fiecare cerere.

**Dacă un secret a fost expus:**

| Secret | Ce faci | Efect |
|---|---|---|
| `SECRET_KEY` | generează altul, repornește | **toată lumea este deconectată** |
| `DRIVE_TOKEN_KEY` | **nu-l schimba fără să citești** [PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md) | datele criptate **nu se mai pot descifra**; toate integrările se reconectează |
| `CRON_SECRET` | generează altul, actualizează planificatorul | sincronizările se opresc tăcut dacă uiți planificatorul |
| chei de API | revocă la furnizor, pune altele | integrarea respectivă se oprește până le pui |
| parola bazei | schimb-o, actualizează `DATABASE_URL` | aplicația nu pornește până o actualizezi |

**Escaladare:** orice suspiciune că datele unui client au fost citite din afară.

**După:** notează ce s-a întâmplat și ce s-a schimbat. Dacă un secret a fost
vreodată comis în git, **rotirea este obligatorie** — istoria îl păstrează.

---

## Când escaladezi, indiferent de incident

- pierdere de date sau documente care nu se pot reface;
- suspiciune că cineva din afară a citit date ale clienților;
- aplicația jos de peste o oră în timpul programului;
- copii de siguranță lipsă mai vechi de 24 de ore;
- orice lucru pe care nu-l înțelegi și care atinge documentele.

**Cui:** administratorul cabinetului, apoi proprietarul aplicației. Numele și
telefoanele se completează la punerea în funcțiune, aici:

| Rol | Nume | Contact |
|---|---|---|
| Administrator aplicație | ________ | ________ |
| Responsabil infrastructură | ________ | ________ |
| Proprietar cabinet | ________ | ________ |
