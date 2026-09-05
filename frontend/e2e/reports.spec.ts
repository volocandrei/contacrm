/**
 * Exporturile, într-un browser adevărat.
 *
 * **De ce merită un test E2E.** Descărcarea nu este un `<a href>`: ruta cere
 * autentificare, iar un token în URL este interzis (§27), deci fișierul se
 * citește cu `fetch` și se salvează dintr-un `blob:`. Drumul acela trece prin
 * cookie de sesiune, antete și `Content-Disposition` — adică exact locurile în
 * care lucrurile se rup fără ca vreun test unitar să observe.
 *
 * Ecranul scoate două fișiere diferite: **raportul** (numerele de pe ecran,
 * agregate) și **registrul** (un rând pe document, cu sumele citite din el).
 * Al doilea este singura cale prin care datele extrase ies din aplicație.
 *
 * Toate documentele sunt sintetice (§70).
 */
import { readFile } from "node:fs/promises";
import { expect, test, type Download, type Page } from "@playwright/test";
import { ACCOUNTS, incomingInvoice, loginAs, unique, uploadAndOpen, field } from "./support";

/** Conținutul fișierului descărcat, fără BOM-ul pe care îl cere Excel. */
async function contentOf(file: Download): Promise<string> {
  return (await readFile(await file.path(), "utf8")).replace(/^﻿/, "");
}

async function downloadFrom(page: Page, button: string): Promise<Download> {
  const started = page.waitForEvent("download");
  await page.getByRole("button", { name: button }).click();
  return started;
}

test("raportul se descarcă drept fișier, cu numele pus de server", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/rapoarte");

  const file = await downloadFrom(page, "Descarcă raportul");

  expect(file.suggestedFilename()).toContain("raport-documente");
  expect(file.suggestedFilename()).toMatch(/\.csv$/);
});

test("filtrele de pe ecran ajung și în fișier", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  await page.goto("/rapoarte?fromMonth=2026-08&toMonth=2026-08");

  const file = await downloadFrom(page, "Descarcă raportul");

  // Un export care ar acoperi altceva decât ce se vede ar fi mai rău decât niciunul.
  expect(file.suggestedFilename()).toContain("2026-08_2026-08");
});

test("ce s-a citit dintr-un document urcat acum iese în registru", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);

  // Testul își face propriul document, ca să poată cere înapoi exact valorile
  // scrise în el. Sprijinit pe ce au lăsat alte teste, ar fi trecut sau căzut
  // după ordinea de rulare.
  const number = unique();
  await uploadAndOpen(page, "registru.pdf", incomingInvoice({ number, total: "1.190,00" }));
  await expect(field(page, "documentNumber")).toHaveValue(number, { timeout: 30_000 });

  await page.goto("/rapoarte");
  const file = await downloadFrom(page, "Descarcă registrul");
  const lines = (await contentOf(file)).trim().split("\r\n");
  const columns = lines[0].split(";");
  const row = lines.slice(1).find((line) => line.includes(number));

  expect(file.suggestedFilename()).toContain("registru-documente");
  // Motivul pentru care există fișierul: până acum, sumele citite se puteau doar
  // privi pe ecran și retasta în programul de contabilitate.
  expect(row, `documentul ${number} lipsește din registru`).toBeDefined();

  const cells = (row ?? "").split(";");
  expect(cells).toHaveLength(columns.length);
  expect(cells[columns.indexOf("Data")]).toBe("14.08.2026");
  expect(cells[columns.indexOf("Serie")]).toBe("FCT");
  expect(cells[columns.indexOf("Număr")]).toBe(number);
  // Cu punct, Excel în setările românești ia suma ca text: o aliniază la stânga
  // și nu o adună. Fișierul pare bun până când cineva trage un total pe coloană.
  expect(cells[columns.indexOf("Total")]).toBe("1190,00");
});
