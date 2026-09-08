# Documentația, pe întrebări

Sunt douăzeci de fișiere aici. Nu se citesc toate. Deschide-l pe cel care
răspunde la întrebarea ta.

## „Vreau să pornesc aplicația pentru un cabinet real"

1. **[PRODUCTION_SETUP_ACCOUNTS.md](PRODUCTION_SETUP_ACCOUNTS.md)** — ce conturi
   îmi trebuie, scris pentru proprietar, nu pentru un programator. **Începe de
   aici.**
2. **[PRODUCTION_LAUNCH_CHECKLIST.md](PRODUCTION_LAUNCH_CHECKLIST.md)** — ce
   trebuie să fie adevărat înainte de primul client, cu trei porți **STOP** și o
   listă de bifat pentru tipărit.
3. **[DEPLOY.md](DEPLOY.md)** — cum se pune efectiv în funcțiune, pas cu pas.
4. **[PRODUCTION_ENVIRONMENT_VARIABLES.md](PRODUCTION_ENVIRONMENT_VARIABLES.md)** —
   toate variabilele, cu rol, implicit și care sunt secrete. **Doar nume, nicio
   valoare.**
5. **[PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md)** — ce
   expiră și când. Completează-l și pune-l în calendar.
6. **[PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md)** — ce trebuie să
   urmărească un serviciu extern ca o problemă să sune un om. **Aplicația nu
   alertează singură.**
7. **[PRODUCTION_RELEASE_GATE.md](PRODUCTION_RELEASE_GATE.md)** — ce se face în
   ziua deployului, în ordine, plus rollback.
8. **[RELEASE_MANIFEST.md](RELEASE_MANIFEST.md)** — ce anume se lansează: commit,
   migrare, dependențe, limitări cunoscute.

## „Ce servicii externe folosește, de fapt?"

- **[PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md](PRODUCTION_EXTERNAL_SERVICES_INVENTORY.md)**
  — inventarul complet, derivat din cod: fiecare serviciu, cu adrese, conturi,
  credențiale, ce date pleacă la el, și ce se strică fără el. Inclusiv lista a
  **ce nu folosește**, ca nimeni să nu deschidă conturi degeaba.
- **[PRODUCTION_API_CONNECTION_MATRIX.md](PRODUCTION_API_CONNECTION_MATRIX.md)** —
  aceleași legături, într-un tabel: direcție, protocol, autentificare, endpoint.
- **[INTEGRATIONS.md](INTEGRATIONS.md)** — **de ce** fiecare integrare are starea
  de verificare pe care o are, și ce anume s-a verificat din ea.
- **[CREDENTIALE.md](CREDENTIALE.md)** — pașii de obținere a fiecărei credențiale.
- **[PRODUCTION_ACCOUNTS_AND_CREDENTIALS.md](PRODUCTION_ACCOUNTS_AND_CREDENTIALS.md)**
  — lista scurtă de bifat la livrare.

## „Este gata de producție?"

- **[FINAL_PRODUCTION_BUILD.md](FINAL_PRODUCTION_BUILD.md)** — raportul final și
  **poarta de Go-Live**: ce s-a verificat rulând, ce nu s-a putut, blocantele pe
  priorități, și verdictul. Cele două concluzii — aplicația și integrările — sunt
  separate deliberat.
- **[FINAL_PRODUCTION_AUDIT.md](FINAL_PRODUCTION_AUDIT.md)** — auditul de defecte
  dinaintea porții, cu reproducerea fiecăruia.
- **[ULTIMATE_APPLICATION_FUNCTIONAL_AUDIT.md](ULTIMATE_APPLICATION_FUNCTIONAL_AUDIT.md)**
  — auditul funcțional.

## „Ceva nu merge" / „ce fac când…"

- **[PRODUCTION_INCIDENT_RUNBOOK.md](PRODUCTION_INCIDENT_RUNBOOK.md)** — 14
  incidente, fiecare cu semne, primul lucru de făcut, diagnostic, reparare și
  când escaladezi. **Începe de aici când ceva s-a stricat.**
- **[RUNBOOK.md](RUNBOOK.md)** — copii de siguranță, restaurare, și situațiile
  de zi cu zi: a venit un client nou, nu mai vin facturile, un document a rămas
  în eroare, cineva nu se poate autentifica.

## „Cum se lucrează cu ea?"

Trei ghiduri, pentru trei oameni diferiți:

- **[OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md)** — ziua unui operator: ce ecran,
  în ce ordine, și ce înseamnă fiecare.
- **[ACCOUNTANT_RUNBOOK.md](ACCOUNTANT_RUNBOOK.md)** — ce face aplicația, în
  termeni de cabinet. Fără cod.
- **[ADMIN_RUNBOOK.md](ADMIN_RUNBOOK.md)** — utilizatori, integrări, copii,
  monitorizare, actualizări.

## „Cum funcționează partea de contabilitate?"

- **[ACCOUNTING_UAT_CHECKLIST.md](ACCOUNTING_UAT_CHECKLIST.md)** — **ce trebuie
  confirmat de un contabil autorizat**, cu loc de semnătură. Cât timp nu este
  semnat, nicio documentație nu are voie să pretindă validare fiscală.
- **[DECLARATIONS.md](DECLARATIONS.md)** — catalogul de declarații, ce este
  certitudine și ce rămâne de confirmat de un contabil, și obligațiile fără
  calendar.
- **[DOCUMENT_PROCESSING.md](DOCUMENT_PROCESSING.md)** — drumul unui document, de
  la sosire la arhivă, inclusiv ce se întâmplă când procesarea nu merge.
- **[BANK_RECONCILIATION.md](BANK_RECONCILIATION.md)** — extrasele, potrivirea cu
  facturile, reconcilierea.
- **[EFACTURA.md](EFACTURA.md)** — citirea XML-ului, perechea XML↔PDF, și cele
  două condiții ANAF care nu se rezolvă din configurare.
- **[SAGA.md](SAGA.md)** — ce se știe, ce nu, și **ce fișier trebuie adus** ca să
  se poată face.

## „Cum este construit?"

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — structura, schema bazei, registrul de
  riscuri.
- **[adr/](adr/)** — deciziile de fond, fiecare cu alternativele cântărite.
- **[STATUS.md](STATUS.md)** — cum pornești pe o mașină nouă, ce s-a construit, ce
  urmează.

---

**O regulă care traversează toate documentele:** unde ceva nu a fost verificat
rulând, scrie asta. O integrare care are cod și teste pe un dublu **nu** este o
integrare verificată, iar diferența este notată peste tot cu același vocabular.
