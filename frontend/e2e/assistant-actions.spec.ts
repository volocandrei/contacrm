/**
 * Propunerile asistentului, într-un browser adevărat.
 *
 * **Linia care nu se trece:** asistentul pregătește, omul apasă. Testul o
 * verifică pe amândouă capetele — că nu s-a întâmplat nimic până la click, și că
 * după click chiar s-a întâmplat, prin ruta obișnuită.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs, unique } from "./support";

async function openAssistant(page: import("@playwright/test").Page) {
  await page.keyboard.press("Control+j");
  const panel = page.getByRole("dialog", { name: "Asistent" });
  await expect(panel).toBeVisible();
  return panel;
}

test("sarcina se creează abia după confirmare", async ({ page }) => {
  const marker = unique();
  await loginAs(page, ACCOUNTS.admin);

  const panel = await openAssistant(page);
  await panel.getByLabel("Întrebarea ta").fill(`notează de verificat ${marker}`);
  await panel.getByRole("button", { name: "Trimite întrebarea" }).click();

  const confirm = panel.getByRole("button", { name: "Notează sarcina" });
  await expect(confirm).toBeVisible();
  // Rezumatul spune ce se întâmplă, pentru cineva care nu a citit conversația.
  await expect(panel.getByText(new RegExp(`Se creează sarcina.*${marker}`))).toBeVisible();

  // Până aici, nimic: kanbanul nu o are.
  await page.goto("/crm/sarcini");
  await expect(page.getByText(new RegExp(marker))).toHaveCount(0);

  // Confirmăm, și abia atunci apare.
  const again = await openAssistant(page);
  await again.getByLabel("Întrebarea ta").fill(`notează de verificat ${marker}`);
  await again.getByRole("button", { name: "Trimite întrebarea" }).click();
  await again.getByRole("button", { name: "Notează sarcina" }).click();
  await expect(again.getByRole("button", { name: "Gata" })).toBeVisible();

  await page.keyboard.press("Escape");
  await page.reload();
  await expect(page.getByText(new RegExp(marker)).first()).toBeVisible();
});

test("kanbanul poate adăuga o sarcină, nu doar să le mute", async ({ page }) => {
  const marker = unique();
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/sarcini");

  await page.getByRole("button", { name: "Sarcină nouă" }).click();
  await page.getByLabel("Ce trebuie făcut").fill(`Din kanban ${marker}`);
  await page.getByRole("button", { name: "Adaugă" }).click();

  await expect(page.getByText(`Din kanban ${marker}`).first()).toBeVisible();
});
