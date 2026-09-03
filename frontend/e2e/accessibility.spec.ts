/**
 * Accesibilitate și layout (§75, §76).
 *
 * **De ce există.** Suita verifica fluxuri, nu forma paginilor. Auditul de
 * producție a măsurat: pe un ecran de 390px, bara laterală deschisă (256px) nu
 * mai încăpea — fiecare pagină depășea cu 50px, iar titlul din antet se strângea
 * la lățime zero, adică dispărea. Nimic nu semnala nimic, pentru că niciun test
 * nu se uita vreodată la o altă lățime decât cea implicită.
 *
 * Aplicația este un instrument de birou și desktopul rămâne prioritar. Dar un
 * ecran care se rupe nu are nicio scuză, iar regresia este ieftin de prins.
 */
import { expect, test } from "@playwright/test";
import { ACCOUNTS, loginAs } from "./support";

/** Ecranele reprezentative: un tabel, un formular, un panou, o integrare. */
const SCREENS = [
  "/",
  "/crm/clienti",
  "/documente/inbox",
  "/documente/verificare",
  "/contabilitate/lipsa",
  "/rapoarte",
  "/administrare/surse",
] as const;

const VIEWPORTS = [
  { label: "desktop", width: 1440, height: 900 },
  { label: "tabletă", width: 820, height: 1180 },
  { label: "telefon", width: 390, height: 844 },
] as const;

test("fiecare buton, link și câmp are un nume pe care îl poate citi cineva", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  const anonymous: string[] = [];

  for (const path of SCREENS) {
    await page.goto(path);
    await expect(page.getByRole("heading").first()).toBeVisible();

    const found = await page.evaluate(() => {
      function accessibleName(el: Element): string {
        const aria = el.getAttribute("aria-label");
        if (aria?.trim()) return aria;

        const labelledBy = el.getAttribute("aria-labelledby");
        if (labelledBy) return document.getElementById(labelledBy)?.textContent ?? "";

        if (el.id) {
          const explicit = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (explicit?.textContent?.trim()) return explicit.textContent;
        }
        // Eticheta implicită: câmpul stă înăuntrul unui `<label>`.
        const wrapping = el.closest("label");
        if (wrapping?.textContent?.trim()) return wrapping.textContent;

        const title = el.getAttribute("title");
        if (title?.trim()) return title;

        return (el.textContent ?? "").trim();
      }

      const problems: string[] = [];
      for (const el of document.querySelectorAll("button, a[href]")) {
        if (!accessibleName(el).trim()) {
          problems.push(`<${el.tagName.toLowerCase()}> ${el.outerHTML.slice(0, 70)}`);
        }
      }
      for (const el of document.querySelectorAll("input, select, textarea")) {
        if ((el as HTMLInputElement).type === "hidden") continue;
        if (!accessibleName(el).trim()) problems.push(el.outerHTML.slice(0, 80));
      }
      return problems;
    });

    for (const item of found) anonymous.push(`${path}: ${item}`);
  }

  expect(anonymous, "elemente fără nume accesibil").toEqual([]);
});

test("nicio pagină nu se rupe pe desktop, tabletă sau telefon", async ({ page }) => {
  await loginAs(page, ACCOUNTS.admin);
  const broken: string[] = [];

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const path of SCREENS) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");

      const measured = await page.evaluate(() => {
        const root = document.documentElement;
        const title = document.querySelector("header h1");
        return {
          overflow: root.scrollWidth - root.clientWidth,
          titleWidth: title ? Math.round(title.getBoundingClientRect().width) : -1,
        };
      });

      // Câțiva pixeli sunt rotunjiri de subpixel, nu o pagină ruptă.
      if (measured.overflow > 2) {
        broken.push(`${viewport.label} ${path}: depășește pe orizontală cu ${measured.overflow}px`);
      }
      // Un titlu de lățime zero înseamnă că a fost strivit până la dispariție.
      if (measured.titleWidth === 0) {
        broken.push(`${viewport.label} ${path}: titlul paginii a fost strivit la zero`);
      }
    }
  }

  expect(broken, "ecrane rupte").toEqual([]);
});
