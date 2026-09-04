/**
 * Textul solicitării.
 *
 * Ce se apără: mesajul spune **cât** mai lipsește, nu doar **ce**. Un client
 * care crede că a trimis facturile nu află nimic din „Facturi de achiziție";
 * află din „mai așteptăm 2 (am primit 3 din 5)".
 */
import { describe, expect, it } from "vitest";
import { buildRequestMessage } from "@/lib/request-message";
import type { ChecklistItem } from "@/types/domain";

function item(overrides: Partial<ChecklistItem> = {}): ChecklistItem {
  return {
    documentType: "PURCHASE_INVOICE",
    documentTypeLabel: "Factură de achiziție",
    expectedMinCount: 5,
    receivedCount: 3,
    isSatisfied: false,
    ...overrides,
  };
}

const BASE = {
  clientName: "Alfa Conta SRL",
  referenceMonth: "2026-08",
  deadline: "2026-09-25",
  organizationName: "Cabinet Contabil Demo SRL",
};

describe("solicitarea de documente", () => {
  it("spune cât mai lipsește, nu doar ce", () => {
    const text = buildRequestMessage({ ...BASE, missing: [item()] });

    expect(text).toContain("mai așteptăm 2 (am primit 3 din 5)");
  });

  it("un tip din care nu a sosit nimic se cere în întregime", () => {
    const text = buildRequestMessage({
      ...BASE,
      missing: [item({ documentTypeLabel: "Extras de cont", expectedMinCount: 1, receivedCount: 0 })],
    });

    expect(text).toContain("Extras de cont — 1 bucată");
    expect(text).not.toContain("am primit");
  });

  it("luna se scrie în cuvinte, iar termenul ca dată", () => {
    const text = buildRequestMessage({ ...BASE, missing: [item()] });

    expect(text).toContain("august 2026");
    expect(text).toContain("25.09.2026");
  });

  it("semnătura este a cabinetului, nu a aplicației", () => {
    const text = buildRequestMessage({ ...BASE, missing: [item()] });

    expect(text.trimEnd().endsWith("Cabinet Contabil Demo SRL")).toBe(true);
    expect(text).not.toContain("ContaCRM");
  });
});
