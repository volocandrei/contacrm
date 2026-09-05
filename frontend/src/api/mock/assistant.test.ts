/**
 * Asistentul, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_assistant_api.py`.
 *
 * Ce se apără, în ordinea gravității: că nu vede peste rolul celui care
 * întreabă, că nu inventează cifre, și că nu execută nimic — propune drumuri.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  assistantAnswer,
  getDocument,
  listDocuments,
  listTasks,
  mockLogin,
} from "@/api/mock/store";
import { DOCUMENT_STATUS_LABEL } from "@/lib/labels";

const ADMIN = "admin@contacrm.test";
/**
 * OPERATOR are `clients:read`, `documents:read`, `documents:write`, `tasks:*`.
 *
 * Nu VIEWER: contul acela este dezactivat în setul sintetic, deliberat, ca fluxul
 * „cont dezactivat" să existe undeva.
 */
const OPERATOR = "operator@contacrm.test";

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("ce știe asistentul", () => {
  it("spune cât e de lucru, din starea reală a documentelor", () => {
    const reply = assistantAnswer("cât e de lucru?");

    expect(reply.used).toEqual(["workload"]);
    expect(reply.engine).toBe("rules");
    expect(reply.text.length).toBeGreaterThan(0);
  });

  it("găsește un client și propune drumul, fără să-l urmeze", () => {
    const reply = assistantAnswer("deschide Alfa");

    expect(reply.used).toEqual(["find_client"]);
    expect(reply.links.every((link) => link.path.startsWith("/crm/clienti/"))).toBe(true);
  });

  it("spune când nu a găsit, în loc să presupună", () => {
    const reply = assistantAnswer("deschide Firma Care Nu Exista SRL");

    expect(reply.text).toContain("Nu am găsit");
    expect(reply.links).toEqual([]);
  });

  it("intrebarea despre un client nu nimereste raportul general", () => {
    // Ordinea intențiilor: cea îngustă înaintea celei largi. Fără ea, întrebarea
    // ar fi nimerit raportul general, care conține și el cuvântul „lipsește".
    const reply = assistantAnswer("ce lipsește la Alfa");

    expect(reply.used).toEqual(["client_month"]);
  });

  it("termenul este o dată adevărată, nu o formulare vagă", () => {
    const reply = assistantAnswer("când e termenul?");

    expect(reply.used).toEqual(["deadline"]);
    expect(reply.text).toMatch(/\d{2}\.\d{2}\.\d{4}/);
  });

  it("la o întrebare străină spune ce poate, nu doar că n-a înțeles", () => {
    const reply = assistantAnswer("care e capitala Franței");

    expect(reply.used).toEqual([]);
    expect(reply.text).toContain("Pot răspunde la");
    expect(reply.suggestions.length).toBeGreaterThan(0);
  });
});

