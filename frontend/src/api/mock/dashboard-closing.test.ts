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
import { getDashboard, mockLogin } from "@/api/mock/store";

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
