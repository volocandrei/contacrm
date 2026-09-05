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
import { assistantAnswer, listTasks, mockLogin } from "@/api/mock/store";

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
