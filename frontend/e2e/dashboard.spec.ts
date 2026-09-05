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
  const band = page.getByRole("region", { name: "Închiderea lunii" });

  await expect(band).toBeVisible();
  // Termenul lunii august cade în septembrie — nu în august, nu în luna 13.
  await expect(band).toContainText("25.09.2026");
  await expect(band).toContainText("august 2026");

  // Și spune cât mai e, nu doar data: numărul de zile schimbă ce faci azi mai
  // mult decât orice contor. Stă în antet, lângă luna la care se referă — era
  // scris a doua oară în bandă, cu alte cuvinte.
  const hero = page.getByRole("region", { name: "Luna în lucru" });
  await expect(hero).toContainText(/până la termen|termenul este azi|termen depășit/);
});

test("clientul care nu a trimis tot are un drum direct din panou", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await uploadAndOpen(page, "pentru-restante.pdf", incomingInvoice({ number: unique(), total: "238,00" }));

  await page.goto("/");
  const band = page.getByRole("region", { name: "Închiderea lunii" });
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

test("panoul deschide cu ce ai de făcut, iar cardurile duc unde se face", async ({ page }) => {
  // Panoul spunea, corect, ce s-a întâmplat: opt contoare de aceeași mărime. Nu
  // răspundea la întrebarea cu care începe dimineața — „cu ce încep?".
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/");

  const plan = page.getByRole("region", { name: "Ce ai de făcut" });
  await expect(plan).toBeVisible();

  const cards = plan.getByRole("link");
  const count = await cards.count();
  expect(count, "setul sintetic nu lasă nimic de făcut, deci testul ar fi vacuu").toBeGreaterThan(
    0,
  );

  // Fiecare card este un drum, nu o cifră: duce în ecranul unde se face treaba.
  const first = cards.first();
  await expect(first).toContainText(/Vezi|Atribuie|Deschide|Cere/);
  await first.click();
  await expect(page).toHaveURL(/\/documente\/|\/contabilitate\//);
});
