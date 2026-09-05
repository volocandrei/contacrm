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

test("arhiva conține documentele și registrul, într-un singur fișier", async ({ page }) => {
  // Documentele se puteau descărca doar unul câte unul. Un client care pleacă,
  // o predare de an, o cerere de la un control — toate cer teancul întreg.
  await loginAs(page, ACCOUNTS.admin);

  // Un document propriu, ca arhiva să aibă ce conține indiferent de ordinea
  // în care rulează celelalte teste.
  const number = unique();
  await uploadAndOpen(page, "arhiva.pdf", incomingInvoice({ number, total: "1.190,00" }));
  await expect(field(page, "documentNumber")).toHaveValue(number, { timeout: 30_000 });

  await page.goto("/rapoarte");
  const file = await downloadFrom(page, "Descarcă arhiva");

  expect(file.suggestedFilename()).toContain("arhiva-documente");
  expect(file.suggestedFilename()).toMatch(/\.zip$/);

  // Se deschide și are înăuntru ce trebuie: o rută care întoarce un ZIP gol ar
  // trece orice verificare care se oprește la numele fișierului.
  const zip = await readFile(await file.path());
  const names = entriesOf(zip);
  expect(names).toContain("registru.csv");
  expect(names.some((name) => name.endsWith(".pdf"))).toBe(true);
});

/**
 * Numele intrărilor dintr-un ZIP, citite din directorul central.
 *
 * Fără o bibliotecă: `zip` nu este o dependență a frontendului, iar testul are
 * nevoie doar de nume. Directorul central stă la coada fișierului, iar fiecare
 * intrare începe cu semnătura 0x02014b50.
 */
function entriesOf(zip: Buffer): string[] {
  const names: string[] = [];
  for (let index = 0; index < zip.length - 46; index += 1) {
    if (zip.readUInt32LE(index) !== 0x02014b50) continue;
    const length = zip.readUInt16LE(index + 28);
    names.push(zip.subarray(index + 46, index + 46 + length).toString("utf8"));
  }
  return names;
}
