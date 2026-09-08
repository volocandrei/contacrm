# Matricea conexiunilor

Fiecare legătură dintre ContaCRM și lumea din afară: în ce direcție merge, pe ce
protocol, cum se legitimează, către ce adresă, și dacă a fost verificată.

**Adresele sunt luate din cod.** Unde codul nu conține o adresă — fiindcă o dă
furnizorul sau administratorul — scrie „configurabilă", nu o valoare inventată.

---

## Ieșiri — aplicația cheamă pe altcineva

| Sistem | Direcție | Protocol | Autentificare | Endpoint | Webhook | Mediu | Stare |
|---|---|---|---|---|---|---|---|
| PostgreSQL | ContaCRM → bază | TCP / protocol PostgreSQL | utilizator + parolă (`DATABASE_URL`) | configurabilă | nu | prod + test | **verificat rulând** |
| Stocare locală | ContaCRM → disc | filesystem | drepturile procesului | `STORAGE_PATH` | nu | prod + test | **verificat rulând** |
| Stocare S3 | ContaCRM → bucket | HTTPS (SDK `boto3`) | chei de acces | `S3_ENDPOINT_URL`, gol = AWS | nu | prod + test | `MOCK VERIFIED` (`moto`) |
| ANAF — autorizare | ContaCRM → ANAF | HTTPS, OAuth 2.0 | `client_id`/`secret` + **certificat calificat, în browser** | `https://logincert.anaf.ro/anaf-oauth2/v1` | nu | prod + test | `NOT VERIFIED — PROVIDER ACCESS REQUIRED` |
| ANAF — facturi | ContaCRM → ANAF | HTTPS REST | Bearer (token din OAuth) | `https://api.anaf.ro/prod/FCTEL/rest` · `.../test/FCTEL/rest` | nu | prod + test | `NOT VERIFIED — PROVIDER ACCESS REQUIRED` |
| ANAF — XML→PDF | ContaCRM → ANAF | HTTPS REST | **niciuna** (public) | `https://webservicesp.anaf.ro/prod/FCTEL/rest/transformare/FACT1` | nu | prod | `NOT VERIFIED — PROVIDER ACCESS REQUIRED` |
| Microsoft — autorizare | ContaCRM → Microsoft | HTTPS, OAuth 2.0 | `client_id`/`secret`/`tenant` | `https://login.microsoftonline.com` | nu | prod | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| Microsoft Graph | ContaCRM → Microsoft | HTTPS REST | Bearer (token din OAuth) | `https://graph.microsoft.com/v1.0` | nu | prod | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| IMAP | ContaCRM → server email | IMAP4 peste SSL | utilizator + parolă (criptată la repaus) | configurabilă, per cabinet | nu | prod | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| SMTP | ContaCRM → server email | SMTP + STARTTLS (587) sau SMTPS (465) | utilizator + parolă | configurabilă | nu | prod | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| Anthropic — extragere | ContaCRM → Anthropic | HTTPS REST | `x-api-key` | `https://api.anthropic.com/v1/messages` | nu | prod | `NOT VERIFIED — CREDENTIALS REQUIRED` |
| Anthropic — asistent | ContaCRM → Anthropic | HTTPS REST | `x-api-key` (**cheie separată**) | `https://api.anthropic.com/v1/messages` | nu | prod | `NOT VERIFIED — CREDENTIALS REQUIRED` |

## Intrări — altcineva cheamă aplicația

| Sistem | Direcție | Protocol | Autentificare | Endpoint | Webhook | Mediu | Stare |
|---|---|---|---|---|---|---|---|
| Browserul cabinetului | om → ContaCRM | HTTPS | cookie de sesiune (`HttpOnly`, `Secure`, `SameSite`) | `PUBLIC_BASE_URL/api/v1/*` | nu | prod | **verificat rulând** (93 de teste în browser real) |
| Browserul clientului (portal) | om → ContaCRM | HTTPS | **token în cale**, nu în query string (§27) | `PUBLIC_BASE_URL/api/v1/portal/{token}` | nu | prod | **verificat rulând** |
| Planificator (cron) | cron → ContaCRM | HTTPS GET | `CRON_SECRET` în antet | `/api/v1/internal/run-queue`, `/daily-digest`, `/reminders` | intrare | prod | **verificat rulând** |
| Load balancer | infra → ContaCRM | HTTP GET | **niciuna** (deliberat) | `/health/live`, `/health/ready`, `/health/info` | nu | prod | **verificat rulând** |

## Ce nu există

| Sistem | De ce apare aici |
|---|---|
| WhatsApp (Meta / Twilio) | **Niciun webhook, niciun API.** Butonul din interfață deschide `https://wa.me/<număr>` în aplicația utilizatorului. Nu trece prin server, nu cere cont. |
| SAGA | Nicio conexiune. Predarea se face prin fișier CSV descărcat de om. |
| Sentry / OTLP | Variabilele există marcate `NEIMPLEMENTAT`; niciun export. |
| Serviciu de plăți | Niciunul. |
| Analytics | Niciunul. |

---

## Note care contează la punerea în funcțiune

**Rutele de cron răspund 404 fără secret, nu 401.** Un 401 ar confirma că ruta
există; rutele astea nu au de ce să fie descoperite de nimeni din afară.
`CRON_SECRET` gol înseamnă **oprit**: refuză orice, inclusiv o cerere corectă.

**Adresele de redirect trebuie să fie identice** cu cele înregistrate la furnizor
(`MS_REDIRECT_URI` în Entra ID, `ANAF_REDIRECT_URI` în portalul ANAF). O
diferență de un caracter produce o eroare opacă la consimțământ.

**`ANAF_ENVIRONMENT` nu este un nivel de log.** `prod` și `test` sunt baze
complet separate la ANAF: o instalare lăsată pe `test` raportează „nicio factură"
la nesfârșit, fără nicio eroare.

**Nicio integrare nu este obligatorie.** Fără oricare dintre ele, ecranul ei
spune că nu este configurată — nu se oferă și apoi eșuează.

**Toate ieșirile sunt HTTPS**, cu excepția conexiunii la baza de date și a
stocării locale, care nu părăsesc rețeaua instalării.
