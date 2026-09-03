/**
 * Unelte comune pentru testele end-to-end.
 *
 * Fișierele urcate se construiesc aici, nu se citesc de pe disc: în repo nu
 * există și nu are voie să existe niciun document contabil (§70). Textul din ele
 * este inventat, dar are **forma** unei facturi românești, ca extracția să aibă
 * ce citi.
 */
import { expect, type Locator, type Page } from "@playwright/test";

export const DEV_PASSWORD = "contacrm-dev";

export const ACCOUNTS = {
  admin: "admin@contacrm.test",
  accountant: "contabil@contacrm.test",
  operator: "operator@contacrm.test",
  reviewer: "verificator@contacrm.test",
  /** Dezactivat intenționat în `seed-dev`, ca fluxul „cont dezactivat" să existe. */
  viewer: "vizitator@contacrm.test",
} as const;

/** Primul client din `seed-dev`, cu CUI-ul lui. Vezi `app/cli.py`. */
export const SEED_CLIENT = { name: "Alfa Conta SRL", taxId: "RO10000101" };

/** Distinge documentele între rulări: baza se reconstruiește, dar un test poate rula de două ori. */
export function unique(): string {
  return Math.random().toString(36).slice(2, 10).toUpperCase();
}

export async function login(page: Page, email: string, password = DEV_PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Parolă").fill(password);
  await page.getByRole("button", { name: "Intră în cont" }).click();
}

export async function loginAs(page: Page, email: string): Promise<void> {
  await login(page, email);
  // Panoul principal este gata când bara laterală există.
  await expect(page.getByRole("navigation", { name: "Navigație principală" })).toBeVisible();
}

/**
 * Urcă un fișier din inbox și deschide documentul creat.
 *
 * Linkul se caută **în lista panoului de încărcare**, nu în pagină: tabelul de
 * dedesubt are și el, pe fiecare rând, un link „Deschide". Prima variantă a
 * testelor lua primul link din pagină și, cât timp încărcarea era încă în zbor,
 * nimerea un document vechi din tabel — apoi cădea cerându-i câmpuri pe care
 * documentul acela nu le avea. Un test care se uită la altceva decât crede este
 * mai rău decât unul care lipsește.
 */
export async function uploadAndOpen(page: Page, filename: string, content: Buffer): Promise<void> {
  await page.goto("/documente/inbox");
  await page.locator('input[type="file"]').setInputFiles({
    name: filename,
    mimeType: filename.endsWith(".pdf") ? "application/pdf" : "application/octet-stream",
    buffer: content,
  });

  const results = page.getByRole("list", { name: /încărcărilor/i });
  const open = results.getByRole("link", { name: "Deschide" });
  await expect(open).toBeVisible();
  await open.click();
}

/**
 * Un câmp din formularul de verificare, după numele lui din contract.
 *
 * Nu `getByLabel`: eticheta conține și insigna de proveniență („citit 95%"),
 * deci numele accesibil al câmpului „Total" este „Total citit 95%" și se
 * schimbă odată cu încrederea. Id-ul este stabil.
 */
export function field(page: Page, name: string): Locator {
  return page.locator(`#field-${name}`);
}

/* ─── Un PDF sintetic, cu strat de text ────────────────────────────────────── */

function escapeText(line: string): string {
  return line.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

/**
 * Cel mai mic PDF valid care poartă text lizibil.
 *
 * Fontul este Helvetica standard, deci codarea este WinAnsi: **fără diacritice**.
 * Nu este o scăpare, ci limita generatorului — reducerea diacriticelor este
 * testată acolo unde chiar trăiește regula, în `test_romanian_documents.py`.
 */
export function makePdf(lines: string[]): Buffer {
  const stream = [
    "BT",
    "/F1 11 Tf",
    "1 0 0 1 40 780 Tm",
    "15 TL",
    ...lines.map((line) => `(${escapeText(line)}) Tj T*`),
    "ET",
  ].join("\n");

  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] " +
      "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    `<< /Length ${Buffer.byteLength(stream, "latin1")} >>\nstream\n${stream}\nendstream`,
  ];

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, index) => {
    offsets.push(Buffer.byteLength(pdf, "latin1"));
    pdf += `${index + 1} 0 obj\n${body}\nendobj\n`;
  });

  const xref = Buffer.byteLength(pdf, "latin1");
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets) {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;

  return Buffer.from(pdf, "latin1");
}

/** O factură în care clientul cabinetului este cumpărătorul — deci una de intrare. */
export function incomingInvoice(options: {
  number: string;
  total: string;
  date?: string;
}): Buffer {
  return makePdf([
    "FACTURA FISCALA",
    "Furnizor: Tert Furnizor SRL",
    "CUI: RO99887766",
    `Cumparator: ${SEED_CLIENT.name}`,
    `CIF: ${SEED_CLIENT.taxId}`,
    `Seria FCT nr. ${options.number}`,
    `Data emiterii: ${options.date ?? "14.08.2026"}`,
    "Data scadentei: 13.09.2026",
    `Total de plata: ${options.total} lei`,
  ]);
}
