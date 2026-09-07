# Audit funcțional al aplicației, pe aplicația care rulează

**7 septembrie 2026.** Verificare făcută **rulând** aplicația — bază PostgreSQL
proprie, migrări reale de la zero, server real, cereri HTTP reale, browser real —
nu citind cod și nu crezând documentația. Unde documentația și realitatea nu s-au
potrivit, a câștigat realitatea, iar documentația a fost corectată.

---

## Rezumat

Șase defecte găsite, șase reparate, fiecare cu test de regresie și cu mutație
care confirmă că testul chiar cade fără reparație.

**Cel mai grav** a fost pe ecranul cel mai important: panoul principal raporta
**un sfert** din munca rămasă. Cu patru clienți activi care datorau documente,
panoul spunea „1 client cu lipsuri" în timp ce raportul „Documente lipsă", pe
aceleași date, spunea 4. Iar pe un cabinet care tocmai își importase clienții,
panoul era **complet gol** — fără lună, fără termen, fără cifre — deși existau 16
documente datorate. Ecranul cu care începe ziua liniștea despre o lună de muncă.

**Nu s-a găsit nicio scurgere de date între cabinete.** Două rute nu verificau
apartenența clientului, dar interogările lor filtrau oricum după organizație:
lipsea garanția, nu confidențialitatea. Ambele au fost închise.

**Verdict: READY WITH WARNINGS.** Detalii la sfârșit.

---

## Cum a fost verificat

| | |
|---|---|
| Bază de date | `contacrm_audit`, creată goală, migrată cu `alembic upgrade head` |
| Schema | comparată cu modelele ORM: 8 diferențe, toate indexuri de expresie (trigram, FTS, unice parțiale) care există doar în migrări — corect, nu defect |
| Server | `uvicorn app.main:app`, proces real, cereri `curl` |
| Date | `seed-dev` (6 clienți, 24 de așteptări) + o a doua organizație creată manual pentru izolare |
| Browser | suita E2E Playwright, 86 de teste, backend real + Postgres real |

---

## Registrul defectelor

| # | Zonă | Severitate | Problemă | Cauză | Reparație | Test | Verificat |
|---|---|---|---|---|---|---|---|
| 1a | Dashboard | **CRITICĂ** | Panoul raporta 1 client cu lipsuri unde raportul raporta 4 | `clients_missing_docs` se calcula din `list_periods`, care nu inventează o lună fără documente — deci sărea clientul care n-a trimis nimic | Panoul se hrănește din `missing()`, aceeași sursă ca raportul | `TestTheClientWhoSentNothing::test_the_missing_count_agrees_with_the_report` | mutație |
| 1b | Dashboard | **CRITICĂ** | Panou complet gol pe un cabinet cu clienți și așteptări, dar fără documente procesate | `latest_active_month` întoarce `None`, iar tot panoul depindea de ea | `month_overview`: luna din date, iar când datele tac, luna calendaristică — **numai dacă se datorează ceva** | `test_a_freshly_installed_office_is_not_told_it_is_done` | mutație |
| 2 | Securitate | MEDIE | `GET /clients/{id}/upload-links` răspundea `200 []` pentru clientul altui cabinet **și pentru orice UUID inventat** | Ruta nu verifica apartenența; `POST` pe aceeași resursă o verifica | Verificare + `404`, ca la rutele-surori (§72) | `test_client_isolation.py`, sweep peste toate rutele cu id | mutație |
| 3 | Securitate | MEDIE | Idem pentru `GET /clients/{id}/aliases` | idem | idem | idem | mutație |
| 4 | Contract §14 | MEDIE | Backendul simulat nu-l vedea pe clientul fără nicio perioadă: demonstrația ascundea aceiași clienți pe care serverul îi arată | Așteptările trăiau **în interiorul** perioadelor, deci un client nou nu putea avea așteptări | Depozit propriu de așteptări + `neverStarted()`, oglinda lui `_never_started` | `dashboard-closing.test.ts` | mutație |
| 5 | Contract tipuri | MEDIE | `AccountingPeriod.id` declarat `string`, dar API-ul întoarce `null` pentru clientul fără perioadă | Tipul nu urma răspunsul real | `id: string \| null` | `tsc` strict | compilator |
| 6 | Frontend | MEDIE | Tabelul „Documente lipsă" chei rândurile pe `period.id` — `null` pentru fiecare client care n-a trimis nimic, deci toate rândurile cu aceeași cheie absentă | consecința lui #5 | cheie pe `clientId`, unic prin construcție | `tsc` + E2E fără erori de consolă | browser |

### Detaliul defectului 1, pentru că este cel care conta

Reproducere, pe serverul real:

