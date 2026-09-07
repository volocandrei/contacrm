# Raport final — construcția pentru producție

Data: **8 septembrie 2026.** Documentul acesta răspunde la o singură întrebare:
**poate aplicația să țină datele financiare reale ale unui cabinet contabil, de
mâine?**

Pentru auditul de defecte, vezi [FINAL_PRODUCTION_AUDIT.md](FINAL_PRODUCTION_AUDIT.md).
Pentru ce trebuie făcut în ziua pornirii,
[PRODUCTION_LAUNCH_CHECKLIST.md](PRODUCTION_LAUNCH_CHECKLIST.md). Pentru starea
fiecărei integrări, [INTEGRATIONS.md](INTEGRATIONS.md).

---

## Verdict

**READY WITH WARNINGS.**

Aplicația poate porni pe date reale, cu trei condiții care nu sunt negociabile și
sunt scrise ca porți **STOP** în lista de control: secrete generate pentru
instalarea aceasta, primul cont de administrator creat cum trebuie, și o copie de
siguranță **restaurată o dată** înainte de primul client.

Avertismentele nu sunt despre ce face aplicația, ci despre ce **nu s-a putut
verifica rulând**: nicio integrare externă nu a fost probată cu credențiale
reale, fiindcă nu există niciuna. Ce depinde numai de noi — autentificare,
izolare între cabinete, ciclul documentului, termenele, rapoartele, banca din
fișier, copiile de siguranță — este verificat rulând, nu citind.

Nu este **READY** fiindcă a spune asta despre un lanț al cărui capăt nu a fost
niciodată atins ar fi o afirmație pe care nu o pot susține. Nu este **NOT READY**
fiindcă blocajul din enunț — securitatea administratorului — a fost rezolvat, iar
partea de aplicație care ține datele cabinetului funcționează și se poate folosi
fără nicio integrare.

---

## Ce s-a construit în această rundă

### Securitatea administratorului (blocantul din enunț)

- politică de parole aplicată în amândouă capetele, cu aceleași reguli verificate
  de un test de contract care citește cazurile din fișierul TypeScript;
- o parolă nu poate conține fragmente din emailul sau numele contului;
- schimbarea parolei din aplicație, cu parola curentă cerută;
- lista sesiunilor active și revocarea celorlalte, dintr-un ecran propriu;
- resetarea unei parole de către administrator **revocă toate sesiunile** acelui
  utilizator — altfel o parolă compromisă rămânea utilă prin sesiunea deschisă.

### Declarațiile

- catalogul completat: D301, D101, D205, plus situațiile financiare interimare;
- periodicitatea `ON_DEMAND`, pentru obligațiile care nu se nasc din calendar:
  nu produc perioade, nu apar ca restanțe, iar calculul termenului **refuză** și
  spune de ce în loc să întoarcă o dată inventată;
- înregistrarea lor de pe fișa clientului, cu perioada aleasă de om și nota lui;
- lista a ce s-a înregistrat, pe fișa clientului — fără ea, o depunere fără
  calendar ar fi fost scrisă în evidență și invizibilă în aceeași clipă;
- registrul declarațiilor ca fișier, cu intervalul aplicat perioadei declarate,
  nu zilei marcării.

### Documentele

- liniile facturii cu **cota de TVA pe fiecare linie** și descrierea produsului,
  citite din XML-ul e-Factura;
- desfacerea automată a teancurilor scanate, cu proveniența fiecărei bucăți;
- perechea XML ↔ PDF a aceleiași facturi, cu stări explicite și cu **conflictul
  de sume care nu se leagă niciodată**;
- proveniența declarată la încărcarea manuală: se pot afirma două drumuri,
  încărcare directă și WhatsApp, iar restul — email, OneDrive, SPV — sunt
  constatări ale sistemului și se refuză explicit;
- centrul de procesare: starea cozii pe ecran, cu cifra care contează (de când
  așteaptă cea mai veche cerere, nu câte sunt).

### Banca

Import de extrase, potrivire automată cu documentele, reconciliere și ecranul ei.
Nicio conexiune bancară directă — și nu s-a promis una.

