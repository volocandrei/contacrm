/**
 * Reconcilierea, într-un browser adevărat (§15, §55, §78).
 *
 * **De ce drumul acesta merită un test end-to-end.** Reconcilierea este ora cea
 * mai lungă a lunii într-un cabinet, iar ecranul are trei bucăți care trebuie să
 * se potrivească: lista de rânduri, propunerile pentru rândul deschis, și
 * confirmarea care schimbă amândouă. Fiecare bucată are testul ei; ce nu are test
 * unitar este **ordinea** în care se folosesc.
 *
 * Rulează pe backendul real, deci extrasul trebuie să existe acolo. Fără el,
 * testul verifică starea goală — ceea ce este tot o verificare, dar alta: ecranul
 * trebuie să spună limpede că nu are nimic de arătat, nu să rămână gol.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs } from "./support";

test("ecranul de bancă se deschide și spune ce are de făcut", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/banca");

  await expect(page.getByRole("heading", { name: "Extrase bancare" })).toBeVisible();

  // Pe o instalare fără extrase importate, ecranul explică ce se așteaptă de la
  // om — nu rămâne o pagină albă din care nu se înțelege dacă s-a rupt ceva.
  const empty = page.getByText(/niciun extras importat/i);
  const statements = page.getByRole("button", { name: /de lămurit|reconciliat/ });

  await expect(empty.or(statements.first())).toBeVisible();
});

test("panoul de propuneri cere întâi un rând deschis", async ({ page }) => {
  // Regula de interfață care ține tot ecranul: propunerile sunt **pentru un rând**.
  // Un panou care ar arăta ceva fără rând selectat ar sugera că sistemul propune
  // singur, pe toate — exact impresia pe care ecranul trebuie să nu o dea.
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/banca");

  const hint = page.getByText(/deschide un rând din extras/i);
  const empty = page.getByText(/niciun extras importat/i);

  await expect(hint.or(empty)).toBeVisible();
});

test("meniul duce la bancă din grupul de contabilitate", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  const nav = page.getByRole("navigation", { name: "Navigație principală" });
  const group = nav.getByRole("button", { name: "Contabilitate" });

  // Grupul își ține starea deschis/închis în stocarea locală, deci poate fi deja
  // deschis. Un clic necondiționat l-ar fi închis, iar testul ar fi căutat un
  // link ascuns — eșec care nu spune nimic despre navigație.
  if ((await group.getAttribute("aria-expanded")) !== "true") {
    await group.click();
  }
  await nav.getByRole("link", { name: "Bancă" }).click();

  await expect(page).toHaveURL(/\/contabilitate\/banca/);
  await expect(page.getByRole("heading", { name: "Extrase bancare" })).toBeVisible();
});
