/**
 * Încărcarea pe backend-ul simulat.
 *
 * Ce se verifică aici este **forma** drumului, nu regulile de fișier: tipul îl
 * stabilește serverul adevărat din primii octeți, iar aici nu există octeți.
 * Contează ca un document urcat să apară exact ca oricare altul — în listă, în
 * contoare, cu propria stare — pentru că restul aplicației nu are voie să știe
 * de unde a venit.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/types";
import { getDocument, listDocuments, mockLogin, uploadDocument } from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** VIEWER citește documente, dar nu are `documents:write`. */
const OPERATOR = "operator@contacrm.test";

const PDF = { filename: "factura.pdf", size: 120_000, mimeType: "application/pdf" };

beforeEach(() => {
  mockLogin(ADMIN);
  vi.useRealTimers();
});

describe("acces", () => {
  /**
   * Refuzul pentru cine **nu** are `documents:write` se verifică în backend
   * (`tests/test_documents_api.py`), nu aici: singurul rol fără permisiune
   * este VIEWER, iar contul lui din setul sintetic este dezactivat intenționat,
   * ca fluxul „cont dezactivat" să fie testabil. Un test care s-ar sprijini pe
   * el ar trece pentru motivul greșit — login-ul cade înainte de încărcare.
   */
  it.each([OPERATOR, "verificator@contacrm.test", "contabil@contacrm.test"])(
    "%s poate încărca",
    (email) => {
      mockLogin(email);
      expect(uploadDocument(PDF).id).toBeTruthy();
    },
  );
});

describe("documentul rezultat", () => {
  it("pornește în `RECEIVED`, fără niciun câmp completat", () => {
    const document = uploadDocument(PDF);

    expect(document.status).toBe("RECEIVED");
    expect(document.confidence).toBeNull();
    // Nu „AI cu valoare nulă": un câmp necitit are proveniența `EMPTY`, iar
    // ecranul de verificare arată diferența.
    for (const field of Object.values(document.fields)) {
      expect(field.source).toBe("EMPTY");
      expect(field.value).toBeNull();
    }
  });

  it("păstrează numele venit de la utilizator ca nume original", () => {
    const document = uploadDocument({ ...PDF, filename: "Factură 2026.pdf" });

    expect(document.originalFilename).toBe("Factură 2026.pdf");
    // Numele de arhivă se compune abia la aprobare, după regula din §10.
    expect(document.storedFilename).toBeNull();
  });

  it("apare imediat în listă, ca sursă `UPLOAD`", () => {
    const document = uploadDocument(PDF);
    const listed = listDocuments({ pageSize: 50 }).items.find((item) => item.id === document.id);

    expect(listed).toBeDefined();
    expect(listed?.source).toBe("UPLOAD");
  });

  it("nu este atribuit niciunui client: identificarea vine din procesare", () => {
    expect(uploadDocument(PDF).clientId).toBeNull();
  });
});

describe("ce refuză", () => {
  it("un fișier gol", () => {
    expect(() => uploadDocument({ ...PDF, size: 0 })).toThrow(ApiError);
  });

  it("un fișier peste limită", () => {
    expect(() => uploadDocument({ ...PDF, size: 30 * 1024 * 1024 })).toThrow(ApiError);
  });

  it("un tip neacceptat", () => {
    expect(() =>
      uploadDocument({ ...PDF, filename: "raport.docx", mimeType: "application/msword" }),
    ).toThrow(ApiError);
  });

  it("spune de ce, nu doar că nu se poate", () => {
    // Un „a eșuat" fără motiv îl lasă pe operator să reîncerce la nesfârșit.
    try {
      uploadDocument({ ...PDF, size: 30 * 1024 * 1024 });
      expect.unreachable("încărcarea ar fi trebuit să fie refuzată");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).message).toMatch(/MB/);
    }
  });
});

describe("procesarea simulată", () => {
  it("rămâne `RECEIVED` imediat după încărcare", () => {
    const document = uploadDocument(PDF);
    expect(getDocument(document.id).status).toBe("RECEIVED");
  });

  it("trece la verificare după ce a trecut destul timp", () => {
    const document = uploadDocument(PDF);

    // Nu așteptăm cu adevărat: promovarea se face la citire, comparând ceasul,
    // deci mutarea ceasului este suficientă. Un cronometru real ar fi făcut
    // testul lent și dependent de mașină.
    vi.useFakeTimers();
    vi.setSystemTime(Date.now() + 10_000);

    const after = getDocument(document.id);
    expect(after.status).toBe("REVIEW_REQUIRED");
    expect(after.reviewRequired).toBe(true);
    expect(after.confidence).not.toBeNull();
  });

  it("ajunge sub pragul automat, deci chiar cere un om", () => {
    const document = uploadDocument(PDF);
    vi.useFakeTimers();
    vi.setSystemTime(Date.now() + 10_000);

    const after = getDocument(document.id);
    expect(after.confidence!).toBeLessThan(0.9);
    expect(after.validationIssues.length).toBeGreaterThan(0);
  });
});
