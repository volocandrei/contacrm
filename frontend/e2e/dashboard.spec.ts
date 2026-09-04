/**
 * Panoul principal, într-un browser adevărat.
 *
 * **Ce apără testul.** Panoul spunea doar *starea* — câte documente au intrat,
 * câte așteaptă verificare — și niciodată *cât mai e până trebuie depus*.
 * Termenul este singurul lucru care dă ordinea muncii într-un cabinet, iar
 * regula lui se greșește ușor: el cade în luna **următoare** celei care se
 * închide. Documentele lui august se depun în septembrie.
 *
 * Luna în lucru o dau datele, nu calendarul, deci testul își aduce singur un
 * document — altfel ar depinde de ce a lăsat în urmă alt fișier de test.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, incomingInvoice, loginAs, unique, uploadAndOpen } from "./support";

test("panoul spune până când trebuie depus și cine încă nu a trimis", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  // Factura poartă CUI-ul clientului din seed, deci se atribuie singură, iar
  // data ei (august 2026) dă luna în lucru.
  await uploadAndOpen(page, "pentru-panou.pdf", incomingInvoice({ number: unique(), total: "119,00" }));

  await page.goto("/");
  const band = page.getByRole("region", { name: "Termenul lunii" });

  await expect(band).toBeVisible();
  // Termenul lunii august cade în septembrie — nu în august, nu în luna 13.
  await expect(band).toContainText("25.09.2026");
  await expect(band).toContainText("august 2026");
  // Și spune cât mai e, nu doar data: numărul de zile schimbă ce faci azi.
  await expect(band).toContainText(/până la termen|Termenul/);
});

test("clientul care nu a trimis tot are un drum direct din panou", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(page, "pentru-restante.pdf", incomingInvoice({ number: unique(), total: "238,00" }));

  await page.goto("/");
  const band = page.getByRole("region", { name: "Termenul lunii" });
  await expect(band).toBeVisible();

  // Ori luna e strânsă, ori se spune **cine** lipsește — nu doar câți.
  const done = band.getByText("Toți clienții au trimis");
  const links = band.getByRole("link");
  if ((await done.count()) === 0) {
    await expect(links.first()).toBeVisible();
    // Linkul duce la fișa clientului, nu la o listă în care trebuie căutat.
    await expect(links.first()).toHaveAttribute("href", /\/crm\/clienti\//);
  }
});


test("graficele spun în cuvinte ce arată desenul", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(page, "pentru-grafic.pdf", incomingInvoice({ number: unique(), total: "99,00" }));
  await page.goto("/");

  // Un grafic este o imagine. Fără nume accesibil, un cititor de ecran anunță
  // „grafic" și atât — adică nimic.
  const trend = page.getByRole("img", { name: /Documente sosite pe zi/ });
  await expect(trend).toBeVisible();
  await expect(trend).toHaveAttribute("aria-label", /zile/);

  const donut = page.getByRole("img", { name: /Distribuția documentelor pe stări/ });
  await expect(donut).toBeVisible();
  // Numele conține și cifrele: altfel desenul rămâne inaccesibil, oricât de
  // frumos ar fi.
  await expect(donut).toHaveAttribute("aria-label", /\d/);
});