describe("de ce stă documentul acolo unde stă", () => {
  /**
   * Un document al cărui nume nu se potrivește cu niciun altul.
   *
   * Căutarea intră și în textul citit, nu doar în nume: un fragment care apare
   * la două documente cere lămurire, pe bună dreptate. Testul vrea cazul cu un
   * singur răspuns, deci alege un nume care chiar identifică unul.
   */
  function uniquelyNamedDocument() {
    const all = listDocuments({ pageSize: 200 }).items;
    // Fără spațiu în nume: altfel întrebarea trebuie scrisă cu ghilimele, iar
    // cazul acela are testul lui. Aici verificăm forma obișnuită.
    const found = all.find(
      (row) =>
        !row.originalFilename.includes(" ") &&
        listDocuments({ q: row.originalFilename, pageSize: 5 }).total === 1,
    );
    expect(found, "setul sintetic nu are niciun document cu nume neambiguu").toBeDefined();
    return found!;
  }

  it("spune starea cu exact cuvântul de pe ecran", () => {
    const document = uniquelyNamedDocument();

    const reply = assistantAnswer(`de ce e la verificare ${document.originalFilename}`);

    expect(reply.used).toEqual(["explain_document"]);
    expect(reply.text).toContain(DOCUMENT_STATUS_LABEL[document.status]);
  });

  it("duce la document, nu doar vorbește despre el", () => {
    const document = uniquelyNamedDocument();

    const reply = assistantAnswer(`de ce e la verificare ${document.originalFilename}`);

    expect(reply.links.some((link) => link.path.includes(document.id))).toBe(true);
  });

  it("cere lămurire în loc să caute la întâmplare", () => {
    const reply = assistantAnswer("de ce e la verificare documentul?");

    expect(reply.text).toContain("Spune-mi care document");
  });

  it("nu confundă întrebarea cu „cât e de lucru”", () => {
    // „de ce e la verificare X" conține „verificare", care în altă intenție
    // înseamnă cu totul altceva. Ordinea listei este regula care le separă.
    const reply = assistantAnswer(`de ce e la verificare ${uniquelyNamedDocument().originalFilename}`);

    expect(reply.used).not.toContain("workload");
  });

  it("nu revarsă textul citit din document", () => {
    // §64: textul OCR nu iese în liste, iar un chat este cea mai largă listă.
    const document = uniquelyNamedDocument();

    const reply = assistantAnswer(`de ce e la verificare ${document.originalFilename}`);

    const ocr = getDocument(document.id).ocr.textPreview;
    expect(ocr, "documentul ales nu are text citit, deci testul ar fi vacuu").toBeTruthy();
    expect(reply.text).not.toContain(ocr!);
  });

  it("prinde un nume cu spații, dacă e scris între ghilimele", () => {
    // „28.5 scan.pdf" tăiat la primul spațiu devine „scan.pdf", care se
    // potrivește cu jumătate din dosar. Ghilimelele sunt modul în care un om
    // spune, natural, că numele e tot ce e înăuntru.
    const spaced = listDocuments({ pageSize: 200 }).items.find((row) =>
      row.originalFilename.includes(" "),
    );
    expect(spaced, "setul sintetic nu are niciun nume cu spațiu").toBeDefined();

    const reply = assistantAnswer(`de ce e la verificare „${spaced!.originalFilename}”`);

    expect(reply.used).toEqual(["explain_document"]);
    expect(reply.text).toContain(spaced!.originalFilename);
  });
});

describe("ce nu face asistentul", () => {
  it("nu propune unui rol ce rolul nu poate cere", () => {
    mockLogin(OPERATOR);

    const reply = assistantAnswer("bla bla");

    // OPERATOR nu are `audit:read`; lista de capacități este a lui, nu a
    // administratorului.
    expect(reply.text).not.toContain("audit");
  });

  it("nu execută nimic: propune, iar baza rămâne neatinsă", () => {
    const before = listTasks({}).length;

    const reply = assistantAnswer("notează să sun la Alfa vineri");

    expect(reply.actions).toHaveLength(1);
    expect(reply.actions[0]!.kind).toBe("create_task");
    // Rostul întreg: propunerea nu este o execuție.
    expect(listTasks({}).length).toBe(before);
  });

  it("nu pregătește niciodată un act contabil", () => {
    // Aprobarea unui document nu se propune nici măcar cu confirmare: acolo
    // trebuie să te uiți la document, nu să apeși un buton dintr-un chat.
    for (const question of ["aprobă tot", "șterge documentele", "respinge factura"]) {
      expect(assistantAnswer(question).actions).toEqual([]);
    }
  });

  it("orice propunere are un fel cunoscut", () => {
    const kinds = new Set(["create_task", "assign_client"]);

    for (const question of ["notează ceva", "atribuie documentele lui Alfa", "cât e de lucru?"]) {
      for (const action of assistantAnswer(question).actions) {
        expect(kinds.has(action.kind)).toBe(true);
        expect(action.summary.length).toBeGreaterThan(0);
      }
    }
  });
});
