/**
 * Invarianți ai datelor.
 *
 * Cele două teste de mai jos există pentru că exact aceste stări au apărut pe ecran:
 * documente marcate „Client neidentificat" care aveau client, și o perioadă
 * „Documente complete" al cărei checklist avea itemi nesatisfăcuți.
 */

import { describe, expect, it } from "vitest";
import {
  approveDocument,
  getDocument,
  listClients,
  listDocuments,
  listPeriods,
  mockLogin,
  updateDocumentFields,
} from "@/api/mock/store";
import { derivePeriodStatus } from "@/api/mock/seed";
import type { ChecklistItem } from "@/types/domain";

const ALL_DOCUMENTS = listDocuments({ pageSize: 200 }).items;
const ALL_PERIODS = listPeriods({});

describe("statusul documentului", () => {
  it("UNMATCHED înseamnă exact «fără client», niciodată altceva", () => {
    const contradictory = ALL_DOCUMENTS.filter((d) => d.status === "UNMATCHED" && d.clientId !== null);
    expect(contradictory.map((d) => `${d.originalFilename} → ${d.clientName}`)).toEqual([]);
  });

  it("orice document fără client este UNMATCHED", () => {
    const orphansWithOtherStatus = ALL_DOCUMENTS.filter(
      (d) => d.clientId === null && d.status !== "UNMATCHED",
    );
    expect(orphansWithOtherStatus.map((d) => `${d.originalFilename} → ${d.status}`)).toEqual([]);
  });

  it("documentele UNMATCHED chiar există în set — altfel testul de mai sus e vacuu", () => {
    expect(ALL_DOCUMENTS.some((d) => d.status === "UNMATCHED")).toBe(true);
  });
});

describe("statusul perioadei", () => {
  it("COMPLETE cere fiecare item din checklist satisfăcut", () => {
    const lying = ALL_PERIODS.filter(
      (p) => p.status === "COMPLETE" && p.checklist.some((item) => !item.isSatisfied),
    );
    expect(lying.map((p) => `${p.clientName} ${p.referenceMonth}`)).toEqual([]);
  });

  it("o perioadă cu tot checklist-ul satisfăcut nu rămâne PARTIAL", () => {
    const understated = ALL_PERIODS.filter(
      (p) =>
        p.status === "PARTIAL" &&
        p.checklist.length > 0 &&
        p.checklist.every((item) => item.isSatisfied),
    );
    expect(understated.map((p) => `${p.clientName} ${p.referenceMonth}`)).toEqual([]);
  });

  it("statusul se recalculează după aprobarea unui document, nu rămâne cel inițial", () => {
    mockLogin("admin@contacrm.test");

    const pending = listDocuments({ status: "REVIEW_REQUIRED", pageSize: 200 }).items.find(
      (d) => d.clientId !== null,
    );
    expect(pending).toBeDefined();

    const clientId = getDocument(pending!.id).clientId!;
    const before = listPeriods({ clientId, referenceMonth: "2026-08" })[0];
    expect(before).toBeDefined();

    updateDocumentFields(pending!.id, [
      { field: "documentType", value: "EXTRAS_CONT" },
      { field: "documentDate", value: "2026-08-14" },
      { field: "referenceMonth", value: "2026-08" },
      { field: "supplierName", value: "Banca Demo" },
    ]);
    approveDocument(pending!.id);

    const after = listPeriods({ clientId, referenceMonth: "2026-08" })[0]!;
    expect(after.status).toBe(
      derivePeriodStatus(after.checklist, after.receivedCount, false),
    );
  });
});

describe("coerența referințelor", () => {
  it("fiecare document cu client indică un client care există", () => {
    const ids = new Set(listClients({ pageSize: 200 }).items.map((c) => c.id));
    const dangling = ALL_DOCUMENTS.filter((d) => d.clientId !== null && !ids.has(d.clientId));
    expect(dangling.map((d) => d.originalFilename)).toEqual([]);
  });

  it("contoarele din checklist nu depășesc realitatea documentelor", () => {
    for (const period of ALL_PERIODS) {
      const total = period.checklist.reduce(
        (sum: number, item: ChecklistItem) => sum + item.receivedCount,
        0,
      );
      expect(total).toBeLessThanOrEqual(period.receivedCount);
    }
  });
});
