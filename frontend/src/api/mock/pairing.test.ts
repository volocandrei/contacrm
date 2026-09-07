/**
 * Perechea XML ↔ PDF, în backendul simulat (§14, §16, §17).
 *
 * Regulile adevărate stau pe server și au testele lor. Aici se apără **ce vede
 * omul**: se propune doar între exemplare de feluri diferite, cu motive scrise,
 * conflictul de sume se arată și nu se leagă, iar legătura este reciprocă și
 * reversibilă.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import * as store from "@/api/mock/store";

let pdf: ReturnType<typeof store.uploadDocument>;
let xml: ReturnType<typeof store.uploadDocument>;

beforeEach(() => {
  store.mockLogin("admin@contacrm.test");

  pdf = store.uploadDocument({ filename: "factura.pdf", size: 40_000, mimeType: "application/pdf" });
  xml = store.uploadDocument({ filename: "factura.xml", size: 8_000, mimeType: "application/xml" });

  // Aceeași identitate: același număr, aceeași sumă.
  for (const doc of [pdf, xml]) {
    doc.documentNumber = "7001";
    doc.totalAmount = "1190.00";
    doc.fields.series = { value: "FCT", source: "AI", confidence: 0.9 };
  }
});

describe("propunerea", () => {
  it("găsește celălalt exemplar și spune de ce", () => {
    const result = store.documentPairing(xml.id);

    expect(result.state).toBe("MATCHED");
    expect(result.candidates[0]?.documentId).toBe(pdf.id);
    expect(result.candidates[0]?.reasons).toContain("același număr de factură");
    expect(result.candidates[0]?.reasons).toContain("aceeași sumă");
  });

  it("nu propune două exemplare de același fel", () => {
    // Două PDF-uri cu aceeași identitate sunt un duplicat, nu o pereche.
    const second = store.uploadDocument({
      filename: "factura-copie.pdf",
      size: 40_000,
      mimeType: "application/pdf",
    });
    second.documentNumber = "7001";
    second.totalAmount = "1190.00";

    const found = store.documentPairing(pdf.id).candidates.map((item) => item.documentId);
    expect(found).not.toContain(second.id);
  });

  it("nu propune nimic pentru un număr care nu se repetă", () => {
    xml.documentNumber = "9999";

    expect(store.documentPairing(xml.id).state).toBe("MISSING");
  });
});

describe("conflictul", () => {
  it("aceeași factură cu sume diferite se arată, nu se leagă", () => {
    // Cazul cel mai important: una dintre valori este citită greșit.
    pdf.totalAmount = "1900.00";

    const result = store.documentPairing(xml.id);

    expect(result.state).toBe("CONFLICT");
    expect(result.pairedWithId).toBeNull();
    expect(result.candidates[0]?.reasons.some((r) => r.includes("sume diferite"))).toBe(true);
  });
});

describe("legarea", () => {
  it("este reciprocă", () => {
    store.pairDocument(xml.id, pdf.id);

    expect(store.getDocument(xml.id).pairedWithId).toBe(pdf.id);
    expect(store.getDocument(pdf.id).pairedWithId).toBe(xml.id);
  });

  it("refuză două exemplare de același fel", () => {
    const second = store.uploadDocument({
      filename: "alta.pdf",
      size: 40_000,
      mimeType: "application/pdf",
    });

    expect(() => store.pairDocument(pdf.id, second.id)).toThrow(ApiError);
  });

  it("se poate rupe", () => {
    store.pairDocument(xml.id, pdf.id);

    const result = store.unpairDocument(xml.id);

    expect(result.pairedWithId).toBeNull();
    expect(store.getDocument(pdf.id).pairedWithId).toBeNull();
  });

  it("niciun document nu se aruncă", () => {
    // Nu este o detecție de duplicate: amândouă rămân.
    store.pairDocument(xml.id, pdf.id);

    expect(store.getDocument(pdf.id).id).toBe(pdf.id);
    expect(store.getDocument(xml.id).id).toBe(xml.id);
  });
});
