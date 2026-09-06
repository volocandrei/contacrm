/**
 * Termenele de depunere, într-un browser adevărat și pe API-ul real.
 *
 * Ce apără testele, în ordinea importanței:
 *
 * 1. **Restanțele se văd.** Un termen ratat este singurul lucru pe care ecranul
 *    chiar nu are voie să-l piardă: costă bani, iar consecința apare la client.
 * 2. **Bifa rămâne bifată.** O marcare care se pierde la reîncărcare este mai
 *    rea decât un buton lipsă — te face să crezi că ai făcut ceva ce n-ai făcut.
 * 3. **Marcarea este o decizie contabilă**, nu una de operare.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs } from "./support";

/** Primul rând cu buton de marcare, oricare ar fi el. */
function anyRow(page: Page) {
  return page.getByRole("button", { name: /^Marchează depus/ }).first();
}

test("ecranul arată ce are cabinetul de depus, cu restanțele separate", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/termene");

  await expect(page.getByRole("heading", { level: 2, name: "Termene" })).toBeVisible();
  // Setul de development are clienți cu declarații lunare configurate, deci
  // există întotdeauna termene trecute: fereastra pornește din urmă.
  await expect(page.getByRole("heading", { name: "Restanțe" })).toBeVisible();
  await expect(page.getByText(/nedepuse după termen/)).toBeVisible();
});

test("o depunere marcată rămâne marcată după reîncărcare", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/termene");

  const button = anyRow(page);
  await expect(button).toBeVisible();
  const label = await button.getAttribute("aria-label");
  const anulare = label!.replace("Marchează depus", "Anulează depunerea");

  await button.click();
  await expect(page.getByRole("button", { name: anulare })).toBeVisible();

  await page.reload();

  // Aici s-ar fi văzut o scriere confirmată înainte de a fi confirmată în baza
  // de date: butonul ar fi arătat din nou „Marchează depus".
  await expect(page.getByRole("button", { name: anulare })).toBeVisible();

  // Curățenie, ca rulările următoare să pornească din aceeași stare.
  await page.getByRole("button", { name: anulare }).click();
  await expect(page.getByRole("button", { name: label! })).toBeVisible();
});

test("un operator vede termenele, dar nu le poate marca", async ({ page }) => {
  await loginAs(page, ACCOUNTS.operator);
  await page.goto("/contabilitate/termene");

  await expect(page.getByRole("heading", { level: 2, name: "Termene" })).toBeVisible();

  // Ecranul îl lasă să apese; serverul refuză. Mesajul apare pe rând, nu într-o
  // pagină de eroare care ar pierde ce avea pe ecran.
  await anyRow(page).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
});

test("o declarație bifată pe fișa clientului ajunge în termene", async ({ page }) => {
  // Bucla care lipsea: obligațiile se puteau seta doar prin API, deci un client
  // adăugat din interfață n-ar fi apărut niciodată în „Termene" — tăcut, adică
  // în felul cel mai prost cu putință.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/clienti");
  await page.getByRole("link", { name: SEED_CLIENT.name }).first().click();
  await page.getByRole("tab", { name: "Contabilitate" }).click();

  const bilant = page.getByRole("checkbox", { name: /Situații financiare anuale/ });
  await expect(bilant).toBeVisible();
  const wasChecked = await bilant.isChecked();
  if (wasChecked) await bilant.uncheck();
  else await bilant.check();

  await page.getByRole("button", { name: "Salvează declarațiile" }).click();
  await expect(page.getByRole("button", { name: "Salvează declarațiile" })).toBeDisabled();

  await page.reload();
  await page.getByRole("tab", { name: "Contabilitate" }).click();
  await expect(page.getByRole("checkbox", { name: /Situații financiare anuale/ })).toBeChecked({
    checked: !wasChecked,
  });

  // Înapoi cum era, ca rulările următoare să pornească din aceeași stare.
  const again = page.getByRole("checkbox", { name: /Situații financiare anuale/ });
  if (wasChecked) await again.check();
  else await again.uncheck();
  await page.getByRole("button", { name: "Salvează declarațiile" }).click();
  await expect(page.getByRole("button", { name: "Salvează declarațiile" })).toBeDisabled();
});

test("un grup întreg se marchează dintr-o apăsare", async ({ page }) => {
  // Un cabinet depune D300 pentru douăzeci de clienți într-o singură ședință.
  // Bifate una câte una, asta înseamnă douăzeci de apăsări.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/termene");

  const all = page.getByRole("button", { name: /^Marchează toate \(\d+\)$/ }).first();
  await expect(all).toBeVisible();
  const before = await page.getByRole("button", { name: /^Marchează depus/ }).count();

  await all.click();

  // Rândurile marcate își schimbă butonul; cele rămase se văd în listă.
  await expect(page.getByRole("button", { name: /^Marchează depus/ })).not.toHaveCount(before);
  await expect(page.getByRole("button", { name: /^Anulează depunerea/ }).first()).toBeVisible();
});

test("termenul se schimbă din catalog și se vede imediat în listă", async ({ page }) => {
  // Ecranul de termene spune că termenele sunt ale cabinetului. Fără ecranul de
  // catalog, afirmația era adevărată despre cod și falsă despre ce putea face
  // omul: ruta exista, drumul către ea nu.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/termene");

  await page.getByRole("link", { name: "Administrează termenele" }).click();
  await expect(page).toHaveURL(/\/administrare\/declaratii$/);

  const day = page.getByLabel("În ce zi cade termenul pentru D300", { exact: true });
  await expect(day).toBeVisible();
  const original = await day.inputValue();

  await saveDay(page, day, "15");

  // Ce apără testul: schimbarea din catalog **mută termenele**, fără repornire.
  // Niciuna dintre declarațiile din catalogul inițial nu cade pe 15, deci un
  // titlu de grup cu ziua 15 nu poate veni decât din schimbarea de mai sus.
  await page.goto("/contabilitate/termene");
  const onTheFifteenth = page.getByRole("heading", { name: /^15\.\d{2}\.\d{4}$/ });
  await expect(onTheFifteenth.first()).toBeVisible();

  // Înapoi cum era, ca rulările următoare să pornească din aceeași stare.
  await page.goto("/administrare/declaratii");
  await saveDay(
    page,
    page.getByLabel("În ce zi cade termenul pentru D300", { exact: true }),
    original,
  );
  await page.goto("/contabilitate/termene");
  await expect(page.getByRole("heading", { name: /^15\.\d{2}\.\d{4}$/ })).toHaveCount(0);
});

/**
 * Schimbă ziua și **așteaptă răspunsul**, nu butonul.
 *
 * „Salvează" este dezactivat și cât timp cererea este în zbor (`!dirty ||
 * isPending`), deci `toBeDisabled` trece imediat după clic — iar pasul următor
 * pleacă peste o salvare neterminată. Este exact defectul reparat o dată în
 * `document-flow.spec.ts`; l-am rescris aici din memorie și l-am reintrodus.
 */
async function saveDay(page: Page, day: Locator, value: string): Promise<void> {
  await day.fill(value);
  const row = page.getByRole("row", { name: /D300/ }).first();
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().includes("/obligations/types/") &&
      response.ok(),
  );
  await row.getByRole("button", { name: "Salvează" }).click();
  await saved;
}
