/**
 * Sistemul învață de la cine vin documentele, într-un browser adevărat.
 *
 * **Ce se poate verifica aici și ce nu.** Învățarea se declanșează la atribuirea
 * unui document **sosit de undeva** — email, OneDrive, SPV. Un document urcat de
 * mână din inbox nu are expeditor extern, iar drumurile care aduc documente cer
 * credențiale externe. Calea pozitivă este deci acoperită de testele de backend,
 * cu recepții adevărate în bază.
 *
 * Ce se verifică aici este **garanția de siguranță**, care se vede în interfață:
 * un document urcat de un coleg nu învață nimic. Dacă ar învăța, adresa colegului
 * s-ar lega de un client, și tot ce urcă el ar ajunge acolo — un defect tăcut,
 * care s-ar descoperi peste luni.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs, makePdf, unique } from "./support";

/** O factură către o firmă care nu este client: nimic de potrivit după CUI. */
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

test("un document urcat de mână nu învață nimic", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  await page.goto("/documente/inbox");
  await page.locator('input[type="file"]').setInputFiles({
    name: "necunoscut.pdf",
    mimeType: "application/pdf",
    buffer: invoiceForAStranger(unique()),
  });
  const results = page.getByRole("list", { name: /încărcărilor/i });
  await results.getByRole("link", { name: "Deschide" }).click();

  // Documentul a ajuns fără client identificabil: îl atribuim, ca un om.
  const chooser = page.getByLabel("Alege clientul documentului");
  await expect(chooser).toBeVisible({ timeout: 30_000 });
  await chooser.selectOption({ label: `${SEED_CLIENT.name} · ${SEED_CLIENT.taxId}` });
  await expect(page.getByText("Clientul a fost atribuit.")).toBeVisible({ timeout: 20_000 });

  // Și **nu** s-a învățat nimic: nu există expeditor extern de reținut.
  await page.goto("/crm/clienti");
  await page.getByRole("link", { name: SEED_CLIENT.name }).first().click();
  await expect(page.getByRole("heading", { name: "Expeditori recunoscuți" })).toHaveCount(0);
});

test("panoul de expeditori lipsește cât timp nu s-a învățat nimic", async ({ page }) => {
  // Un cabinet nou nu are de ce să vadă o listă goală și o explicație despre
  // ceva ce nu s-a întâmplat încă.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/clienti");
  await page.getByRole("link", { name: SEED_CLIENT.name }).first().click();

  await expect(page.getByRole("heading", { name: "Date generale" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Expeditori recunoscuți" })).toHaveCount(0);
});
