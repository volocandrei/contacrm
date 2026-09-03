/**
 * Ce vede fiecare rol, în browser.
 *
 * Ascunderea unui buton este ergonomie; autorizarea o face serverul, iar asta
 * este verificată în Python. Ce se verifică aici este că cele două chiar sunt de
 * acord: un buton oferit pe un drum pe care ruta îl refuză este un defect care
 * s-a mai întâmplat în proiectul ăsta (`availableActions` oferea `reprocess` pe
 * un document cu încercările epuizate, iar ruta răspundea 409).
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, field, incomingInvoice, loginAs, unique, uploadAndOpen } from "./support";

test("un operator poate încărca și corecta, dar nu poate aproba", async ({ page }) => {
  await loginAs(page, ACCOUNTS.operator);
  await uploadAndOpen(
    page,
    "de-la-operator.pdf",
    incomingInvoice({ number: unique(), total: "310,00" }),
  );

  await expect(field(page, "totalAmount")).toBeVisible();
  // Poate scrie…
  await expect(page.getByRole("button", { name: "Salvează" })).toBeVisible();
  // …dar aprobarea nu i se oferă deloc.
  await expect(page.getByRole("button", { name: "Aprobă și arhivează" })).toHaveCount(0);
});

test("meniul nu oferă uși încuiate", async ({ page }) => {
  // Un OPERATOR vedea „Utilizatori", „Roluri" și „Setări" în bara laterală, iar
  // fiecare îl trimitea într-un 403 — un meniu care minte despre ce se poate
  // face îl lasă pe om să creadă că aplicația este stricată.
  await loginAs(page, ACCOUNTS.operator);
  const menu = page.getByRole("navigation", { name: "Navigație principală" });

  await expect(menu.getByRole("link", { name: "Utilizatori" })).toHaveCount(0);
  await expect(menu.getByRole("link", { name: "Setări" })).toHaveCount(0);
  await expect(menu.getByRole("link", { name: "Jurnal audit" })).toHaveCount(0);
  // Ce poate face rămâne la locul lui.
  await expect(menu.getByRole("link", { name: "Inbox" })).toBeVisible();
});

test("un administrator vede administrarea", async ({ page }) => {
  // Perechea testului de mai sus: filtrarea trebuie să ascundă, nu să șteargă.
  await loginAs(page, ACCOUNTS.admin);
  const menu = page.getByRole("navigation", { name: "Navigație principală" });

  await expect(menu.getByRole("link", { name: "Utilizatori" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Setări" })).toBeVisible();
});

test("un verificator poate aproba", async ({ page }) => {
  await loginAs(page, ACCOUNTS.reviewer);
  await uploadAndOpen(
    page,
    "de-la-verificator.pdf",
    incomingInvoice({ number: unique(), total: "420,00" }),
  );

  await expect(field(page, "documentNumber")).not.toHaveValue("", { timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Aprobă și arhivează" })).toBeVisible();
});

test("ecranul de setări publică nume de provideri, nu secrete (§73)", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/administrare/setari");

  // Se așteaptă o valoare, nu ecranul: altfel se citește „Se încarcă…" și testul
  // trece sau cade după cât de repede răspunde serverul.
  await expect(page.getByText("OCR_PROVIDER")).toBeVisible();

  const body = (await page.locator("main").innerText()).toLowerCase();
  // Nimic care să semene a credențiale sau a adresă de bază de date.
  expect(body).not.toContain("secret_key");
  expect(body).not.toContain("database_url");
  expect(body).not.toContain("postgresql");
  expect(body).not.toContain("s3_secret");
});
