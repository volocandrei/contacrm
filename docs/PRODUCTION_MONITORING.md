# Monitorizare și alerte

Ce trebuie configurat ca o problemă să **sune un om**, nu să se descopere a doua
zi la o sută de documente neprocesate.

Aplicația **nu** trimite alerte singură și nu are integrare cu niciun serviciu de
monitorizare. Ce face este să **spună adevărul despre starea ei** pe câteva
adrese HTTP. Un serviciu extern le interoghează și sună.

---

## Cele patru adrese, și ce înseamnă fiecare

| Adresă | Răspunde la întrebarea | Cine o citește | 503 înseamnă |
|---|---|---|---|
| `/health/live` | procesul răspunde? | orchestratorul (Docker, systemd) | repornește procesul |
| `/health/ready` | **instanța asta** poate servi cereri? | load balancerul | scoate instanța din rotație |
| `/health/workers` | mai procesează cineva documentele? | **monitorizarea externă** | sună un om |
| `/health/info` | ce versiune și ce configurare rulează? | omul, la depanare | — |

Niciuna nu cere autentificare și niciuna nu conține secrete — un test o verifică
(`test_worker_health.py::test_no_secret_leaks_through_the_health_endpoints`).

### De ce workerul are adresă separată

`/health/ready` este citit de load balancer. Dacă un worker mort ar face `ready`
să răspundă 503, load balancerul ar scoate din rotație **toate** instanțele de
API: o problemă de procesare s-ar transforma într-o cădere totală, exact în
momentul în care cabinetul are nevoie să deschidă ecranul cozii ca să înțeleagă
ce se întâmplă.

Un worker mort trebuie să **sune un om**, nu să oprească aplicația.

Starea workerului apare **și** în corpul lui `/health/ready`, pentru cine se uită
acolo, dar nu influențează codul HTTP.

---

## Ce trebuie configurat, minimum

Un serviciu care interoghează două adrese și trimite email când nu primește 200.
UptimeRobot, HetrixTools, Better Stack și Healthchecks.io au toate un plan
gratuit suficient. **Nu este nevoie de un serviciu anume**; proiectul nu
folosește niciunul azi.

| Ce | Valoare |
|---|---|
| **Monitor 1 — aplicația** | |
| URL | `https://domeniul-tău/health/ready` |
| Interval | 1–5 minute |
| Timeout | 10 secunde |
| Se așteaptă | `HTTP 200`, corp cu `"status":"ok"` |
| Alertă la | 503, timeout, sau două verificări ratate consecutiv |
| Gravitate | **CRITIC** — nimeni nu poate lucra |
| **Monitor 2 — workerul** | |
| URL | `https://domeniul-tău/health/workers` |
| Interval | 5 minute |
| Timeout | 10 secunde |
| Se așteaptă | `HTTP 200`, corp cu `"status":"ok"` |
| Alertă la | 503 de două ori consecutiv (evită o alertă la o repornire) |
| Gravitate | **CRITIC** — documentele intră și nu le ia nimeni |

Destinația alertei: adresa de email a administratorului cabinetului. Dacă
serviciul permite, adaugă și SMS pentru primul monitor.

### Cum arată răspunsul workerului

```json
{
  "status": "stale",
  "workers": [
    {
      "name": "processing",
      "healthy": false,
      "ageSeconds": 431,
      "timeoutSeconds": 90,
      "hostname": "srv-contacrm",
      "detail": "Workerul processing nu a mai raportat de 431 secunde (pragul este 90). Documentele se strâng în coadă."
    }
  ]
}
```

`detail` este scris ca să poată intra direct într-o alertă, fără traducere.

---

## Cum știe aplicația că workerul trăiește

Workerul scrie un **semn de viață** la fiecare tur, într-un rând din baza de
date (`worker_heartbeats`). `/health/workers` compară vechimea lui cu
`WORKER_HEARTBEAT_TIMEOUT_SECONDS` (implicit **90 de secunde**, adică trei ture
goale ratate la rând).

Trei alegeri care contează:

- **Se bate înaintea muncii, nu după.** Dacă turul se blochează într-un apel de
  rețea care nu se mai întoarce, ultimul semn rămâne cel de dinainte și
  îmbătrânește — exact ce trebuie să declanșeze alarma. Un worker blocat este viu
  pentru sistemul de operare și mort pentru cabinet.
- **Ceasul este al bazei, nu al procesului.** Două mașini cu ceasuri
  nesincronizate ar fi produs o vechime imposibilă, iar alarma ar fi sunat pentru
  NTP, nu pentru worker.
- **Un worker care nu a raportat niciodată nu este sănătos.** O instalare în care
  workerul nu a fost pornit deloc arată exact ce este, din prima zi — nu tace
  până la primul document.

Funcționează și pentru cabinetele care rulează workerul din cron
(`python -m app.worker --once`): și acela bate.

---

## Politica de alertare

Nu trimite notificări pentru fiecare eroare. Un om care primește douăzeci de
mesaje pe zi nu mai citește al douăzeci și unulea — iar acela este cel care
conta.

### CRITIC — sună imediat

