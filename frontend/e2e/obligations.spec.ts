/**
 * Termenele de depunere, într-un browser adevărat și pe API-ul real.
 *
 * Ce apără testele, în ordinea importanței:
 *
 * 1. **Restanțele se văd.** Un termen ratat este singurul lucru pe care ecranul
 *    chiar nu are voie să-l piardă: costă bani, iar consecința apare la client.
 * 2. **Bifa rămâne bifată.** O marcare care se pierde la reîncărcare este mai
 *    rea decât un buton lipsă — te face să crezi că ai făcut ceva ce n-ai făcut.
 * 3. **Marcarea este o decizie contabilă**, nu una de operare.
 */
import { expect, test, type Page } from "@playwright/test";
import { ACCOUNTS, loginAs } from "./support";

/** Primul rând cu buton de marcare, oricare ar fi el. */
function anyRow(page: Page) {
  return page.getByRole("button", { name: /^Marchează depus/ }).first();
}

test("ecranul arată ce are cabinetul de depus, cu restanțele separate", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/termene");

  await expect(page.getByRole("heading", { level: 2, name: "Termene" })).toBeVisible();
  // Setul de development are clienți cu declarații lunare configurate, deci
  // există întotdeauna termene trecute: fereastra pornește din urmă.
  await expect(page.getByRole("heading", { name: "Restanțe" })).toBeVisible();
  await expect(page.getByText(/nedepuse după termen/)).toBeVisible();
});

test("o depunere marcată rămâne marcată după reîncărcare", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/termene");

  const button = anyRow(page);
  await expect(button).toBeVisible();
  const label = await button.getAttribute("aria-label");
  const anulare = label!.replace("Marchează depus", "Anulează depunerea");

  await button.click();
  await expect(page.getByRole("button", { name: anulare })).toBeVisible();

  await page.reload();

  // Aici s-ar fi văzut o scriere confirmată înainte de a fi confirmată în baza
  // de date: butonul ar fi arătat din nou „Marchează depus".
  await expect(page.getByRole("button", { name: anulare })).toBeVisible();

  // Curățenie, ca rulările următoare să pornească din aceeași stare.
  await page.getByRole("button", { name: anulare }).click();
  await expect(page.getByRole("button", { name: label! })).toBeVisible();
});

test("un operator vede termenele, dar nu le poate marca", async ({ page }) => {
  await loginAs(page, ACCOUNTS.operator);
  await page.goto("/contabilitate/termene");

  await expect(page.getByRole("heading", { level: 2, name: "Termene" })).toBeVisible();

  // Ecranul îl lasă să apese; serverul refuză. Mesajul apare pe rând, nu într-o
  // pagină de eroare care ar pierde ce avea pe ecran.
  await anyRow(page).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
});
