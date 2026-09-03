/**
 * Factura electronică, de la fișier la arhivă.
 *
 * De la 1 iulie 2024, între firme din România factura electronică este
 * obligatorie. Pentru un cabinet asta înseamnă că partea covârșitoare a
 * facturilor vine ca XML — un document **structurat**, în care fiecare valoare
 * stă într-un câmp cu nume. Verificarea umană devine o citire, nu o completare.
 *
 * Testul cere exact valorile scrise în fișier. Sunt inventate (§70), dar au
 * forma reală a unei facturi RO_CIUS.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, electronicInvoice, field, loginAs, unique, uploadAndOpen } from "./support";

test("o factură electronică este citită întreagă, fără nimic de completat", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const number = `FCT${Math.floor(Math.random() * 90000 + 10000)}`;
  await uploadAndOpen(
    page,
    "efactura.xml",
    electronicInvoice({ number, subtotal: "1000.00", vat: "190.00", total: "1190.00" }),
  );

  await expect(field(page, "documentNumber")).not.toHaveValue("", { timeout: 30_000 });

  // Tot ce scrie în XML ajunge pe ecran — inclusiv ce un PDF nu poate da:
  // numele părților, care într-un PDF stau într-un bloc de adresă fără etichetă.
  await expect(field(page, "series")).toHaveValue("FCT");
  await expect(field(page, "documentNumber")).toHaveValue(number.replace("FCT", ""));
  await expect(field(page, "documentDate")).toHaveValue("2026-08-14");
  await expect(field(page, "supplierName")).toHaveValue("Șerbănescu Impex SRL");
  await expect(field(page, "supplierTaxId")).toHaveValue("RO99887766");
  await expect(field(page, "customerName")).toHaveValue(SEED_CLIENT.name);
  await expect(field(page, "subtotal")).toHaveValue("1000.00");
  await expect(field(page, "vatAmount")).toHaveValue("190.00");
  await expect(field(page, "totalAmount")).toHaveValue("1190.00");
  await expect(field(page, "currency")).toHaveValue("RON");

  // Clientul cabinetului este cumpărătorul → factură de intrare.
  await expect(field(page, "documentType")).toHaveValue("FACTURA_INTRARE");
});

test("valorile dintr-un câmp cu nume nu sunt o presupunere", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(
    page,
    "certitudine.xml",
    electronicInvoice({
      number: `FCT${Math.floor(Math.random() * 90000 + 10000)}`,
      subtotal: "500.00",
      vat: "95.00",
      total: "595.00",
    }),
  );
  await expect(field(page, "totalAmount")).not.toHaveValue("", { timeout: 30_000 });

  // Ecranul arată proveniența fiecărui câmp. Într-un document structurat nu există
  // „80% sigur": elementul e acolo sau nu e, deci scrie „citit 100%".
  await expect(page.getByText("citit 100%").first()).toBeVisible();
});

test("XML-ul nu are facsimil, dar are ce citi", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(
    page,
    "redare.xml",
    electronicInvoice({
      number: `FCT${Math.floor(Math.random() * 90000 + 10000)}`,
      subtotal: "100.00",
      vat: "19.00",
      total: "119.00",
    }),
  );
  await expect(field(page, "totalAmount")).not.toHaveValue("", { timeout: 30_000 });

  // În locul imaginii, factura redată din câmpurile ei — spusă ca atare.
  await expect(page.getByText(/redare din câmpurile documentului/i)).toBeVisible();
  // Iar originalul rămâne la un clic distanță, neatins (§16).
  await expect(page.getByText("Documentul original (XML)")).toBeVisible();
});

test("o factură electronică se arhivează ca XML, nu convertită", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const number = `FCT${Math.floor(Math.random() * 90000 + 10000)}`;
  await uploadAndOpen(
    page,
    "de-arhivat.xml",
    electronicInvoice({ number, subtotal: "200.00", vat: "38.00", total: "238.00" }),
  );
  await expect(field(page, "totalAmount")).not.toHaveValue("", { timeout: 30_000 });

  await page.getByRole("button", { name: "Aprobă și arhivează" }).click();
  await expect(page.getByText("Arhivat").first()).toBeVisible({ timeout: 20_000 });

  // Originalul este ce s-a depus la ANAF. Un PDF „frumos" generat din el ar fi
  // altceva decât documentul, iar §16 spune că originalul nu se transformă.
  await page.goto("/documente/arhiva");
  await page.getByLabel("Caută documente").fill(number.replace("FCT", ""));
  await expect(page.getByText(new RegExp(`^2026-08-14_.*${number}\\.xml$`))).toBeVisible();
});

test("un XML care nu este factură este respins cu un motiv", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/documente/inbox");

  // Trece de validarea de tip — chiar este XML — dar nu are ce citi din el.
  // Documentul intră în sistem și ajunge în eroare, cu explicația la vedere.
  await page.locator('input[type="file"]').setInputFiles({
    name: "configurare.xml",
    mimeType: "application/xml",
    buffer: Buffer.from(
      `<?xml version="1.0"?><configurare><valoare>${unique()}</valoare></configurare>`,
      "utf8",
    ),
  });

  const results = page.getByRole("list", { name: /încărcărilor/i });
  await results.getByRole("link", { name: "Deschide" }).click();

  await expect(page.getByText(/eroare/i).first()).toBeVisible({ timeout: 30_000 });
});
