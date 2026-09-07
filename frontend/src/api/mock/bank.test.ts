/**
 * Regulile de reconciliere pe care le vede omul, în backendul simulat (§14).
 *
 * Backendul simulat este contractul interfeței: dacă el se poartă altfel decât
 * serverul, ecranul se dezvoltă pe o minciună și se sparge la trecerea pe date
 * reale. Ce se verifică aici sunt exact regulile pe care le apără și
 * `backend/tests/test_bank_api.py`:
 *
 * - propunerile vin cu **motive** (fără ele nu se pot verifica);
 * - a cere propuneri **nu leagă nimic**;
 * - nu se poate aloca mai mult decât a rămas din plată sau din factură;
 * - parțial înseamnă „încă în lucru", nu „gata";
 * - totul este reversibil.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import * as bank from "@/api/mock/bank";

beforeEach(() => {
  bank.reset();
});

const PAYMENT = "bank-tx-1";
const PARTIAL = "bank-tx-3";
const FEE = "bank-tx-4";
const INVOICE = "bank-doc-1";

describe("propuneri", () => {
  it("găsește factura numită în plată și spune de ce", () => {
    const found = bank.suggestions(PAYMENT);

    expect(found[0]?.documentId).toBe(INVOICE);
    expect(found[0]?.reasons).toContain("numărul facturii apare în plată");
    expect(found[0]?.reasons).toContain("sumă exactă");
  });

  it("nu leagă nimic doar pentru că a fost întrebată", () => {
    bank.suggestions(PAYMENT);

    const transaction = bank.listTransactions().find((item) => item.id === PAYMENT);
    expect(transaction?.matches).toHaveLength(0);
    expect(transaction?.status).toBe("UNMATCHED");
  });

  it("nu propune o factură emisă pentru o plată", () => {
    // Direcția nu se discută: bani ieșiți nu închid o factură emisă de cabinet.
    const found = bank.suggestions(PAYMENT);

    expect(found.every((item) => item.documentId !== "bank-doc-3")).toBe(true);
  });

  it("tace când nu se potrivește nimic", () => {
    // Comisionul bancar nu are factură, și nu trebuie să i se inventeze una.
    expect(bank.suggestions(FEE)).toEqual([]);
  });
});

describe("legarea", () => {
  it("o plată integrală închide rândul", () => {
    const result = bank.match(PAYMENT, INVOICE, null);

    expect(result.status).toBe("MATCHED");
    expect(result.unallocated).toBe("0.00");
  });

  it("o plată parțială lasă rândul în lucru", () => {
    // `NEEDS_REVIEW` este singura stare care spune adevărul: s-a pus ceva, dar nu
    // tot. Marcat „gata", restul de plată ar fi dispărut din vedere.
    const result = bank.match(PAYMENT, INVOICE, "500.00");

    expect(result.status).toBe("NEEDS_REVIEW");
    expect(result.unallocated).toBe("690.00");
  });

  it("refuză mai mult decât a rămas din plată", () => {
    expect(() => bank.match(PAYMENT, INVOICE, "2000.00")).toThrow(ApiError);
  });

  it("refuză mai mult decât restul facturii", () => {
    // Fără regula asta, o factură ar apărea plătită de două ori, iar restul de
    // plată al furnizorului ar ieși negativ.
    expect(() => bank.match(PARTIAL, "bank-doc-2", "1000.00")).toThrow(ApiError);
  });

  it("a doua alocare pe aceeași factură crește legătura, nu adaugă un rând", () => {
    bank.match(PAYMENT, INVOICE, "500.00");
    const result = bank.match(PAYMENT, INVOICE, "690.00");

    expect(result.matches).toHaveLength(1);
    expect(result.matches[0]?.amount).toBe("1190.00");
    expect(result.status).toBe("MATCHED");
  });
});

describe("desfacerea", () => {
  it("o legătură se poate scoate", () => {
    bank.match(PAYMENT, INVOICE, null);

    const result = bank.unmatch(PAYMENT, INVOICE);

    expect(result.status).toBe("UNMATCHED");
    expect(result.matches).toHaveLength(0);
  });

  it("un comision se marchează lămurit și iese din lista de lucru", () => {
    const result = bank.ignore(FEE, "Comision de administrare");

    expect(result.status).toBe("IGNORED");
    expect(bank.listStatements()[0]?.openCount).toBe(3);
  });

  it("un rând legat nu se poate ascunde ca lămurit", () => {
    bank.match(PAYMENT, INVOICE, null);

    expect(() => bank.ignore(PAYMENT, "x")).toThrow(ApiError);
  });

  it("un rând lămurit din greșeală se readuce", () => {
    bank.ignore(FEE, "greșeală");

    expect(bank.reopen(FEE).status).toBe("UNMATCHED");
  });
});

describe("contorul de pe extras", () => {
  it("numără doar ce mai are nevoie de un om", () => {
    expect(bank.listStatements()[0]?.openCount).toBe(4);

    bank.match(PAYMENT, INVOICE, null);

    expect(bank.listStatements()[0]?.openCount).toBe(3);
  });

  it("o alocare parțială rămâne numărată", () => {
    bank.match(PAYMENT, INVOICE, "500.00");

    expect(bank.listStatements()[0]?.openCount).toBe(4);
  });
});
