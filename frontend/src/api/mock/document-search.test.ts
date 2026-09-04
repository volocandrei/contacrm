/**
 * Căutarea în documente, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_documents_api.py::TestSearchingInsideDocuments`.
 *
 * Ce s-a schimbat: căutarea se uita doar la ce este *despre* document — numele
 * fișierului, furnizorul, numărul, clientul. Textul citit **de pe** document nu
 * era căutabil, deși este exact ce caută un contabil.
 */
import { describe, expect, it } from "vitest";
import { getDocument, listDocuments, mockLogin } from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";

describe("căutarea în documente", () => {
  it("găsește după numele fișierului, ca înainte", () => {
    mockLogin(ADMIN);
    const first = listDocuments({ pageSize: 1 }).items[0];
    expect(first).toBeDefined();

    const word = first!.originalFilename.split(/[\s._-]+/).find((part) => part.length > 3);
    expect(word).toBeDefined();
    const found = listDocuments({ q: word!, pageSize: 200 });

    expect(found.items.length).toBeGreaterThan(0);
  });

  it("un termen care nu apare nicăieri nu întoarce nimic", () => {
    mockLogin(ADMIN);
    // Căutarea trebuie să și refuze, altfel nu este căutare.
    expect(listDocuments({ q: "elicopterportocaliu", pageSize: 200 }).total).toBe(0);
  });

  it("diacriticele nu trebuie să se potrivească", () => {
    mockLogin(ADMIN);
    const withDiacritics = listDocuments({ pageSize: 200 }).items.find((d) =>
      /[ăâîșț]/i.test(d.supplierName ?? ""),
    );
    if (!withDiacritics) return;

    const plain = withDiacritics
      .supplierName!.normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[șş]/gi, "s")
      .replace(/[țţ]/gi, "t");

    expect(listDocuments({ q: plain, pageSize: 200 }).total).toBeGreaterThan(0);
  });

  it("găsește un document după un cuvânt din textul lui", () => {
    mockLogin(ADMIN);
    // Diferența adusă aici: până acum se căuta doar în ce este *despre*
    // document, nu în ce scrie în el.
    const withText = listDocuments({ pageSize: 200 }).items
      .map((item) => getDocument(item.id))
      .find((doc) => (doc.ocr.textPreview ?? "").length > 20);
    expect(withText).toBeDefined();

    const word = withText!.ocr
      .textPreview!.split(/[^\p{L}\p{N}]+/u)
      .find((part) => part.length > 5);
    expect(word).toBeDefined();

    const found = listDocuments({ q: word!, pageSize: 200 });
    expect(found.items.some((item) => item.id === withText!.id)).toBe(true);
  });

  it("căutarea nu scoate textul documentului în listă", () => {
    mockLogin(ADMIN);
    // Se caută în text, dar textul nu iese în listă (§64).
    const item = listDocuments({ pageSize: 1 }).items[0]!;
    expect(item).not.toHaveProperty("ocr");
    expect(item).not.toHaveProperty("ocrText");
  });
});
