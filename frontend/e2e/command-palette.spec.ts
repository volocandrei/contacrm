/**
 * Paleta de comenzi, într-un browser adevărat.
 *
 * Ce apără testul: drumul scurt către un client rămâne scurt. Toate cele trei
 * lucruri care îl compun se pot strica separat — scurtătura de tastatură,
 * căutarea care întreabă serverul, și navigarea la apăsarea lui Enter — și
 * niciunul nu se vede dintr-un test unitar.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs } from "./support";

test.describe("paleta de comenzi", () => {
  test("Ctrl+K duce la un client căutat după CUI, fără mouse", async ({ page }) => {
    await loginAs(page, ACCOUNTS.admin);

    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Caută în aplicație" });
    await expect(palette).toBeVisible();

    // CUI-ul este exact ce câmpul vechi din antet nu putea găsi: orice se scria
    // acolo ducea în inboxul de documente.
    await page.keyboard.type(SEED_CLIENT.taxId);
    await expect(palette.getByRole("option", { name: new RegExp(SEED_CLIENT.name) })).toBeVisible();

    // Primul rezultat este selectat din start — Enter îl deschide.
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/crm\/clienti\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: SEED_CLIENT.name })).toBeVisible();
  });

  test("găsește ecranele după nume, fără diacritice", async ({ page }) => {
    await loginAs(page, ACCOUNTS.admin);
    await page.getByRole("button", { name: /Caută client/ }).click();

    await page.keyboard.type("sarcini");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/crm\/sarcini$/);
  });

  test("selecția este anunțată, iar la închidere focalizarea se întoarce", async ({ page }) => {
    await loginAs(page, ACCOUNTS.admin);
    const trigger = page.getByRole("button", { name: /Caută client/ });
    await trigger.click();

    // Selecția se mută cu săgețile, dar focalizarea rămâne în câmp: singurul
    // mod în care un cititor de ecran află ce e selectat este acest atribut.
    const input = page.getByRole("combobox", { name: /Caută client/ });
    await expect(input).toHaveAttribute("aria-activedescendant", /^palette-/);

    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
  });

  test("Escape o închide fără să navigheze nicăieri", async ({ page }) => {
    await loginAs(page, ACCOUNTS.admin);
    const before = page.url();

    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog", { name: "Caută în aplicație" })).toBeVisible();
    await page.keyboard.press("Escape");

    await expect(page.getByRole("dialog", { name: "Caută în aplicație" })).toBeHidden();
    expect(page.url()).toBe(before);
  });
});
