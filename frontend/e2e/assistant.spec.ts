/**
 * Asistentul, într-un browser adevărat și pe API-ul real.
 *
 * Ce apără testul, în ordinea importanței:
 *
 * 1. **Cifra vine din date.** Răspunsul la „cât e de lucru?" trebuie să fie
 *    același număr pe care îl arată contorul din meniu. Un asistent care
 *    aproximează este mai rău decât unul absent: numărul lui ajunge într-un
 *    email către client.
 * 2. **Nu navighează singur.** Propune un drum; ecranul se schimbă doar după ce
 *    omul apasă. Un salt neașteptat dintr-un ecran de lucru pierde ce aveai pe el.
 * 3. **Se deschide de oriunde**, cu tastatura.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs } from "./support";

async function openAssistant(page: import("@playwright/test").Page) {
  await page.keyboard.press("Control+j");
  const panel = page.getByRole("dialog", { name: "Asistent" });
  await expect(panel).toBeVisible();
  return panel;
}

test("răspunde cu cifra din date, nu cu una plauzibilă", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const counts = await page.evaluate(async () => {
    const response = await fetch("/api/v1/dashboard/counts", { credentials: "include" });
    return (await response.json()) as { review: number; unmatched: number };
  });

  const panel = await openAssistant(page);
  await panel.getByLabel("Întrebarea ta").fill("cât e de lucru?");
  await panel.getByRole("button", { name: "Trimite întrebarea" }).click();

  const waiting = counts.review + counts.unmatched;
  if (waiting === 0) {
    await expect(panel.getByText("Coada este goală")).toBeVisible();
  } else if (counts.review > 0) {
    await expect(panel.getByText(new RegExp(`${counts.review} documente? așteaptă`))).toBeVisible();
  }
});

test("propune drumul, dar îl deschide omul", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  const before = page.url();

  const panel = await openAssistant(page);
  await panel.getByLabel("Întrebarea ta").fill(`deschide ${SEED_CLIENT.name}`);
  await panel.getByRole("button", { name: "Trimite întrebarea" }).click();

  const link = panel.getByRole("button", { name: new RegExp(`Deschide ${SEED_CLIENT.name}`) });
  await expect(link).toBeVisible();
  // Până aici nu s-a mutat nimic: propunerea nu este o navigare.
  expect(page.url()).toBe(before);

  await link.click();
  await expect(page).toHaveURL(/\/crm\/clienti\/[0-9a-f-]+$/);
});

test("spune ce poate, când nu înțelege", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const panel = await openAssistant(page);
  await panel.getByLabel("Întrebarea ta").fill("care e capitala Franței");
  await panel.getByRole("button", { name: "Trimite întrebarea" }).click();

  await expect(panel.getByText("Pot răspunde la")).toBeVisible();
});

test("Escape îl închide și dă focalizarea înapoi", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  const trigger = page.getByRole("button", { name: /Deschide asistentul/ });
  await trigger.click();

  await expect(page.getByRole("dialog", { name: "Asistent" })).toBeVisible();
  await page.keyboard.press("Escape");

  await expect(page.getByRole("dialog", { name: "Asistent" })).toBeHidden();
  await expect(trigger).toBeFocused();
});
