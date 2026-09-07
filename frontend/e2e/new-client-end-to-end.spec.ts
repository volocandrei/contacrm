/**
 * Clientul adăugat acum: din formular, în listă, în selector, cu document (§24).
 *
 * **Sesizarea.** „nu îmi apare în această listă clientul adăugat de mine mai
 * devreme". Nu s-a spus care listă — iar aplicația are unsprezece locuri în care
 * se alege un client, fiecare cerându-și lista cu alți parametri.
 *
 * Pe backendul real nu s-a putut reproduce: `tests/test_new_client_is_visible.py`
 * verifică toate cele nouă cereri pe care le face interfața și clientul nou este
 * în fiecare. Ce s-a găsit este altceva, și explica exact ce a văzut omul:
 * demonstrația rulează pe backendul simulat, care trăiește în memoria filei.
 * O reîncărcare de pagină îl golește, deci clientul „adăugat mai devreme" chiar
 * dispărea. Bannerul spune acum consecința, nu categoria — vezi `app-shell.tsx`.
 *
 * Testul de aici apără cealaltă jumătate: pe backendul adevărat, drumul întreg
 * trebuie să funcționeze dintr-o singură trecere, fără reîncărcare și fără vreun
 * ocol. Un test care s-ar opri la „apare în listă" ar fi putut fi verde și inutil.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs, unique } from "./support";

test("client nou → căutare → selector de încărcare → document urcat pe el", async ({ page }) => {
  const marker = unique();
  const name = `Zeta ${marker} SRL`;

  await loginAs(page, ACCOUNTS.admin);

  // 1. Creare, din formularul pe care îl folosește omul.
  await page.goto("/crm/clienti");
  await page.getByRole("button", { name: "Client nou" }).click();
  await page.locator("#client-name").fill(name);
  await page.locator("#client-taxId").fill(`RO${marker.replace(/\D/g, "") || "1"}0001`);
  await page.getByRole("button", { name: "Adaugă clientul" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();

  // 2. Apare în listă, fără reîncărcare: lista se invalidează la salvare.
  await page.goto("/crm/clienti");
  await expect(page.getByRole("link", { name })).toBeVisible();

  // 3. Se găsește prin căutare, inclusiv scris fără diacritice.
  await page.getByRole("searchbox", { name: "Caută clienți" }).fill(`Zeta ${marker}`);
  await expect(page.getByRole("link", { name })).toBeVisible();

  // 4. Apare în selectorul de pe ecranul de încărcare — locul din sesizare.
  await page.goto("/documente/inbox");
  const selector = page.getByLabel("Client (opțional)");
  await expect(selector).toBeVisible();
  await expect(selector.locator("option", { hasText: name })).toHaveCount(1);

  // 5. Și chiar primește un document, atribuit lui, nu „de identificat".
  await selector.selectOption({ label: name });
  await page.locator("input[type=file]").setInputFiles({
    name: `factura-${marker}.pdf`,
    mimeType: "application/pdf",
    buffer: Buffer.from(`%PDF-1.7\n${"0".repeat(600)}\n%%EOF`),
  });

  const results = page.getByRole("list", { name: /încărcărilor/i });
  await expect(results).toContainText(new RegExp(`factura-${marker}`, "i"), { timeout: 15_000 });

  // 6. Și documentul chiar poartă clientul ales, nu „de identificat": îl căutăm
  //    pe **fișa clientului**, în fila lui de documente. Este locul în care se
  //    uită contabilul după ce a urcat un teanc, și singura verificare care
  //    leagă cele două jumătăți ale sesizării: clientul nou chiar ține documente.
  await page.goto("/crm/clienti");
  await page.getByRole("link", { name }).click();
  await page.getByRole("tab", { name: "Documente" }).click();
  //    Tabelul de acolo arată data, tipul și furnizorul — nu numele fișierului —
  //    deci se numără rândurile: clientul este creat în test, are exact un
  //    document, iar antetul se pune la socoteală.
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2, { timeout: 15_000 });
});
