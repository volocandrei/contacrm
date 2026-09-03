/**
 * Sesiunea, într-un browser adevărat.
 *
 * Partea asta a produsului nu se poate verifica altfel. Cookie-urile `httpOnly`
 * sunt invizibile din JavaScript prin definiție, deci un test care rulează *în*
 * pagină nu poate spune dacă sesiunea trăiește într-un cookie sau într-un token
 * lăsat la vedere. Aici se vede.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, DEV_PASSWORD, login, loginAs } from "./support";

test("o parolă greșită nu intră, și spune de ce", async ({ page }) => {
  await login(page, ACCOUNTS.admin, "parola-gresita");

  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("un email inexistent arată exact același lucru ca o parolă greșită", async ({ page }) => {
  // Altfel formularul de autentificare devine un instrument de enumerare a
  // conturilor: „acest email nu există" spune atacatorului pe cine să caute.
  await login(page, "nimeni@contacrm.test", DEV_PASSWORD);
  const unknownAccount = await page.getByRole("alert").textContent();

  await login(page, ACCOUNTS.admin, "parola-gresita");
  const wrongPassword = await page.getByRole("alert").textContent();

  expect(unknownAccount).toBe(wrongPassword);
});

test("un cont dezactivat nu intră", async ({ page }) => {
  await login(page, ACCOUNTS.viewer, DEV_PASSWORD);

  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("sesiunea supraviețuiește unei reîncărcări", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  await page.reload();

  // Dacă sesiunea ar sta în memoria paginii, reîncărcarea ar fi trimis-o la login.
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByRole("navigation", { name: "Navigație principală" })).toBeVisible();
});

test("tokenul nu este niciodată la vederea paginii", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const stored = await page.evaluate(() => ({
    local: Object.entries(localStorage).map(([key, value]) => `${key}=${value}`),
    session: Object.entries(sessionStorage).map(([key, value]) => `${key}=${value}`),
    // Un cookie citibil din JavaScript nu este `httpOnly`.
    cookies: document.cookie,
  }));

  const everything = [...stored.local, ...stored.session, stored.cookies].join(" ");
  // Un JWT are trei bucăți despărțite de punct și începe cu antetul codat.
  expect(everything).not.toMatch(/eyJ[A-Za-z0-9_-]{8,}\./);
  expect(stored.cookies).not.toContain("contacrm_access");
});

test("niciun token nu ajunge într-un URL (§27)", async ({ page }) => {
  // Un token în query string ajunge în logurile serverului, în istoricul
  // browserului și în antetul `Referer`. Testul se uită la **toate** cererile pe
  // care le face pagina, nu doar la cele pe care ni le amintim.
  const suspicious: string[] = [];
  page.on("request", (request) => {
    if (/[?&](token|access_token|jwt|auth)=/i.test(request.url())) suspicious.push(request.url());
  });

  await loginAs(page, ACCOUNTS.admin);
  await page.getByRole("link", { name: "Inbox" }).click();
  await page.waitForLoadState("networkidle");

  expect(suspicious).toEqual([]);
});

test("logout închide sesiunea pe server, nu doar pe ecran", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  await page.getByRole("button", { name: "Meniu cont" }).click();
  await page.getByRole("menuitem", { name: "Deconectare" }).click();
  await expect(page).toHaveURL(/\/login/);

  // Reîncărcarea unei rute protejate nu are voie să reintre.
  await page.goto("/documente/inbox");
  await expect(page).toHaveURL(/\/login/);
});
