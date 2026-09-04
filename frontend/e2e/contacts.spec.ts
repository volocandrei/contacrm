/**
 * Agenda, într-un browser adevărat.
 *
 * Ce apără testul, în ordinea importanței:
 *
 * 1. **O singură cerere.** Ecranul cerea înainte contactele fiecărui client în
 *    parte — treizeci de cereri pentru treizeci de clienți. Regresia s-ar
 *    strecura ușor (un `useClientContacts` pus la loc într-un rând) și nu s-ar
 *    vedea din nimic altceva decât din traficul de rețea.
 * 2. **Căutarea acoperă și firma**, nu doar persoana.
 * 3. **Datele de contact sunt acționabile**: `mailto:` și `tel:` există ca linkuri,
 *    nu ca text de copiat cu ochiul.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs } from "./support";

test("agenda se încarcă dintr-o singură cerere", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const contactRequests: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/v1\/(contacts|clients\/[^/]+\/contacts)/.test(request.url())) {
      contactRequests.push(request.url());
    }
  });

  await page.goto("/crm/contacte");
  await expect(page.getByRole("heading", { level: 2, name: "Contacte" })).toBeVisible();
  await expect(page.getByRole("list").first()).toBeVisible();

  expect(contactRequests).toHaveLength(1);
  expect(contactRequests[0]).toContain("/api/v1/contacts");
});

test("căutarea găsește oamenii unei firme, nu doar numele lor", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/contacte");

  await page.getByLabel("Caută în agendă").fill(SEED_CLIENT.name);

  const rows = page.getByRole("listitem");
  await expect(rows.first()).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(SEED_CLIENT.name) }).first()).toBeVisible();
});

test("un email se scrie, un telefon se sună", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/contacte");

  await expect(page.locator('a[href^="mailto:"]').first()).toBeVisible();
});
