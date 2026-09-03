/**
 * Adăugarea unui client, într-un browser adevărat.
 *
 * **De ce contează acest drum.** Auditul de producție a arătat că un cabinet nou
 * nu putea adăuga niciun client — CRM-ul era numai de citire. Fără clienți nu se
 * leagă niciun dosar din OneDrive și niciun email nu poate fi atribuit, deci
 * acesta este primul lucru pe care îl face cineva la prima pornire.
 *
 * Emailul contactului nu este un detaliu de formular: după el ajunge un atașament
 * primit la clientul potrivit (§8).
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs, unique } from "./support";

test("un client nou primește un contact, iar amândouă apar în listă", async ({ page }) => {
  const marker = unique();
  const name = `Client E2E ${marker} SRL`;
  const email = `contact.${marker.toLowerCase()}@exemplu.test`;

  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/clienti");
  await page.getByRole("button", { name: "Client nou" }).click();

  await page.locator("#client-name").fill(name);
  await page.locator("#client-taxId").fill(`RO${marker.replace(/\D/g, "") || "1"}0000`);
  await page.locator("#client-address").fill("Str. Verificată 1");
  await page.getByRole("button", { name: "Adaugă clientul" }).click();

  // Salvarea duce direct pe fișa clientului: pasul următor este contactul.
  await expect(page.getByRole("heading", { name })).toBeVisible();

  await page.getByRole("tab", { name: "Contacte" }).click();
  await page.getByRole("button", { name: "Contact nou" }).click();
  await page.locator("#contact-fullName").fill("Maria Ionescu");
  await page.locator("#contact-email").fill(email.toUpperCase());
  await page.getByRole("button", { name: "Adaugă contactul" }).click();

  // Adresa se păstrează în litere mici — altfel potrivirea expeditorului n-ar
  // funcționa niciodată.
  await expect(page.getByRole("cell", { name: email })).toBeVisible();

  await page.goto("/crm/clienti");
  // Nu `getByLabel`: antetul aplicației are propria căutare globală, iar cele două
  // etichete se potrivesc amândouă.
  await page.locator('input[placeholder="Denumire, CUI, adresă…"]').fill(name);
  await expect(page.getByRole("link", { name })).toBeVisible();
});

test("aceeași firmă nu poate fi adăugată de două ori", async ({ page }) => {
  const marker = unique();
  const taxId = `RO${Date.now()}`.slice(0, 12);

  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/clienti");

  for (const suffix of ["Prima", "A Doua"]) {
    await page.getByRole("button", { name: "Client nou" }).click();
    await page.locator("#client-name").fill(`${suffix} ${marker} SRL`);
    await page.locator("#client-taxId").fill(suffix === "Prima" ? taxId : taxId.replace("RO", ""));
    await page.getByRole("button", { name: "Adaugă clientul" }).click();

    if (suffix === "Prima") {
      await expect(page.getByRole("heading", { name: `Prima ${marker} SRL` })).toBeVisible();
      await page.goto("/crm/clienti");
    }
  }

  // `RO…` și `…` sunt același cod fiscal. A doua intrare trebuie refuzată, cu
  // numele clientului care îl are deja — nu cu un mesaj generic.
  await expect(page.getByRole("alert")).toContainText(`Prima ${marker} SRL`);
});

test("un operator nu vede butonul de client nou", async ({ page }) => {
  await loginAs(page, ACCOUNTS.operator);
  await page.goto("/crm/clienti");

  // Nivelul 2: antetul aplicației are un `h1` cu numele ecranului curent.
  await expect(page.getByRole("heading", { level: 2, name: "Clienți" })).toBeVisible();
  // Meniul nu oferă uși încuiate; autorizarea rămâne pe server.
  await expect(page.getByRole("button", { name: "Client nou" })).toHaveCount(0);
});
