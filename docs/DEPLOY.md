# Deploy

Două lucruri diferite, cu constrângeri diferite.

---

## 1. Frontend — Vercel

Funcționează așa cum e. Fără backend, fără bază de date: interfața rulează pe
backendul simulat din browser (`VITE_API_MODE=mock`, implicit), cu date sintetice.

**Legare:** proiect Vercel din repo, `Root Directory = frontend`. Vercel detectează
Vite; `frontend/vercel.json` adaugă ce nu poate ghici:

- **rescrieri SPA** — fără ele, o reîncărcare pe `/documente/verificare/<id>` dă 404,
  pentru că ruta trăiește în browser, nu pe server. Excepția `assets/` lasă fișierele
  statice să fie servite ca fișiere;
- **antete** — `nosniff`, `X-Frame-Options: DENY`, `no-referrer`, plus o politică de
  permisiuni care închide camera, microfonul, locația și plățile. Aplicația nu are
  nevoie de niciuna.

**Ca demonstrația să vorbească cu un API real**, se setează în Vercel:

```
VITE_API_MODE=http
VITE_API_BASE_URL=https://<api>/api/v1
```

Atenție: baza absolută pe altă origine **rupe previzualizarea documentelor**.
Cookie-ul de sesiune este `SameSite=Lax`, iar de pe altă origine nu ajunge la
cererile pornite de `<img>` sau `<object>`. Soluția este să servești API-ul de pe
aceeași origine — un rewrite Vercel de la `/api` către backend — nu să slăbești
cookie-ul și în niciun caz să pui un token în URL (§27).

---

## 2. Backend — ce cere, și de ce nu intră ca atare pe Vercel

Trei lucruri lipsesc dintr-un mediu serverless:

| Ce cere | De ce | Ce se schimbă |
|---|---|---|
| **Disc persistent** | `LocalStorageProvider` scrie originalele și arhiva pe disc. `/tmp` din serverless dispare între invocări, iar o probă contabilă nu are voie să dispară | un `S3StorageProvider` care implementează același protocol (ADR-004). Business logic nu se atinge: nu cunoaște `os.path` |
| **Proces continuu** | `app/worker.py` ia din coadă și procesează. Serverless nu ține procese vii | worker pe un serviciu cu proces continuu, **sau** `python -m app.worker --once` chemat de un cron care rulează des |
| **PostgreSQL** | schema, migrările, coada, auditul | serviciu gestionat (Neon, Supabase). Conexiunile serverless cer **pooling** — altfel fiecare invocare deschide o conexiune și baza rămâne fără |

### Ce mai trebuie făcut pentru varianta „Vercel + servicii externe"

În ordinea în care blochează:

1. **`S3StorageProvider`.** Protocolul există și e respectat peste tot; nimic din
   restul aplicației nu știe unde ajung fișierele. De implementat: `save` cu scriere
   atomică, `open`/`iter_range` pentru preview cu `Range`, `copy` pentru arhivare,
   `exists`, `size`, `delete`. Testele de storage existente sunt scrise pe protocol,
   deci se aplică și noului provider.
2. **Pooling de conexiuni.** `DATABASE_URL` către endpointul cu pooler al
   furnizorului, plus `db_pool_size` mic. Fără asta, primul vârf de trafic epuizează
   conexiunile.
3. **Workerul pe cron.** Vercel Cron poate chema o rută protejată care rulează un tur.
   `--once` există exact pentru asta. Ruta trebuie autentificată cu un secret, nu
   lăsată publică.
4. **Migrările.** Nu rulează din funcția serverless: se aplică separat, înainte de
   deploy, dintr-un pas de CI sau de la o mașină cu acces la baza de date.

### Alternativa, mai simplă

Un singur serviciu cu proces continuu și disc (Railway, Render, Fly.io, sau un VPS cu
`docker compose`) rezolvă toate trei fără să schimbe nicio linie de cod: API, worker
și Postgres, exact cum rulează azi local. Alegerea „Vercel + servicii externe" este
justificată dacă frontendul și API-ul trebuie să stea pe aceeași platformă; costul ei
este munca de la punctele 1–4.

---

## 3. Înainte de orice deploy în producție

`Settings.assert_production_ready()` oprește pornirea dacă `SECRET_KEY` a rămas cel
implicit sau dacă providerii sunt configurați inconsistent. În plus, de verificat
manual:

- `CORS_ALLOWED_ORIGINS` enumeră originile reale (caracterul universal este refuzat
  de configurare);
- `ENVIRONMENT=production` — ascunde `/docs` și pune `Secure` pe cookie-uri;
- `OCR_PROVIDER` / `AI_PROVIDER`: `mock` înseamnă că **niciun document nu părăsește
  mașina**. Trecerea la un provider real este o decizie cu implicații GDPR (R2), nu o
  schimbare de configurare;
- documentele nu se comit niciodată în repo — `storage/` și `ARHIVA/` sunt ignorate.
