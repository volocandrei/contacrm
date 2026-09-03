/**
 * Drumul complet al unui document, capăt la capăt.
 *
 * Un fișier urcat din browser trece prin stocare, coadă, extracție reală
 * (`pdf_text`), identificarea clientului după codul fiscal, verificare umană și
 * arhivare cu numele standardizat (§10) — și fiecare pas se verifică pe ecran,
 * nu în baza de date. Textul din PDF este scris de test, deci se poate cere
 * exact valoarea aceea înapoi: dacă extracția ar începe să inventeze, testul ar
 * cădea.
 *
 * Toate documentele sunt sintetice (§70).
 */
import { expect, test, type Page } from "@playwright/test";
import {
  ACCOUNTS,
  SEED_CLIENT,
  field,
  incomingInvoice,
  loginAs,
  unique,
  uploadAndOpen,
} from "./support";

/** Documentul este gata când extracția a scris ceva în formular. */
async function waitForExtraction(page: Page) {
  await expect(field(page, "documentNumber")).not.toHaveValue("", { timeout: 30_000 });
}

test("un PDF urcat ajunge citit, atribuit, corectat, aprobat și arhivat", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const number = unique();
  await uploadAndOpen(page, "factura-intrare.pdf", incomingInvoice({ number, total: "1.190,00" }));
  await waitForExtraction(page);

  // 1. Ce scrie în fișier ajunge pe ecran. Nu o valoare plauzibilă — chiar aceea.
  await expect(field(page, "documentNumber")).toHaveValue(number);
  await expect(field(page, "series")).toHaveValue("FCT");
  await expect(field(page, "totalAmount")).toHaveValue("1190.00");
  // Factura are și `Data scadentei`; confuzia dintre ele ar muta documentul în
  // altă lună contabilă.
  await expect(field(page, "documentDate")).toHaveValue("2026-08-14");

  // 2. Clientul se identifică singur, din CUI-ul citit de pe document.
  await expect(page.getByText(SEED_CLIENT.name).first()).toBeVisible();

  // 3. Direcția vine din rolul potrivirii: clientul nostru cumpără → intrare.
  await expect(field(page, "documentType")).toHaveValue("FACTURA_INTRARE");

  // 4. O corectură umană se salvează și rămâne.
  await field(page, "supplierName").fill("Tert Furnizor SRL");
  await page.getByRole("button", { name: "Salvează" }).click();
  await expect(page.getByRole("button", { name: "Salvează" })).toBeDisabled();

  await page.reload();
  await expect(field(page, "supplierName")).toHaveValue("Tert Furnizor SRL");

  // 5. Aprobarea și arhivarea sunt un singur act: un document aprobat care nu a
  //    ajuns în arhivă nu este nicăieri.
  await page.getByRole("button", { name: "Aprobă și arhivează" }).click();
  await expect(page.getByText("Arhivat").first()).toBeVisible({ timeout: 20_000 });

  // 6. În arhivă, sub numele standardizat din §10:
  //    `YYYY-MM-DD_[Tip]_[Client]_[SerieNumăr].pdf` — seria și numărul lipite.
  await page.goto("/documente/arhiva");
  await page.getByLabel("Caută documente").fill(number);
  await expect(page.getByText(new RegExp(`^2026-08-14_.*FCT${number}\\.pdf$`))).toBeVisible();
});

test("previzualizarea se încarcă autentificat, fără token în URL", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(
    page,
    "previzualizare.pdf",
    incomingInvoice({ number: unique(), total: "250,00" }),
  );
  await waitForExtraction(page);

  // `<img>` și `<object>` nu trimit antetul `Authorization`, iar un token în
  // query string este interzis (§27): conținutul se citește cu `fetch` și
  // elementului i se dă un URL de obiect.
  const frame = page.locator("object[data], img[src]").first();
  await expect(frame).toBeVisible();
  const source = (await frame.getAttribute("data")) ?? (await frame.getAttribute("src")) ?? "";

  expect(source).toMatch(/^blob:/);
  expect(source).not.toContain("token");
});

test("un document fără strat de text nu primește valori inventate", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  // O poză de bon fiscal nu are text de citit. Providerul întoarce un rezultat
  // gol, nu unul plauzibil: un câmp gol costă zece secunde de completat de pe
  // facsimil, unul greșit trece pe lângă operator.
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  await page.goto("/documente/inbox");
  await page.locator('input[type="file"]').setInputFiles({
    name: "bon.png",
    mimeType: "image/png",
    buffer: png,
  });

  const results = page.getByRole("list", { name: /încărcărilor/i });
  await results.getByRole("link", { name: "Deschide" }).click();

  await expect(field(page, "totalAmount")).toHaveValue("");
  await expect(field(page, "supplierName")).toHaveValue("");
});

test("același fișier urcat de două ori este recunoscut ca duplicat", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const content = incomingInvoice({ number: unique(), total: "99,00" });
  await uploadAndOpen(page, "original.pdf", content);
  await uploadAndOpen(page, "copie.pdf", content);

  // Același SHA-256: duplicatul se leagă de original în loc să intre a doua oară
  // în contabilitate.
  await expect(page.getByText(/duplicat/i).first()).toBeVisible();
});

test("un fișier neacceptat este refuzat cu un motiv, nu cu „a eșuat”", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/documente/inbox");

  await page.locator('input[type="file"]').setInputFiles({
    name: "note.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("nu este un document contabil"),
  });

  const alert = page.getByRole("alert").first();
  await expect(alert).toBeVisible();
  await expect(alert).not.toHaveText("");
});
