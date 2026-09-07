/**
 * Pe unde intră documentele — pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_document_sources.py`. Ecranul ăsta este primul
 * pe care îl deschide cineva care evaluează aplicația, iar el promite ceva
 * verificabil. O demonstrație care arată „e-Factura: merge" acolo unde
 * instalarea reală ar spune „lipsește împuternicirea" nu vinde produsul, ci
 * pregătește o discuție neplăcută peste două luni.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { getDocumentSources, mockLogin } from "@/api/mock/store";
import type { DocumentSourceRow } from "@/types/domain";

const ADMIN = "admin@contacrm.test";
/** Contabilul nu vede configurarea: enumeră ce lipsește din variabilele de mediu. */
const ACCOUNTANT = "contabil@contacrm.test";

function byCode(): Map<string, DocumentSourceRow> {
  return new Map(getDocumentSources().sources.map((row) => [row.code, row]));
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("drumurile care merg", () => {
  it("încărcarea și linkul de trimitere merg din prima zi", () => {
    // Sunt singurele care nu cer nici credențiale, nici o hotărâre. Arătate ca
    // „de configurat", cabinetul nou ar crede că nu poate primi nimic.
    const rows = byCode();

    expect(rows.get("UPLOAD")!.state).toBe("LIVE");
    expect(rows.get("PORTAL")!.state).toBe("LIVE");
    expect(rows.get("UPLOAD")!.requirement).toBeNull();
  });

  it("numără documentele care chiar au intrat pe fiecare drum", () => {
    // O integrare conectată care n-a adus nimic arată ca una care merge.
    const rows = byCode();
    const counted = [...rows.values()]
      .filter((row) => row.documents !== null)
      .reduce((total, row) => total + row.documents!, 0);

    expect(counted).toBeGreaterThan(0);
  });

  it("numărul din capul ecranului se potrivește cu rândurile", () => {
    const data = getDocumentSources();

    expect(data.live).toBe(data.sources.filter((row) => row.state === "LIVE").length);
  });
});

describe("ce nu promite", () => {
  it("ce nu există spune asta, și nu numără nimic", () => {
    // Un zero ar arăta ca o integrare stricată, nu ca una inexistentă.
    const rows = byCode();

    for (const code of ["EMAIL_IMAP", "WHATSAPP", "GOOGLE_DRIVE"]) {
      const row = rows.get(code)!;
      expect(row.state, code).toBe("PLANNED");
      expect(row.documents, code).toBeNull();
      expect(row.requirement, code).toBeTruthy();
      // Fără drum: un buton care duce nicăieri e mai rău decât niciunul.
      expect(row.path, code).toBeNull();
    }
  });

  it("WhatsApp nu se preface că primește documente", () => {
    // Butoanele de WhatsApp există peste tot în aplicație, deci cineva ar putea
    // presupune că și intrarea documentelor merge pe acolo.
    expect(byCode().get("WHATSAPP")!.requirement).toContain("Meta");
  });

  it("Saga este ieșire, nu intrare", () => {
    const data = getDocumentSources();

    expect(data.exports.map((row) => row.code)).toContain("SAGA");
    expect(data.sources.map((row) => row.code)).not.toContain("SAGA");
    expect(data.exports.find((row) => row.code === "SAGA")!.state).toBe("PLANNED");
  });

  it("orice drum care nu merge spune ce anume lipsește", () => {
    // „Neconfigurat" fără motiv este o ghicitoare pe care omul o pierde.
    for (const row of getDocumentSources().sources) {
      if (row.state !== "LIVE") expect(row.requirement, row.code).toBeTruthy();
      else expect(row.requirement, row.code).toBeNull();
    }
  });
});

describe("cine poate vedea", () => {
  it("este ecranul administratorului", () => {
    mockLogin(ACCOUNTANT);

    expect(() => getDocumentSources()).toThrow();
  });
});
