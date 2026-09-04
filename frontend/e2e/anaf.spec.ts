/**
 * Ecranul e-Factura, într-un browser adevărat.
 *
 * **Ce se poate verifica aici și ce nu.** Autorizarea la ANAF cere un certificat
 * digital calificat prezentat de browser, la propriu. Nu există cont de
 * serviciu, nu există mediu de test fără certificat. Prin urmare drumul întreg —
 * autorizare, listare, descărcare — **nu poate fi acoperit de nicio suită
 * automată**; el se verifică o singură dată, manual, la instalare.
 *
 * Ce se verifică aici este starea în care se află **fiecare instalare nouă**:
 * fără credențiale configurate. Ecranul trebuie să spună ce lipsește, nu să
 * ofere un buton care eșuează cu o eroare de la ANAF — și asta chiar se poate
 * verifica, pentru că este cazul obișnuit, nu unul de margine.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs } from "./support";

test("un cabinet fără credențiale ANAF află ce lipsește", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/administrare/e-factura");

  // Nivelul 2: antetul aplicației are un `h1` cu numele ecranului curent.
  await expect(page.getByRole("heading", { level: 2, name: "e-Factura" })).toBeVisible();
  await expect(page.getByText("Integrarea nu este configurată pe server.")).toBeVisible();
  await expect(page.getByText("ANAF_CLIENT_ID")).toBeVisible();

  // Niciun buton care ar eșuea cu o eroare venită de la ANAF.
  await expect(page.getByRole("button", { name: "Autorizează la ANAF" })).toHaveCount(0);
});

test("meniul îl duce pe administrator acolo", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  await page.getByRole("link", { name: "e-Factura" }).click();

  await expect(page).toHaveURL(/\/administrare\/e-factura$/);
});

test("un operator nu are ecranul în meniu", async ({ page }) => {
  await loginAs(page, ACCOUNTS.operator);

  // Meniul nu oferă uși încuiate; autorizarea rămâne pe server.
  await expect(page.getByRole("link", { name: "e-Factura" })).toHaveCount(0);
});
