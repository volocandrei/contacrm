/**
 * Securitatea contului, într-un browser adevărat (§1, §45, §55).
 *
 * **De ce este drumul care merită un test end-to-end.** Aplicația va conține
 * documentele financiare ale unor firme reale. Parola care le păzește trebuia să
 * poată fi schimbată din aplicație — până acum nu se putea deloc: exista numai
 * resetarea făcută de un administrator **altcuiva**, iar pe o instalare
 * proaspătă administratorul este unul singur.
 *
 * **Contul pe care se schimbă parola se creează în test.** Dacă am schimba parola
 * unui cont din `seed-dev`, celelalte specificații din aceeași rulare nu s-ar mai
 * putea autentifica — un test care strică vecinii nu este un test, este o cursă.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, DEV_PASSWORD, loginAs, unique } from "./support";

async function logout(page: import("@playwright/test").Page): Promise<void> {
  // `/login` cu sesiune activă duce înapoi în aplicație, nu la formular.
  await page.getByRole("button", { name: "Meniu cont" }).click();
  await page.getByRole("menuitem", { name: "Deconectare" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test("un coleg nou își schimbă singur parola, iar cea veche nu mai merge", async ({ page }) => {
  const marker = unique().toLowerCase();
  const email = `securitate.${marker}@contacrm.test`;
  const first = "iarna-devreme-pe-strada-7";
  const second = "trei-mere-verzi-pe-pervaz";

  // 1. Administratorul îl adaugă. Parola inițială o pune el și i-o spune direct.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/administrare/utilizatori");
  await page.getByRole("button", { name: "Coleg nou" }).click();
  await page.locator("#user-fullName").fill(`Coleg ${marker}`);
  await page.locator("#user-email").fill(email);
  await page.locator("#user-password").fill(first);
  await page.getByRole("button", { name: "Adaugă colegul" }).click();
  await expect(page.getByRole("cell", { name: email })).toBeVisible();
  await logout(page);

  // 2. Colegul intră cu parola primită și își pune una a lui.
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Parolă").fill(first);
  await page.getByRole("button", { name: "Intră în cont" }).click();
  await expect(page.getByRole("navigation", { name: "Navigație principală" })).toBeVisible();

  await page.goto("/administrare/securitate");
  await page.locator("#current-password").fill(first);
  await page.locator("#new-password").fill(second);
  await page.locator("#repeat-password").fill(second);
  await page.getByRole("button", { name: "Schimbă parola" }).click();
  await expect(page.getByText(/parola a fost schimbată/i)).toBeVisible();

  // 3. Parola veche nu mai deschide nimic; cea nouă, da.
  await logout(page);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Parolă").fill(first);
  await page.getByRole("button", { name: "Intră în cont" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Parolă").fill(second);
  await page.getByRole("button", { name: "Intră în cont" }).click();
  await expect(page.getByRole("navigation", { name: "Navigație principală" })).toBeVisible();
});

test("formularul spune de ce o parolă slabă nu merge, înainte de apăsare", async ({ page }) => {
  // Motivele se calculează în browser, cu aceleași reguli ca serverul. Fără ele,
  // omul scrie, apasă, așteaptă și primește refuzul — de trei ori la rând, fiindcă
  // motivele ar veni unul câte unul.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/administrare/securitate");

  await page.locator("#current-password").fill(DEV_PASSWORD);
  await page.locator("#new-password").fill("aaaaaaaaaaaa");

  await expect(page.getByText(/caractere diferite/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Schimbă parola" })).toBeDisabled();
});

test("îmi văd sesiunea curentă, și niciun token în pagină", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/administrare/securitate");

  await expect(page.getByText("sesiunea curentă")).toBeVisible();

  // Un ecran care listează sesiuni nu are voie să livreze cheile lor.
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}/);
});
