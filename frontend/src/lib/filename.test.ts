/**
 * Testele pentru §10, §11 și R7. Aceleași cazuri trebuie să treacă și în backend,
 * în `FilenameGeneratorService` / `StoragePathService` — fișierul acesta este
 * specificația executabilă a regulii.
 */
import { describe, expect, it } from "vitest";
import {
  buildArchivePath,
  buildDocumentFilename,
  normalizeExtension,
  sanitizeSegment,
  type FilenameInput,
} from "@/lib/filename";

/** Scris ca `fromCharCode` ca să nu depindă de escaping-ul editorului. */
const BACKSLASH = String.fromCharCode(92);

describe("sanitizeSegment", () => {
  it("elimină diacriticele românești", () => {
    expect(sanitizeSegment("Șerbănescu Țară SRL")).toBe("SerbanescuTaraSRL");
    expect(sanitizeSegment("ăâîșț ĂÂÎȘȚ")).toBe("aaistAAIST");
  });

  it("elimină separatorii de cale, în ambele forme", () => {
    expect(sanitizeSegment("a/b")).toBe("ab");
    expect(sanitizeSegment(`a${BACKSLASH}b`)).toBe("ab");
    expect(sanitizeSegment(`..${BACKSLASH}..${BACKSLASH}etc`)).toBe("etc");
    expect(sanitizeSegment("../../etc")).toBe("etc");
  });

  it("elimină caracterele interzise pe Windows și cele de control", () => {
    expect(sanitizeSegment('a<b>c:d"e|f?g*h')).toBe("abcdefgh");
    expect(sanitizeSegment(`a${String.fromCharCode(0)}b${String.fromCharCode(31)}c`)).toBe("abc");
  });

  it("păstrează cratima și underscore-ul, care apar în serii reale", () => {
    expect(sanitizeSegment("FCT-2026_A")).toBe("FCT-2026_A");
  });

  it("nu produce nume rezervate pe Windows", () => {
    expect(sanitizeSegment("CON")).toBe("_CON");
    expect(sanitizeSegment("nul")).toBe("_nul");
    expect(sanitizeSegment("LPT1")).toBe("_LPT1");
  });

  it("nu întoarce niciodată segment gol", () => {
    expect(sanitizeSegment("")).toBe("_");
    expect(sanitizeSegment("///")).toBe("_");
  });

  it("nu lasă punct sau spațiu la capete", () => {
    expect(sanitizeSegment("  .nume.  ")).toBe("nume");
  });

  it("respectă limita de lungime", () => {
    expect(sanitizeSegment("x".repeat(200))).toHaveLength(60);
    expect(sanitizeSegment("x".repeat(200), 10)).toHaveLength(10);
  });
});

describe("normalizeExtension", () => {
  it("preferă tipul MIME în locul extensiei trimise de expeditor", () => {
    expect(normalizeExtension("factura.exe", "application/pdf")).toBe("pdf");
    expect(normalizeExtension("poza.pdf", "image/jpeg")).toBe("jpg");
  });

  it("acceptă doar extensii din lista permisă", () => {
    expect(normalizeExtension("factura.PDF")).toBe("pdf");
    expect(normalizeExtension("script.exe")).toBe("pdf");
    expect(normalizeExtension("fara-extensie")).toBe("pdf");
  });
});

describe("buildDocumentFilename", () => {
  const base: FilenameInput = {
    documentDate: "2026-08-14",
    documentTypeLabel: "Factură",
    clientName: "Alfa Prod SRL",
    series: "FCT",
    documentNumber: "1024",
    originalFilename: "scan.PDF",
  };

  it("respectă convenția YYYY-MM-DD_Tip_Client_SerieNumar.ext", () => {
    expect(buildDocumentFilename(base)).toBe("2026-08-14_Factura_AlfaProdSRL_FCT1024.pdf");
  });

  it("omite ultimul segment când documentul nu are serie și număr", () => {
    expect(buildDocumentFilename({ ...base, series: null, documentNumber: null })).toBe(
      "2026-08-14_Factura_AlfaProdSRL.pdf",
    );
  });

  it("marchează lipsa datei în loc să o inventeze", () => {
    expect(buildDocumentFilename({ ...base, documentDate: null })).toMatch(/^fara-data_/);
    expect(buildDocumentFilename({ ...base, documentDate: "2026-02-30" })).toMatch(/^fara-data_/);
  });

  it("adaugă sufixul anti-coliziune", () => {
    expect(buildDocumentFilename({ ...base, collisionSuffix: 2 })).toBe(
      "2026-08-14_Factura_AlfaProdSRL_FCT1024_2.pdf",
    );
  });

  it("nu lasă niciun separator de cale să treacă din numele clientului", () => {
    const hostile = buildDocumentFilename({
      ...base,
      clientName: `..${BACKSLASH}..${BACKSLASH}windows${BACKSLASH}system32`,
    });
    expect(hostile).not.toContain("/");
    expect(hostile).not.toContain(BACKSLASH);
  });
});

describe("buildArchivePath", () => {
  it("construiește /ARHIVA/{an}/{luna}/{client}/", () => {
    expect(buildArchivePath("2026-08", "Alfa Prod SRL")).toBe("/ARHIVA/2026/08/AlfaProdSRL/");
  });

  it("nu poate ieși din rădăcină prin numele clientului", () => {
    const path = buildArchivePath("2026-08", `..${BACKSLASH}..${BACKSLASH}Beta`);
    expect(path).toBe("/ARHIVA/2026/08/Beta/");
    expect(path).not.toContain(BACKSLASH);
    expect(path.split("/").filter(Boolean)).toHaveLength(4);
  });

  it("nu poate ieși din rădăcină prin perioada de referință", () => {
    expect(buildArchivePath("../../etc", "Alfa")).toBe("/ARHIVA/fara-perioada/00/Alfa/");
    expect(buildArchivePath("2026-13", "Alfa")).toBe("/ARHIVA/2026/00/Alfa/");
  });

  it("marchează explicit documentele fără perioadă sau fără client", () => {
    expect(buildArchivePath(null, null)).toBe("/ARHIVA/fara-perioada/00/ClientNeidentificat/");
  });
});
