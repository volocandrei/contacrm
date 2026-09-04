/**
 * Solicitarea de documente, dusă până la capăt.
 *
 * Aplicația știe ce lipsește fiecărui client și până când, dar nu poate
 * **trimite** — asta cere un provider și rămâne în Faza 2. Butonul acoperă exact
 * distanța rămasă: textul iese gata scris, iar contabilul îl trimite din clientul
 * lui de email. Testul verifică drumul întreg, inclusiv că în clipboard ajunge
 * chiar mesajul, nu un șablon cu locurile necompletate.
 *
 * Documentul se urcă întâi pentru că perioada contabilă **se derivă**: fără
 * niciun document, luna nu există, deci nu are cum să-i lipsească ceva.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, incomingInvoice, loginAs, unique, uploadAndOpen } from "./support";

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

/** Luna facturii sintetice din `support.ts` (documentul este datat 14.08.2026). */
const MONTH = "2026-08";

test("solicitarea ajunge în clipboard, cu lista lipsurilor completată", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(page, "factura-intrare.pdf", incomingInvoice({ number: unique(), total: "1.190,00" }));

  await page.goto(`/contabilitate/lipsa?referenceMonth=${MONTH}`);

  const button = page.getByRole("button", { name: /Copiază solicitarea/ }).first();
  await expect(button).toBeVisible();
  await button.click();

  await expect(page.getByRole("button", { name: /Copiat/ }).first()).toBeVisible();

  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("Bună ziua,");
  expect(copied).toContain("august 2026");
  // Termenul: documentele lui august se depun în septembrie.
  expect(copied).toMatch(/\d{2}\.09\.2026/);
  // Locurile din șablon trebuie completate, nu copiate ca atare.
  expect(copied).not.toContain("{{");
  // Semnătura este a cabinetului, nu a aplicației.
  expect(copied).not.toContain("ContaCRM");
});
