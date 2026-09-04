/**
 * Documentele fără client identificat.
 *
 * **Ce apără testul.** Contorul `unmatched` exista din prima zi în
 * `/dashboard/counts`, dar nu avea ecran: singurul loc unde apăreau documentele
 * neatribuite era lista de verificare, unde se amestecau cu o muncă de alt fel —
 * acolo corectezi un câmp, aici cauți firma. Mai rău, insigna din meniu numără
 * doar `REVIEW_REQUIRED`, deci spunea 7 în timp ce lista arăta 11.
 *
 * Testul își creează singur situația, în loc să depindă de ce a rămas în bază:
 * urcă o factură emisă către un CUI pe care cabinetul nu-l are, deci
 * neidentificabilă.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs, makePdf, unique } from "./support";

/** O factură către o firmă care nu este client: nimic de potrivit. */
function invoiceForAStranger(number: string): Buffer {
  return makePdf([
    "FACTURA FISCALA",
    "Furnizor: Tert Furnizor SRL",
    "CUI: RO99887766",
    "Cumparator: Firma Necunoscuta SRL",
    "CIF: RO12009988",
    `Seria FCT nr. ${number}`,
    "Data emiterii: 14.08.2026",
    "Total de plata: 100,00 lei",
  ]);
}

test("un document fără client stă la Neatribuite, nu la Verificare", async ({ page }) => {
  const number = unique();
  await loginAs(page, ACCOUNTS.admin);

  await page.goto("/documente/inbox");
  await page.locator('input[type="file"]').setInputFiles({
    name: "strain.pdf",
    mimeType: "application/pdf",
    buffer: invoiceForAStranger(number),
  });
  const results = page.getByRole("list", { name: /încărcărilor/i });
  await expect(results.getByRole("link", { name: "Deschide" })).toBeVisible({ timeout: 30_000 });

  const row = page.getByRole("row", { name: new RegExp(number) });

  await page.goto("/documente/neatribuite");
  await expect(row).toBeVisible({ timeout: 30_000 });

  // Și **nu** în lista de verificare: acolo se corectează câmpuri, aici se caută
  // firma. Amestecate, contorul din meniu nu mai poate fi adevărat pentru niciuna.
  await page.goto("/documente/verificare");
  await expect(row).toHaveCount(0);
});

test("meniul duce la ecranul de neatribuite", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  const menu = page.getByRole("navigation", { name: "Navigație principală" });

  await menu.getByRole("link", { name: /Neatribuite/ }).click();

  await expect(page).toHaveURL(/\/documente\/neatribuite$/);
  await expect(page.getByRole("heading", { level: 2, name: "Neatribuite" })).toBeVisible();
});

test("din verificare se pornește coada", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/documente/verificare");

  await page.getByRole("link", { name: "Pornește verificarea" }).click();

  await expect(page).toHaveURL(/\/documente\/verificare\/coada$/);
});
