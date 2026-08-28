/**
 * Reguli de aprobare și arhivare (§17, R7, R10) verificate pe backend-ul simulat.
 * Store-ul ține stare mutabilă la nivel de modul; vitest izolează modulele per
 * fișier de test, deci ordinea contează doar în interiorul acestui fișier.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import {
  approveDocument,
  assignClient,
  listClients,
  listDocuments,
  mockLogin,
  updateDocumentFields,
  validateForApproval,
  getDocument,
} from "@/api/mock/store";
import { buildArchivePath } from "@/lib/filename";

const ADMIN = "admin@contacrm.test";
/** OPERATOR are `documents:write`, dar nu `documents:approve`. */
const OPERATOR = "operator@contacrm.test";
/** Singurul VIEWER din setul sintetic are contul dezactivat. */
const DISABLED = "vizitator@contacrm.test";

/** Documente care încă așteaptă verificare — punctul de plecare al fluxului. */
function pendingDocumentIds(count: number): string[] {
  const ids = listDocuments({ status: "REVIEW_REQUIRED", pageSize: 200 })
    .items.filter((doc) => doc.clientId !== null)
    .map((doc) => doc.id);
  expect(ids.length).toBeGreaterThanOrEqual(count);
  return ids.slice(0, count);
}

/**
 * Două documente în așteptare cu același tip MIME. Extensia face parte din nume,
 * deci fără această condiție documentele nu s-ar ciocni.
 */
function pendingPairWithSameExtension(): [string, string] {
  const pending = listDocuments({ status: "REVIEW_REQUIRED", pageSize: 200 }).items.filter(
    (doc) => doc.clientId !== null,
  );
  for (const first of pending) {
    const match = pending.find(
      (other) =>
        other.id !== first.id &&
        getDocument(other.id).mimeType === getDocument(first.id).mimeType,
    );
    if (match) return [first.id, match.id];
  }
  throw new Error("Setul sintetic nu conține două documente în așteptare cu aceeași extensie.");
}

/** Aduce documentul într-o stare în care poate fi aprobat, cu valori cunoscute. */
function prepare(id: string, documentNumber: string) {
  updateDocumentFields(id, [
    { field: "documentType", value: "FACTURA_INTRARE" },
    { field: "documentDate", value: "2026-08-14" },
    { field: "referenceMonth", value: "2026-08" },
    { field: "series", value: "FCT" },
    { field: "documentNumber", value: documentNumber },
    { field: "supplierName", value: "Furnizor Test SRL" },
    { field: "totalAmount", value: "1190.00" },
  ]);
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("validateForApproval", () => {
  it("blochează aprobarea unui document fără client", () => {
    const [id] = pendingDocumentIds(1);
    prepare(id!, "5001");
    const doc = getDocument(id!);
    const orphan = { ...doc, clientId: null };
    expect(validateForApproval(orphan)).toContain("Documentul nu are client atribuit.");
  });

  it("cere câmpurile obligatorii ale tipului de document", () => {
    const [id] = pendingDocumentIds(1);
    prepare(id!, "5002");
    updateDocumentFields(id!, [{ field: "totalAmount", value: null }]);
    const errors = validateForApproval(getDocument(id!));
    expect(errors.some((error) => error.includes("totalAmount"))).toBe(true);
  });

  it("refuză aprobarea și nu schimbă statusul când validarea eșuează", () => {
    const [id] = pendingDocumentIds(1);
    prepare(id!, "5003");
    updateDocumentFields(id!, [{ field: "documentDate", value: null }]);

    expect(() => approveDocument(id!)).toThrow(ApiError);
    expect(getDocument(id!).status).toBe("REVIEW_REQUIRED");
  });
});

describe("approveDocument", () => {
  it("arhivează cu nume standardizat și cale derivată din aceleași reguli", () => {
    const [id] = pendingDocumentIds(1);
    prepare(id!, "7001");
    const approved = approveDocument(id!);

    expect(approved.status).toBe("ARCHIVED");
    expect(approved.reviewRequired).toBe(false);
    expect(approved.storedFilename).toBe(
      `2026-08-14_Facturaintrare_${approved.clientName!.replace(/\s+/g, "")}_FCT7001.pdf`,
    );
    expect(approved.storagePath).toBe(buildArchivePath("2026-08", approved.clientName));
  });

  it("adaugă sufix anti-coliziune când numele există deja în același director", () => {
    const [first, second] = pendingPairWithSameExtension();

    prepare(first, "7002");
    const one = approveDocument(first);

    // Al doilea document ajunge la același client, cu aceleași date → același nume.
    assignClient(second, one.clientId!);
    prepare(second, "7002");
    const two = approveDocument(second);

    expect(two.storagePath).toBe(one.storagePath);
    expect(two.storedFilename).not.toBe(one.storedFilename);
    expect(two.storedFilename).toBe(one.storedFilename!.replace(/(\.[^.]+)$/, "_2$1"));
  });

  it("nu lasă separatori de cale să treacă din numele clientului în arhivă", () => {
    const [id] = pendingDocumentIds(1);
    prepare(id!, "7003");
    const approved = approveDocument(id!);

    expect(approved.storedFilename).not.toMatch(/[/\\]/);
    expect(approved.storagePath!.split("/").filter(Boolean)).toHaveLength(4);
  });

  it("scrie aprobarea în istoricul documentului", () => {
    const [id] = pendingDocumentIds(1);
    prepare(id!, "7004");
    const approved = approveDocument(id!);

    expect(approved.history.at(-1)).toMatchObject({ action: "DOCUMENT_APPROVED" });
    expect(approved.history.at(-1)!.detail).toContain(approved.storedFilename!);
  });
});

describe("autorizare (R10)", () => {
  it("un OPERATOR nu poate aproba documente", () => {
    const [id] = pendingDocumentIds(1);
    prepare(id!, "9001");

    mockLogin(OPERATOR);
    expect(() => approveDocument(id!)).toThrow(ApiError);
    expect(getDocument(id!).status).toBe("REVIEW_REQUIRED");
  });

  it("un OPERATOR poate în schimb corecta câmpuri", () => {
    const [id] = pendingDocumentIds(1);
    mockLogin(OPERATOR);
    const updated = updateDocumentFields(id!, [{ field: "series", value: "OP" }]);
    expect(updated.fields.series).toMatchObject({ value: "OP", source: "MANUAL" });
  });

  it("un cont dezactivat nu se poate autentifica", () => {
    expect(() => mockLogin(DISABLED)).toThrow(ApiError);
  });

  it("clienții rămân vizibili pentru un OPERATOR", () => {
    mockLogin(OPERATOR);
    expect(listClients({}).items.length).toBeGreaterThan(0);
  });
});