### Ce s-a reparat, găsit rulând

Zece defecte în auditul de pregătire, dintre care două de securitate (o formulă
executabilă într-un CSV exportat, o cale de fișier venită de la client) și patru
de integritate sau de comportament (aceeași reamintire trimisă de patru ori, ziua
serverului confundată cu ziua cabinetului, o stivă din documentație care nu putea
porni, un asistent fără limită de cost). Detaliile, cu reproducerea fiecăruia, în
[FINAL_PRODUCTION_AUDIT.md](FINAL_PRODUCTION_AUDIT.md).

---

## Ce nu s-a putut verifica, și de ce

| Integrare | Stare | Ce lipsește |
|---|---|---|
| ANAF / SPV (e-Factura) | NOT VERIFIED — EXTERNAL CREDENTIAL REQUIRED | certificat calificat, aplicație înregistrată în SPV |
| Microsoft Graph (OneDrive, email) | MOCK VERIFIED | `MS_CLIENT_ID` / `MS_CLIENT_SECRET` / `MS_TENANT_ID` |
| IMAP | MOCK VERIFIED | o cutie poștală de test |
| SMTP | MOCK VERIFIED | `SMTP_*` și un domeniu cu SPF/DKIM/DMARC |
| Model de extragere (poze, scanuri) | MOCK VERIFIED | `AI_API_KEY` |
| SAGA | neimplementat, deliberat | un fișier real exportat din SAGA sau documentația formatului de import |

Detaliile fiecăreia — ce anume **s-a** verificat și ce rămâne o presupunere
despre protocolul celuilalt sistem — în [INTEGRATIONS.md](INTEGRATIONS.md).

**Despre SAGA, explicit:** nu s-a scris nicio conversie. Formatul de import nu
este public, iar unul ghicit ar produce fișiere care se încarcă și pun cifre
greșite în contabilitate — cel mai scump fel de eșec, fiindcă nu se vede. Ce
există în loc și este util imediat: exportul CSV al registrului, în formatul pe
care Excel-ul românesc îl deschide corect.

---

## Ce rămâne de făcut de om, nu de aplicație

1. **Catalogul de declarații se confirmă cu un contabil**, rând cu rând.
   Termenele din cod sunt puncte de plecare uzuale, nu o afirmație a aplicației
   despre ce spune legea. Se ajustează din `/administrare/declaratii`.
2. **Copia de siguranță se restaurează o dată**, pe o instalare de test, înainte
   de primul client real. O copie care nu s-a restaurat niciodată nu este o
   copie.
3. **Prima rulare a fiecărei integrări se face cu un singur client**, urmărită.
4. **Cineva trebuie alertat când workerul moare.** Panoul de procesare arată
   starea cozii pe ecran, dar nu sună pe nimeni noaptea.

---

## Cifrele

| | Valoare |
|---|---|
| Teste backend | 1.940 |
| Teste frontend | 410 |
| Teste end-to-end (browser real, backend real) | 93 |
| `mypy --strict` pe 176 de module | curat |
| `ruff check` + `ruff format --check` pe 309 fișiere | curat |
| Migrări aplicate de la zero | 27, până la `d7c2a41f8b95` |
| Secrete în repository | 0 |
| Rute cerute de frontend și inexistente în backend | 0 |
| Integrări externe verificate live | **0** — vezi tabelul de mai sus |

Fiecare regulă nouă din runda aceasta este verificată **prin mutație**: se strică
deliberat regula și se confirmă că testul cade. O aserțiune care trece și cu
regula stricată nu apără nimic.

## Cum se verifică ce scrie aici

```bash
# backend: lint, tipuri, migrări, teste
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run alembic upgrade head
uv run pytest

# frontend: lint, tipuri, teste, build
cd ../frontend
npm run lint
npx tsc --noEmit -p tsconfig.app.json
npm test -- --run
npm run build

# end-to-end, într-un browser real
npm run test:e2e
```

Aceleași comenzi rulează în CI la fiecare push, plus trei verificări de igienă:
niciun `.env` comis, niciun document contabil în repo, niciun caracter de
control în surse.
