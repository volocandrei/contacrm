/**
 * Șabloanele de așteptări, într-un browser adevărat.
 *
 * **Ce apără testul.** Fără așteptări configurate, checklistul lunii este gol,
 * „Documente lipsă" nu are ce raporta, iar fiecare lună apare completă pentru că
 * nu i se cere nimic. Șablonul este drumul pe care un cabinet configurează
 * doisprezece clienți într-un minut, în loc de o după-amiază.
 *
 * Drumul trece prin patru locuri care se pot rupe separat: ecranul de profiluri,
 * salvarea, aplicarea pe clienții aleși, și — singurul care contează cu adevărat
 * — raportul care începe să ceară exact ce s-a configurat.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, SEED_CLIENT, loginAs, unique } from "./support";

/** O lună fără documente pentru clientul ăsta: raportul trebuie să-l arate oricum. */
const MONTH = "2026-06";

test("un profil configurează un client, iar raportul începe să ceară", async ({ page }) => {
  const name = `Profil ${unique()}`;

  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/contabilitate/sabloane");

  // 1. Profilul.
  await page.getByRole("button", { name: "Profil nou" }).click();
  await page.getByLabel("Nume").fill(name);
  await page.getByLabel("Factură intrare", { exact: true }).check();
  await page.getByLabel("Extras cont", { exact: true }).check();
  await page.getByRole("button", { name: "Creează profilul" }).click();

  // Salvat: apare în lista din stânga. Numele apare și pe butonul de aplicare,
  // deci se caută textul din listă, nu orice buton care îl conține.
  await expect(page.getByText(name, { exact: true })).toBeVisible();

  // 2. Aplicarea pe un client anume.
  await page.getByPlaceholder("Caută client").fill(SEED_CLIENT.name);
  await page.getByRole("checkbox", { name: SEED_CLIENT.name }).check();
  await page.getByRole("button", { name: /^Aplică/ }).click();
  await expect(page.getByText(/client configurat/)).toBeVisible();

  // 3. Partea care contează: raportul cere acum exact ce s-a configurat — și îl
  //    arată pe clientul care n-a trimis nimic, adică cel căruia îi lipsește tot.
  await page.goto(`/contabilitate/lipsa?referenceMonth=${MONTH}`);
  const row = page.getByRole("row", { name: new RegExp(SEED_CLIENT.name) });
  await expect(row).toBeVisible();
  await expect(row.getByText(/Extras cont/)).toBeVisible();
});

/**
 * Clientul acestui test, **altul** decât cel de mai sus.
 *
 * Suita rulează pe o singură bază, cu un singur worker: testul precedent îi
 * aplicase deja un profil lui Alfa, deci bifa era pusă, iar butonul de salvare
 * rămânea dezactivat — nu avea ce salva. Un test care depinde de ordinea în care
 * rulează celelalte trece azi și cade mâine, din motive care n-au legătură cu el.
 */
const OWN_CLIENT = "Beta Service SRL";

test("profilul se poate salva din ce e deja configurat pe un client", async ({ page }) => {
  // Drumul pe care se face primul profil: potrivești un client cu mâna, vezi că
  // e bun, îi dai un nume. Un formular gol ar fi însemnat să reintroduci
  // aceleași bife — și să greșești exact ce tocmai nimeriseși.
  const name = `Ca la Beta ${unique()}`;

  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/crm/clienti");
  await page.getByRole("link", { name: OWN_CLIENT }).first().click();
  // Așteptările stau în fila de contabilitate, nu pe „General".
  await page.getByRole("tab", { name: "Contabilitate" }).click();

  // Clientul vine deja configurat din setul sintetic — și asta **este**
  // precondiția scenariului: profilul se face din ce a potrivit cineva cu mâna.
  // Prima variantă a testului bifa un tip și salva înainte, ceea ce nu adăuga
  // nimic și, cum bifa era deja pusă, lăsa butonul dezactivat pe veci.
  await expect(page.getByRole("checkbox", { name: "Factură intrare" })).toBeChecked();

  await page.getByRole("button", { name: "Salvează lista ca profil" }).click();
  await page.getByLabel("Numele profilului").fill(name);
  await page.getByRole("button", { name: "Salvează profilul" }).click();

  await expect(page.getByText(new RegExp(`Profilul .${name}. a fost salvat`))).toBeVisible();

  await page.goto("/contabilitate/sabloane");
  await expect(page.getByText(name, { exact: true })).toBeVisible();
});
