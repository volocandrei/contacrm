/**
 * Exportul raportului, într-un browser adevărat.
 *
 * **De ce merită un test E2E.** Descărcarea nu este un `<a href>`: ruta cere
 * autentificare, iar un token în URL este interzis (§27), deci fișierul se
 * citește cu `fetch` și se salvează dintr-un `blob:`. Drumul acela trece prin
 * cookie de sesiune, antete și `Content-Disposition` — adică exact locurile în
 * care lucrurile se rup fără ca vreun test unitar să observe.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs } from "./support";

test("raportul se descarcă drept fișier, cu numele pus de server", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/rapoarte");

  const started = page.waitForEvent("download");
  await page.getByRole("button", { name: "Descarcă CSV" }).click();
  const file = await started;

  expect(file.suggestedFilename()).toContain("raport-documente");
  expect(file.suggestedFilename()).toMatch(/\.csv$/);
});

test("filtrele de pe ecran ajung și în fișier", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/rapoarte?fromMonth=2026-08&toMonth=2026-08");

  const started = page.waitForEvent("download");
  await page.getByRole("button", { name: "Descarcă CSV" }).click();
  const file = await started;

  // Un export care ar acoperi altceva decât ce se vede ar fi mai rău decât niciunul.
  expect(file.suggestedFilename()).toContain("2026-08_2026-08");
});
