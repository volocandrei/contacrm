/**
 * Portalul clientului, într-un browser adevărat.
 *
 * **Ce apără testul.** Partea grea a muncii unui cabinet este adunarea
 * documentelor, iar linkul mută efortul de la client la aplicație. Drumul întreg
 * trece prin patru locuri care se pot rupe separat: butonul care deschide linkul,
 * pagina publică — **fără autentificare** —, urcarea, și sosirea documentului la
 * clientul potrivit.
 *
 * Testul îl parcurge într-o singură sesiune de browser, exact ca un cabinet care
 * dă linkul unui client.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs, makePdf, unique } from "./support";

test("un client trimite un document fără cont, iar el ajunge la dosarul lui", async ({
  page,
  context,
}) => {
  const marker = unique();

  // 1. Cabinetul deschide linkul.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/clienti");
  await page.getByRole("link", { name: SEED_CLIENT.name }).first().click();
  await page.getByRole("button", { name: /Deschide un link|Încă un link/ }).click();

  const address = page.locator("code").filter({ hasText: "/incarca/" });
  await expect(address).toBeVisible();
  const url = (await address.textContent()) ?? "";
  expect(url).toContain("/incarca/");

  // 2. Clientul îl deschide — într-un context nou, fără sesiune. Este partea
  //    care contează: dacă pagina ar cere autentificare, tot mecanismul ar fi
  //    inutil, fiindcă clientul nu are cont și nu vrea unul.
  const guest = await context.browser()!.newContext();
  const clientPage = await guest.newPage();
  await clientPage.goto(url.replace(/^https?:\/\/[^/]+/, ""));

  await expect(clientPage.getByRole("heading", { name: "Trimite documentele" })).toBeVisible();
  // Și nu află cine este clientul cabinetului.
  await expect(clientPage.getByText(SEED_CLIENT.name)).toHaveCount(0);

  // 3. Trimite un fișier.
  await clientPage.locator('input[type="file"]').setInputFiles({
    name: `de-la-client-${marker}.pdf`,
    mimeType: "application/pdf",
    buffer: makePdf([`Document trimis de client ${marker}`]),
  });
  await expect(clientPage.getByText(/Am primit documentul/)).toBeVisible({ timeout: 20_000 });
  await guest.close();

  // 4. Documentul este în aplicație, la clientul potrivit, fără să fi trecut
  //    prin „neatribuit": apartenența vine din link.
  await page.goto("/documente/inbox");
  await page.getByLabel("Caută documente").fill(marker);
  await expect(page.getByRole("row", { name: new RegExp(marker) })).toBeVisible({
    timeout: 20_000,
  });
  await page.goto("/documente/neatribuite");
  await expect(page.getByText(new RegExp(marker))).toHaveCount(0);
});

test("un link care nu există nu spune nimic despre el", async ({ page }) => {
  await page.goto("/incarca/token-care-nu-exista");

  await expect(page.getByText(/Linkul nu mai este valabil/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Alege fișiere" })).toHaveCount(0);
});
