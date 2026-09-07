/**
 * Desfacerea unui teanc, în backendul simulat (§8, §14).
 *
 * Regulile adevărate de detectare stau pe server și au testele lor
 * (`backend/tests/test_pdf_split.py`). Aici se apără **ce vede omul**: că
 * originalul rămâne, că fiecare bucată arată înapoi spre el, că nimic nu se taie
 * de două ori, și că propunerea vine cu motive — fără ele, tăietura nu se poate
 * verifica, deci nu se poate accepta.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import * as store from "@/api/mock/store";

let stack: ReturnType<typeof store.uploadDocument>;

beforeEach(() => {
  store.mockLogin("admin@contacrm.test");
  stack = store.uploadDocument({
    filename: "scan_001.pdf",
    size: 90_000,
    mimeType: "application/pdf",
  });
});

describe("previzualizarea", () => {
  it("găsește documentele și spune de ce se taie", () => {
    const plan = store.splitPreview(stack.id);

    expect(plan.splittable).toBe(true);
    expect(plan.segments).toHaveLength(3);
    // Primul segment nu este o tăietură: este începutul fișierului.
    expect(plan.segments[0]?.reasons).toEqual([]);
    expect(plan.segments[1]?.reasons.length).toBeGreaterThan(0);
  });

  it("nu propune nimic pentru un document obișnuit", () => {
    const single = store.uploadDocument({
      filename: "factura.pdf",
      size: 30_000,
      mimeType: "application/pdf",
    });

    expect(store.splitPreview(single.id).splittable).toBe(false);
  });

  it("nu scrie nimic", () => {
    store.splitPreview(stack.id);

    expect(store.getDocument(stack.id).status).not.toBe("SPLIT");
  });
});

describe("desfacerea", () => {
  it("produce documente noi, fiecare cu proveniența lui", () => {
    const created = store.splitDocument(stack.id);

    expect(created).toHaveLength(3);
    for (const item of created) {
      const piece = store.getDocument(item.id);
      expect(piece.splitFromId).toBe(stack.id);
      expect(piece.pageFrom).toBeGreaterThan(0);
    }
  });

  it("lasă originalul în bază, marcat", () => {
    // Un document contabil nu dispare pentru că am înțeles noi ceva despre el.
    store.splitDocument(stack.id);

    const original = store.getDocument(stack.id);
    expect(original.status).toBe("SPLIT");
    // Si este in continuare acolo: se poate citi, deci nu a fost sters.
    expect(store.getDocument(stack.id).id).toBe(stack.id);
  });

  it("nu se poate desface de două ori", () => {
    store.splitDocument(stack.id);

    expect(() => store.splitDocument(stack.id)).toThrow(ApiError);
  });

  it("un document obișnuit nu se poate desface", () => {
    const single = store.uploadDocument({
      filename: "factura.pdf",
      size: 30_000,
      mimeType: "application/pdf",
    });

    expect(() => store.splitDocument(single.id)).toThrow(ApiError);
  });
});