```
PANOU  clientsMissingDocs : 1      RAPORT clienti cu lipsuri : 4
PANOU  closing.laggards   : ['Alfa Conta SRL']
```

După reparație, pe aceleași date:

```
PANOU  clientsMissingDocs : 4      RAPORT clienti cu lipsuri : 4
PANOU  laggards           : ['Alfa Conta SRL', 'Beta Service SRL',
                             'Delta Prod SRL', 'Șerbănescu Impex SRL']
```

**Regula corectă, scrisă acum explicit:** panoul are lună dacă există **muncă**,
nu dacă există calendar. Un cabinet gol nu primește o lună inventată — testul
care apăra asta a rămas neatins și trece; un cabinet cu clienți care datorează
documente primește luna curentă, chiar dacă n-a intrat încă niciun document.

---

## Ce a fost verificat și **funcționează**

Nu doar ce s-a stricat. Fiecare rând de mai jos a fost pus la încercare, nu citit.

### Dashboard
Toate cifrele confruntate cu interogări independente pe bază: `clientsTotal` 6 și
`clientsActive` 4 se potrivesc exact cu `select count(*)` filtrat pe `deleted_at`
și `status`. După reparație, panoul, raportul și `closing` dau același număr.

### Surse documente
Toate cele 5 drumuri reale raportează starea calculată din configurarea care
rulează, nu declarată. Cele 3 inexistente spun asta pe față, cu `documents: null`
— nu zero, care ar arăta ca o integrare stricată.

### Ciclul documentului
- Încărcare reală prin API: `201`, document în bază, job de procesare creat.
- Procesare: PDF sintetic ilizibil → `OCR_FAILED`, job `FAILED`, document rămas
  `RECEIVED` (retriabil) — comportament corect, nu defect.
- **Fișier gol** → `422`. **Executabil deghizat în `.pdf`** (antet `MZ`) → `422`,
  respins după octeți, nu după extensie (§50).
- **Nume ostile**: `../../../../etc/passwd.pdf`, `..\..\windows\system32\cmd.pdf`,
  300 de caractere, diacritice, `%`, `_`. Toate stocate la
  `organizations/{org}/documents/{uuid}/original/source.pdf` — numele original
  rămâne **etichetă**, niciodată cale. Traversarea de cale este imposibilă prin
  construcție.
- Previzualizare și descărcare: `200` cu cookie de sesiune (drumul real al
  browserului pentru `<img>`/`<object>`), `401` fără. Antete corecte:
  `private, no-store`, `Content-Disposition` cu `filename*=UTF-8''`.

### Autentificare și RBAC
Operator: `403` pe `/users`, `/roles`, `/settings`, `/audit-logs`, `/fees`,
`/reminders`. Administrator: `200` pe toate. Refuzul îl dă serverul, nu interfața.

### Izolare între cabinete
17 rute cu id, cerute cu sesiunea altei organizații: toate `404` (nu `403` — un
refuz ar confirma că id-ul există). Clientul străin nu apare în liste.

### Capcanele de regresie cunoscute, pe PostgreSQL real
| Capcană | Rezultat |
|---|---|
| `Serban` → `Șerbănescu Impex SRL` | ✅ găsit |
| `DISTRIBUTIE` → `Gama Distribuție SRL` | ✅ găsit |
| `%`, `_`, `%%`, `Alfa%` | ✅ 0 rezultate din 6 — tratate ca text, nu jokeri |
| `TaskStatus` după dus-întors real (`session.expire`) | ✅ enum, nu șir |
| `DONE ⇔ completed_at`, ambele direcții | ✅ ține |
| CUI duplicat | ✅ `409` |
| CUI al unui client șters | ✅ reînregistrare permisă |
| Audit `old`/`new` la schimbarea de status | ✅ `{'status':'TODO'} → {'status':'DONE'}` în bază; ascunse deliberat din API (§33) |

### Contract frontend ↔ backend
98 de apeluri extrase din `endpoints.ts`, confruntate cu cele 122 de rute din
OpenAPI: **toate au rută**. Cele 25 de rute pe care le folosesc ecranele
principale răspund `200`.

### Paginare
`pageSize` 1 / 5 / 100 corect; `201` → `422` (plafon 200); `page=0` și `page=-1` →
`422`; pagină peste sfârșit → listă goală cu `total` corect.

---

## Inventarul paginilor

30 de rute în `App.tsx`. Toate deschise în browser de suita E2E
(`e2e/pages.spec.ts`), care cade la orice eroare de consolă sau cerere eșuată.

