/**
 * Onorariile, într-un browser adevărat și pe API-ul real.
 *
 * Ce apără testele, în ordinea importanței:
 *
 * 1. **Încasarea marcată rămâne marcată.** O bifă care se pierde la reîncărcare
 *    este mai rea decât un buton lipsă: te face să crezi că ai închis un rând pe
 *    care nu l-ai închis, iar la sfârșit de lună cifra nu se potrivește cu banca.
 * 2. **Restanțele vechi se văd.** Sunt singurele care nu se mai văd nicăieri
 *    altundeva: luna trece, ecranul se schimbă, banii rămân neîncasați.
 * 3. **Banii nu se văd de la orice rol.** Lista este ordinea în care cabinetul
 *    își ține clienții după bani.
 */
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs } from "./support";

const PAID = `Anulează încasarea · ${SEED_CLIENT.name}`;
const UNPAID = `Am încasat · ${SEED_CLIENT.name}`;

/** Rândul unui client anume. Fără el, „primul rând" înseamnă alt client la fiecare rulare. */
function buttonIn(page: Page, name: string) {
  return page.getByRole("row").filter({ hasText: SEED_CLIENT.name }).getByRole("button", { name });
}

/**
 * Apasă și așteaptă **răspunsul serverului**, nu butonul.
 *
 * Un buton dezactivat înseamnă „se salvează", nu „s-a salvat" — lecția care a
 * picat de două ori în CI, o dată la documente și o dată la termene.
 */
async function toggle(page: Page, name: string) {
  const saved = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/fees/payments") && response.request().method() !== "GET",
  );
  await buttonIn(page, name).click();
  await saved;
}

test("ecranul arată luna, cifrele ei și restanțele vechi", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/onorarii");

  await expect(page.getByRole("heading", { level: 2, name: "Onorarii" })).toBeVisible();
  await expect(page.getByText("De încasat").first()).toBeVisible();
  // Setul de development lasă intenționat o lună neîncasată în urmă.
  await expect(page.getByRole("heading", { name: "Neîncasate din lunile trecute" })).toBeVisible();
  // Și un client fără onorariu stabilit: ecranul trebuie să arate și cine a fost
  // uitat, nu doar cine e configurat.
  await expect(page.getByText("fără onorariu").first()).toBeVisible();
});

test("o încasare marcată rămâne marcată după reîncărcare", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/onorarii");
  await expect(page.getByRole("row").filter({ hasText: SEED_CLIENT.name })).toBeVisible();

  const wasPaid = (await buttonIn(page, PAID).count()) > 0;
  const before = wasPaid ? PAID : UNPAID;
  const after = wasPaid ? UNPAID : PAID;

  await toggle(page, before);
  await expect(buttonIn(page, after)).toBeVisible();

  await page.reload();

  // Aici s-ar fi văzut o scriere confirmată înainte de a ajunge în baza de date.
  await expect(buttonIn(page, after)).toBeVisible();

  // Înapoi cum era, ca rulările următoare să pornească din aceeași stare.
  await toggle(page, after);
  await expect(buttonIn(page, before)).toBeVisible();
});

test("fișa clientului arată onorariul și ultimele luni facturate", async ({ page }) => {
  // Întrebarea de la telefon — „eu am plătit în martie" — se pune pe fișa
  // clientului, nu pe ecranul lunii.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/clienti");
  await page.getByRole("link", { name: SEED_CLIENT.name }).first().click();
  await page.getByRole("tab", { name: "Contabilitate" }).click();

  await expect(page.getByRole("heading", { name: "Onorariu lunar" })).toBeVisible();
  await expect(page.getByText("Ultimele luni facturate")).toBeVisible();
});

test("luna se descarcă drept fișier, cu numele pus de server", async ({ page }) => {
  // Motivul pentru care există fișierul: cine emite facturile lucrează în alt
  // program, iar până acum retasta sumele de pe ecran, client cu client.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/onorarii");

  const started = page.waitForEvent("download");
  await page.getByRole("button", { name: "Descarcă luna" }).click();
  const file = await started;

  expect(file.suggestedFilename()).toMatch(/^onorarii-\d{4}-\d{2}\.csv$/);

  const text = (await readFile((await file.path())!, "utf8")).replace(/^﻿/, "");
  const lines = text.trim().split("\r\n");
  const columns = lines[0]!.split(";");
  expect(columns).toContain("Client");
  expect(columns).toContain("Documente");

  const row = lines.slice(1).find((line) => line.startsWith(SEED_CLIENT.name));
  expect(row, `${SEED_CLIENT.name} lipsește din fișier`).toBeDefined();
});

test("un contabil nu ajunge la onorarii", async ({ page }) => {
  await loginAs(page, ACCOUNTS.accountant);

  // Nici în meniu: ascunderea este ergonomie, refuzul îl dă serverul (§32).
  await expect(page.getByRole("link", { name: "Onorarii" })).toHaveCount(0);

  await page.goto("/crm/onorarii");
  await expect(page.getByRole("alert").first()).toBeVisible();
});
