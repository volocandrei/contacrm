/**
 * Termenul lunii, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_documents_api.py::TestDashboard`.
 *
 * Regula care se greșește cel mai ușor: termenul este în luna **următoare**.
 * Documentele lui august se depun în septembrie, iar cele ale lui decembrie în
 * ianuarie anul următor — nu în luna 13.
 */
import { describe, expect, it } from "vitest";
import {
  createClient,
  getDashboard,
  listMissingDocuments,
  mockLogin,
  setExpectations,
} from "@/api/mock/store";
import { MOCK_NOW } from "@/api/mock/seed";

const ADMIN = "admin@contacrm.test";

describe("închiderea lunii", () => {
  it("termenul cade în luna de după cea care se închide", () => {
    mockLogin(ADMIN);
    const closing = getDashboard().closing;

    expect(closing).not.toBeNull();
    const [closedYear, closedMonth] = closing!.referenceMonth.split("-").map(Number);
    const [dueYear, dueMonth] = closing!.deadline.split("-").map(Number);

    const closedIndex = closedYear! * 12 + closedMonth!;
    const dueIndex = dueYear! * 12 + dueMonth!;
    expect(dueIndex - closedIndex).toBe(1);
  });

  it("clienții în întârziere sunt ordonați după cât le lipsește", () => {
    mockLogin(ADMIN);
    const { laggards } = getDashboard().closing!;

    // Primul rând trebuie să fie cel care costă cel mai mult dacă rămâne așa.
    const counts = laggards.map((l) => l.missingCount);
    expect([...counts].sort((a, b) => b - a)).toEqual(counts);
  });

  it("fiecare rând spune ce lipsește, nu doar că lipsește ceva", () => {
    mockLogin(ADMIN);
    const { laggards } = getDashboard().closing!;

    for (const laggard of laggards) {
      expect(laggard.missingCount).toBeGreaterThan(0);
      expect(laggard.missing.length).toBeGreaterThan(0);
      // Etichete lizibile, nu coduri.
      expect(laggard.missing.every((label) => label.trim().length > 0)).toBe(true);
    }
  });

  it("numărul de clienți care așteaptă îi acoperă pe cei afișați", () => {
    mockLogin(ADMIN);
    const closing = getDashboard().closing!;

    // Lista e trunchiată pentru panou; contorul nu este.
    expect(closing.clientsWaiting).toBeGreaterThanOrEqual(closing.laggards.length);
  });
});

describe("clientul care n-a trimis nimic", () => {
  it("intră în cifrele panoului, nu doar în raport", () => {
    // `listPeriods` nu inventează o lună fără documente, deci clientul care n-a
    // trimis absolut nimic nu are perioadă — iar panoul îl număra ca pe unul în
    // regulă. Pe serverul real, cu patru clienți activi și un singur document
    // urcat, panoul spunea „1 client cu lipsuri" acolo unde raportul spunea 4.
    // Găsit rulând aplicația, nu citind codul.
    mockLogin("admin@contacrm.test");
    const inainte = getDashboard().kpis.clientsMissingDocs;

    // Un client activ, cu așteptări, care n-a trimis nimic: singurul caz în care
    // cele două numărători se despart. Fără el, testul ar trece din întâmplare —
    // în setul sintetic toți clienții au documente.
    const tacut = createClient({ name: "Tăcut SRL", taxId: "RO9911", status: "ACTIVE" });
    setExpectations(tacut.id, [{ documentTypeCode: "FACTURA_INTRARE", expectedMinCount: 2 }]);

    const raport = listMissingDocuments(MOCK_NOW.slice(0, 7)).length;
    const panou = getDashboard();

    expect(raport).toBe(inainte + 1);
    expect(panou.kpis.clientsMissingDocs).toBe(raport);
    expect(panou.closing?.clientsWaiting).toBe(raport);
    // Și apare pe nume în raport. Nu și în `laggards`: acela este deliberat un
    // top al celor cărora le lipsește cel mai mult, iar un client cu un singur
    // gol se clasează ultimul dintre treisprezece.
    const inRaport = listMissingDocuments(MOCK_NOW.slice(0, 7)).map((e) => e.period.clientName);
    expect(inRaport).toContain("Tăcut SRL");
  });
});
