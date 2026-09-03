/**
 * Testele end-to-end (M8).
 *
 * **De ce există.** Aproape toate defectele serioase din proiectul ăsta au fost
 * găsite rulând aplicația, nu citind-o: tokenul fals trimis către API-ul real,
 * un buton oferit într-o stare în care ruta răspundea 409, o reprocesare care
 * răspundea 202 cu un document neatins, o expresie regulată ajunsă în fișier cu
 * un byte de control. Toate au trecut prin teste unitare verzi. Ce le lega era
 * că fiecare apărea abia acolo unde cele două jumătăți se întâlnesc — browser,
 * HTTP, cookie-uri, bază de date reală.
 *
 * Suita de aici pune exact acel drum sub verificare automată, o dată pentru
 * totdeauna, în loc să depindă de cine își aduce aminte să deschidă aplicația.
 *
 * **Ce pornește.** Un PostgreSQL adevărat (baza `contacrm_e2e`, reconstruită la
 * fiecare rulare), backendul adevărat, și **build-ul** frontendului servit prin
 * `vite preview` — nu serverul de development. Un E2E care verifică un artefact
 * pe care nimeni nu îl pune în producție verifică altceva decât produsul.
 *
 * Cele două servere se pornesc de aici, nu din CI, ca aceeași comandă să meargă
 * și pe laptop: `npm run test:e2e`.
 */
import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8010;
const WEB_PORT = 4173;

/** Baza pe care testele o pot lăsa murdară. Sufixul `_e2e` este garda din CLI. */
const DATABASE_URL =
  process.env.E2E_DATABASE_URL ??
  "postgresql+psycopg://contacrm:contacrm_dev_password@localhost:5432/contacrm_e2e";

const backendEnv = {
  DATABASE_URL,
  // `local` citește ce scrie chiar în fișierul urcat de test — XML sau PDF —
  // deci aserțiunile pot fi despre conținut, nu despre valori inventate. `mock`
  // ar fi făcut suita să verifice generatorul de date sintetice. Este și
  // valoarea recomandată în producție, deci se verifică exact ce se și rulează.
  OCR_PROVIDER: "local",
  STORAGE_PROVIDER: "local",
  STORAGE_PATH: "./storage/e2e",
  ARCHIVE_ROOT: "./storage/e2e/ARHIVA",
  ENVIRONMENT: "development",
};

export default defineConfig({
  testDir: "./e2e",
  // Serverele sunt partajate și baza este una singură: două fișiere care rulează
  // în paralel s-ar vedea documentele unul altuia. Testele sunt scrise să nu
  // depindă de asta, dar un eșec intermitent costă mai mult decât minutul
  // economisit.
  workers: 1,
  fullyParallel: false,
  // Un test E2E care trece doar la a doua încercare ascunde exact clasa de defect
  // pentru care a fost scris: o cursă între interfață și server.
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],

  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "ro-RO",
    timezoneId: "Europe/Bucharest",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      // Baza se reconstruiește în aceeași comandă care pornește serverul: un
      // `globalSetup` separat ar depinde de ordinea în care Playwright pornește
      // lucrurile, iar ordinea aceea nu este ceva pe care vrem să ne bazăm.
      command:
        "uv run python -m app.cli reset-e2e && " +
        `uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/health/ready`,
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      // `VITE_API_MODE` intră în cod la **build**, nu la rulare: fără build aici,
      // `preview` ar servi un pachet vechi, construit pe backendul simulat, iar
      // suita ar trece fără să atingă vreodată serverul.
      command:
        `npm run build && ` +
        // `--host 127.0.0.1`: fara el, `vite preview` asculta pe `localhost`, care pe
        // Windows se rezolva intai la `::1`. Playwright interogheaza `127.0.0.1` si
        // asteapta degeaba un server care rula de fapt.
        `npm run preview -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      cwd: ".",
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: {
        VITE_API_MODE: "http",
        VITE_PROXY_TARGET: `http://127.0.0.1:${API_PORT}`,
      },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
