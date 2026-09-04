/**
 * Coada de verificare, într-un browser adevărat.
 *
 * **Ce apără testul.** Ruta `next-review` a primit de la început un `after` —
 * „scoate din coadă documentul tocmai închis, ca operatorul să nu revină pe el"
 * — dar interfața nu a chemat-o niciodată așa. Cine aproba rămânea pe documentul
 * aprobat și mai avea de făcut două lucruri pentru fiecare document următor:
 * înapoi la coadă, deschide. La câteva sute de documente pe lună, asta se adună.
 *
 * Testul urcă două documente, aprobă unul și cere ca ecranul să fi trecut deja
 * pe altul, spunând ce s-a întâmplat cu cel dinainte.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, field, incomingInvoice, loginAs, unique, uploadAndOpen } from "./support";

test("aprobarea deschide singură următorul document", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  // Două documente proprii, ca să existe un „următor" indiferent de ce mai era
  // în coadă înainte.
  await uploadAndOpen(page, "prima.pdf", incomingInvoice({ number: unique(), total: "1.190,00" }));
  await expect(field(page, "documentNumber")).not.toHaveValue("", { timeout: 30_000 });
  const first = page.url();

  await uploadAndOpen(page, "a-doua.pdf", incomingInvoice({ number: unique(), total: "2.380,00" }));
  await expect(field(page, "documentNumber")).not.toHaveValue("", { timeout: 30_000 });

  await page.goto(first);
  await expect(field(page, "documentNumber")).not.toHaveValue("", { timeout: 30_000 });

  // Furnizorul nu se citește dintr-un PDF sintetic — îl completează operatorul,
  // ca în fluxul obișnuit. Aprobarea salvează singură corecțiile nesalvate.
  await field(page, "supplierName").fill("Tert Furnizor SRL");

  const approve = page.getByRole("button", { name: "Aprobă și arhivează" });
  await expect(approve).toBeEnabled();
  await approve.click();

  // Mesajul numește documentul aprobat: ecranul arată deja altul, iar fără nume
  // saltul ar părea o scăpare a aplicației.
  await expect(page.getByText(/a fost aprobat și arhivat/)).toBeVisible({ timeout: 20_000 });
  await expect(page).not.toHaveURL(first);
});