| Situație | Cum se detectează |
|---|---|
| Aplicația nu răspunde | `/health/ready` → 503 sau timeout |
| Baza de date indisponibilă | `/health/ready` → `"database": false` |
| Workerul mort sau blocat | `/health/workers` → 503 |
| Stocarea indisponibilă | încărcările eșuează; vezi jurnalul, `StorageError` |

### AVERTISMENT — se privește în aceeași zi

| Situație | Unde se vede |
|---|---|
| Coadă care crește | *Documente → În procesare*; vezi pragurile mai jos |
| Eșecuri repetate de procesare | același ecran, lista de eșecuri recente |
| Disc aproape plin | monitorizarea serverului (nu a aplicației) |
| O integrare nu a mai adus nimic | *Administrare → Surse documente* / *e-Factura* |
| O credențială se apropie de expirare | [PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md) |

### Nu alerta pentru

- un document care a eșuat (are motivul scris pe ecran și se reprocesează);
- un email care nu a plecat o dată (se reîncearcă din ecranul de remindere);
- o sincronizare ratată (turul următor continuă de unde a rămas).

---

## Praguri pentru coada de procesare

Ecranul *Documente → În procesare* arată patru cifre. **Cea care contează nu
este câte sunt în coadă, ci de când așteaptă cea mai veche**: treizeci de cereri
într-o dimineață aglomerată sunt normale și se golesc singure; una singură care
așteaptă de patruzeci de minute nu are nicio explicație bună.

| Stare | Cea mai veche cerere așteaptă | Ce înseamnă |
|---|---|---|
| Normal | sub 5 minute | procesarea ține pasul |
| Atenție | 5–15 minute | vârf de încărcare, sau un document greu |
| **Critic** | peste 15 minute | cel mai probabil procesarea nu rulează |

Pragul de 15 minute din interfață este ales pentru cereri care **nu au pornit
deloc**: dacă nimeni nu le-a luat într-un sfert de oră, nu le va lua nimeni.
Este altceva decât `PROCESSING_STALE_AFTER_MINUTES`, care se aplică unui job
**pornit** și neterminat.

Un job blocat se repune în coadă cu:

```bash
uv run --directory backend python -m app.cli recover-processing
```

---

## Spațiu pe disc

Documentele sunt critice și cresc monoton — nimic nu le șterge automat (vezi
[PRODUCTION_ENVIRONMENT_VARIABLES.md](PRODUCTION_ENVIRONMENT_VARIABLES.md),
secțiunea de retenție).

**Aplicația nu monitorizează discul** — ar fi trebuit să presupună un sistem de
fișiere anume, iar pe S3 întrebarea nici nu are sens. Se monitorizează la nivel
de server:

| Prag | Ce se face |
|---|---|
| sub 20% liber | **AVERTISMENT** — planifică extinderea sau arhivarea |
| sub 10% liber | **CRITIC** — extinde acum |
| sub 5% liber | încărcările încep să eșueze |

Când discul este plin, încărcarea **eșuează zgomotos**: se ridică o eroare, nu se
scrie niciun rând, iar arhivarea nu marchează documentul ca arhivat. Verificat
prin test (`test_storage_failure.py`) și prin mutație — un document `ARCHIVED`
fără fișier în arhivă ar arăta identic cu unul corect și s-ar descoperi abia la
un control.

Estimare grosieră: o factură PDF are 100–500 KB. Un cabinet cu 200 de clienți și
30 de documente pe client pe lună scrie ~1–3 GB pe an, plus copiile din arhivă.

---

## Jurnalele

Structurate (structlog), la ieșirea standard. Fiecare linie poartă `request_id`,
iar unde este cazul `user_id`, `document_id`, `job_id`.

**Ce nu conțin niciodată:** parole, tokenuri, chei de API, conținutul
documentelor. Un test verifică rutele de sănătate; restul este apărat de
convenția de logare.

Ce trebuie făcut la instalare: trimite ieșirea standard undeva unde se poate
citi peste o săptămână (`journald`, fișier rotit, sau colectorul platformei).
Într-un container fără asta, jurnalul dispare la fiecare repornire — adică exact
când ai nevoie de el.

---

## Ce nu este monitorizat, și de ce

| Ce | De ce nu |
|---|---|
| Metrici (Prometheus, OTLP) | Nu există export. Variabilele din `.env.example` sunt marcate `NEIMPLEMENTAT`. |
| Trasare distribuită | O aplicație, un worker, o bază. Nu ar arăta nimic în plus. |
| Sentry | Nicio integrare. Jurnalele structurate acoperă depanarea la scara unui cabinet. |
| Expirarea secretului Microsoft | Aplicația **nu poate ști** data: Entra ID nu o trimite la niciun apel. Rămâne operațional — vezi [PRODUCTION_EXPIRY_CHECKLIST.md](PRODUCTION_EXPIRY_CHECKLIST.md). |

Ce **se vede** în aplicație despre integrări: ultima sincronizare reușită și
ultima eroare, pe ecranele lor. O integrare care nu a mai adus nimic de o
săptămână se vede acolo înainte să întrebe un client.
