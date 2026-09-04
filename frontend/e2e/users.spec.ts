/**
 * Administrarea colegilor, într-un browser adevărat.
 *
 * **Ce apără testul.** Până acum singurul drum era `app.cli create-admin`, o
 * comandă gândită pentru primul cont al unei baze goale. Drumul nou trece prin
 * formular, rețea, sesiune și autentificarea contului creat — adică prin exact
 * locurile în care lucrurile se rup fără ca vreun test unitar să observe.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs, unique } from "./support";

test("un coleg adăugat din interfață se poate autentifica imediat", async ({ page }) => {
  const marker = unique().toLowerCase();
  const email = `coleg.${marker}@contacrm.test`;
  const password = `parola-coleg-${marker}`;

  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/administrare/utilizatori");
  await page.getByRole("button", { name: "Coleg nou" }).click();

  await page.locator("#user-fullName").fill(`Coleg ${marker}`);
  await page.locator("#user-email").fill(email);
  await page.locator("#user-password").fill(password);
  await page.getByRole("button", { name: "Adaugă colegul" }).click();

  await expect(page.getByRole("cell", { name: email })).toBeVisible();

  // Rostul întreg: contul nou funcționează, fără terminal. Întâi ieșim —
  // `/login` cu sesiune activă duce înapoi în aplicație, nu la formular.
  await page.getByRole("button", { name: "Meniu cont" }).click();
  await page.getByRole("menuitem", { name: "Deconectare" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Parolă").fill(password);
  await page.getByRole("button", { name: "Intră în cont" }).click();

  await expect(page.getByRole("navigation", { name: "Navigație principală" })).toBeVisible();
});

test("propriul cont nu se poate dezactiva", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/administrare/utilizatori");

  // Rândul propriu este marcat, iar butoanele de acces sunt blocate: un cabinet
  // cu un singur administrator nu are voie să rămână afară din propria aplicație.
  const myRow = page.getByRole("row").filter({ hasText: ACCOUNTS.admin });
  await expect(myRow.getByRole("button", { name: "Dezactivează" })).toBeDisabled();
  await expect(myRow.getByRole("combobox")).toBeDisabled();
});

test("un operator nu ajunge la ecranul de utilizatori", async ({ page }) => {
  await loginAs(page, ACCOUNTS.operator);

  // Meniul nu oferă uși încuiate; autorizarea rămâne pe server.
  await expect(page.getByRole("link", { name: "Utilizatori" })).toHaveCount(0);
});
