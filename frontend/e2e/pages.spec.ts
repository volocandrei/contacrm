/**
 * Fiecare ecran din navigație, deschis cu adevărat (§36, §73).
 *
 * **De ce există.** Suita verifica fluxurile importante — autentificare,
 * documente, permisiuni — dar niciun test nu deschidea pur și simplu toate
 * paginile. Consecința: două ecrane livrate cereau un endpoint pe care backendul
 * nu îl are (`/messages` și `/clients/:id/messages`). În modul simulat mergeau
 * perfect; în modul real răspundeau 404, iar unul dintre ele rămânea gol fără să
 * spună nimic. Auditul le-a găsit cu un `curl`, nu cu un test.
 *
 * Testul de aici este ieftin și acoperă exact clasa aceea de defect: nicio cerere
 * eșuată, nicio eroare în consolă, un titlu care chiar se randează.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs } from "./support";

const SCREENS = [
  ["/", "Panou principal"],
  ["/crm/clienti", "Clienți"],
  ["/crm/contacte", "Contacte"],
  ["/crm/sarcini", "Sarcini"],
  ["/documente/inbox", "Inbox documente"],
  ["/documente/procesare", "În procesare"],
  ["/documente/verificare", "Verificare"],
  ["/documente/arhiva", "Arhivă"],
  ["/contabilitate/perioade", "Perioade"],
  ["/contabilitate/lipsa", "Documente lipsă"],
  ["/comunicare/mesaje", "Mesaje"],
  ["/comunicare/sabloane", "Șabloane"],
  ["/comunicare/remindere", "Remindere"],
  ["/rapoarte", "Rapoarte"],
  ["/administrare/utilizatori", "Utilizatori"],
  ["/administrare/roluri", "Roluri"],
  ["/administrare/setari", "Setări"],
  ["/administrare/surse", "Surse documente"],
  ["/administrare/audit", "Jurnal de audit"],
] as const;

test("fiecare ecran se deschide, fără cereri eșuate și fără erori în consolă", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];

  // Ascultătorii se pun **după** autentificare, deliberat. Înainte de ea,
  // `GET /me` și `POST /auth/refresh` răspund 401 — corect, așa află aplicația
  // că nu există sesiune. Ecranul de autentificare are testele lui în
  // `auth.spec.ts`; aici ne interesează ce se întâmplă după ce ai intrat.
  await loginAs(page, ACCOUNTS.admin);

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedRequests.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });

  for (const [path] of SCREENS) {
    await page.goto(path);
    // Titlul paginii, oricare ar fi el: dacă ecranul a rămas alb, nu există niciunul.
    await expect(page.getByRole("heading").first()).toBeVisible();
  }

  expect(failedRequests, "niciun ecran nu are voie să ceară ceva ce serverul nu are").toEqual([]);
  expect(consoleErrors, "niciun ecran nu are voie să lase erori în consolă").toEqual([]);
});

test("un ecran care nu există duce înapoi la panou, nu la o pagină albă", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/nu-exista-asa-ceva");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading").first()).toBeVisible();
});