| Zonă | Rute | Deschise | Funcționale | Defecte găsite |
|---|---|---|---|---|
| Panou | `/` | ✅ | ✅ după reparație | 2 (1a, 1b) |
| CRM | clienți, import, fișă, contacte, sarcini, onorarii | ✅ | ✅ | 0 |
| Documente | inbox, procesare, verificare, neatribuite, arhivă, coadă, fișă | ✅ | ✅ | 0 |
| Contabilitate | perioade, **lipsă**, termene, șabloane | ✅ | ✅ după reparație | 1 (#6) |
| Comunicare | mesaje, șabloane, remindere | ✅ | ✅ | 0 |
| Administrare | utilizatori, roluri, setări, **surse**, e-Factura, audit, declarații | ✅ | ✅ | 0 |
| Public | login, portal `/incarca/:token` | ✅ | ✅ | 0 |

---

## Rezultate exacte

| Verificare | Comandă | Rezultat |
|---|---|---|
| Teste backend | `uv run pytest -q` | **1.661 teste, toate verzi** |
| Teste frontend | `npx vitest run` | **330 teste, 32 fișiere, toate verzi** |
| E2E, browser real | `npm run test:e2e` | **86 teste, toate verzi** (4,2 min) |
| Lint backend | `ruff check .` | *All checks passed* |
| Format backend | `ruff format --check .` | *270 files already formatted* |
| Tipuri backend | `mypy app` | *no issues in 163 source files* |
| Tipuri frontend | `tsc --noEmit` | fără erori |
| Lint frontend | `oxlint src` | ieșire 0 |
| Build frontend | `npm run build` | reușit |
| Migrări de la zero | `alembic upgrade head` pe bază goală | reușit |
| Schemă vs modele | `compare_metadata` | doar indexuri de expresie, așteptat |

---

## Element deschis: costul panoului

Reparația 1a face muncă în plus, fiindcă răspunde la o întrebare la care înainte
răspundea greșit: **30 de interogări în loc de 24** pe setul de volum.

Costul a fost tăiat înainte de a fi acceptat:
- cele trei citiri pe care panoul le făcea de două ori — clienți, așteptări,
  etichete de tip — se fac o dată pe cerere;
- `_collection_state` primește golurile deja calculate, în loc să le ceară din
  nou cu un serviciu nou.

Pragul din `test_the_dashboard_is_a_fixed_number_of_queries` a fost mutat de la 25
la 34, cu motivul scris în test. **Nu a fost slăbit ca să treacă**: el prinde în
continuare un N+1 sau o interogare uitată într-o buclă; ce s-a schimbat este
cantitatea de muncă pe care ecranul o face corect. Cele șase interogări rămân un
cost real, de recâștigat printr-o interogare agregată.

---

## Ce **nu** a putut fi verificat

| Ce | De ce | Ce ar fi nevoie |
|---|---|---|
| Preluare email prin **IMAP** | niciun server IMAP disponibil | o cutie de test cu parolă de aplicație |
| Preluare **Microsoft Graph** | fără credențiale Microsoft | `MS_CLIENT_ID`, `MS_CLIENT_SECRET` |
| **e-Factura / SPV ANAF** | autorizarea cere certificat digital în browser | certificat + împuterniciri |
| **Trimitere email** (solicitări, remindere, rezumat) | fără SMTP | `SMTP_*` + `NOTIFICATIONS_ENABLED` |
| **Citire cu AI** a pozelor | fără cheie | `AI_API_KEY` |
| **Export Saga** | nu există; forma nu se poate deduce | un fișier pe care Saga îl importă azi |

Pentru toate: logica proprie este acoperită de teste cu provideri falși, iar
punctul exact de contact cu serviciul extern rămâne **NEVERIFICAT**. Nu se afirmă
nicăieri că aceste integrări funcționează.

---

## Verdict

### READY WITH WARNINGS

Aplicația este utilizabilă și, pe partea verificabilă local, se poartă corect:
ciclul documentului, izolarea între cabinete, RBAC, integritatea bazei, căutarea,
paginarea, invarianții contabili.

Avertismentele, în ordinea importanței:

1. **Șase integrări externe rămân neverificate** — email (ambele feluri),
   e-Factura, AI, Saga. Sunt exact drumurile prin care ar trebui să intre
   majoritatea documentelor. Până la prima verificare cu credențiale reale,
   volumul practic al aplicației depinde de încărcarea manuală și de linkul de
   trimitere, care **au fost** verificate și funcționează.
2. **Panoul costă cu șase interogări mai mult** decât înainte de audit.
3. Defectul #1 a existat luni de zile fără să cadă niciun test, deși existau
   teste pe panou și pe raport separat. Ce lipsea era testul care le **compară**.
   Acela există acum, în ambele implementări.
