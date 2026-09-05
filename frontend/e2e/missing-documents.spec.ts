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

  // Și drumul pe care sosește răspunsul: o listă cu ce lipsește îi spune
  // clientului *ce* să caute și îl lasă singur cu *cum* trimite.
  expect(copied).toContain("/incarca/");
  expect(copied).toMatch(/valabil până la \d{2}\.\d{2}\.\d{4}/);

  // Și rămâne o urmă pe ecran. Fără ea, peste trei zile cabinetul cere de două
  // ori aceluiași client și îl uită complet pe altul.
  await expect(page.getByText("Pregătit Astăzi").first()).toBeVisible();
  await page.getByLabel("Cerere").selectOption("never");
  await expect(page.getByText("Pregătit Astăzi")).toHaveCount(0);
});

test("linkul din mesajul copiat chiar duce undeva", async ({ page, context }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(page, "factura-intrare.pdf", incomingInvoice({ number: unique(), total: "1.190,00" }));

  await page.goto(`/contabilitate/lipsa?referenceMonth=${MONTH}`);
  await page.getByRole("button", { name: /Copiază solicitarea/ }).first().click();
  await expect(page.getByRole("button", { name: /Copiat/ }).first()).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());

  // Exact ce face clientul: ia adresa din mesaj și o deschide, fără sesiune.
  // Un link mort trimis unui client este mai rău decât niciun link — omul
  // încearcă, nu merge, și data viitoare nu mai încearcă.
  const url = copied.split("\n").find((line) => line.includes("/incarca/"))!;
  const guest = await context.browser()!.newContext();
  const clientPage = await guest.newPage();
  await clientPage.goto(url.replace(/^https?:\/\/[^/]+/, ""));

  await expect(clientPage.getByRole("heading", { name: "Trimite documentele" })).toBeVisible();
  await guest.close();
});

test("trimiterea neconfigurată spune ce lipsește, nu că a eșuat", async ({ page }) => {
  // Fără `SMTP_*`, aplicația nu poate trimite. Ce contează este **cum** o spune:
  // nimic nu s-a stricat, doar nu i s-a spus prin ce să trimită. Un „a eșuat
  // trimiterea" ar trimite pe cineva să caute defectul în altă parte.
  await loginAs(page, ACCOUNTS.admin);
  // Ca la celelalte teste din fișier: perioada se **derivă** din documente, deci
  // fără unul urcat luna nu există și rândul n-ar avea ce cere.
  await uploadAndOpen(
    page,
    "factura-trimitere.pdf",
    incomingInvoice({ number: unique(), total: "1.190,00" }),
  );
  await page.goto(`/contabilitate/lipsa?referenceMonth=${MONTH}`);

  const send = page.getByRole("button", { name: "Trimite pe email" }).first();
  await expect(send).toBeVisible();
  await send.click();

  const alert = page.getByRole("alert").first();
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/NOTIFICATIONS_ENABLED|SMTP/);
});
