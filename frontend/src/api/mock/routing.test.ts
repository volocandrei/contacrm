/**
 * Rutele backendului simulat, cerute pe drumul pe care le cere aplicația.
 *
 * **De ce nu ajung testele de magazin.** Acelea cheamă funcția direct
 * (`store.processingHealth()`) și trec chiar dacă ruta este înregistrată greșit
 * — cu alt verb, cu altă cale, sau după una care o umbrește. Exact asta s-a
 * întâmplat: `GET /documents/processing/health` a fost înregistrată prima oară
 * ca `POST`, iar singurul semn ar fi fost un panou care spune „starea cozii nu
 * s-a putut citi" în demonstrație — un ecran care arată o eroare acolo unde nu
 * este niciuna.
 *
 * Se verifică **forma drumului**, nu regulile: acelea au testele lor, pe funcții.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { mockRequest } from "@/api/mock/router";
import { mockLogin } from "@/api/mock/store";
import { ApiError } from "@/api/types";

beforeEach(() => {
  mockLogin("admin@contacrm.test");
});

function get(path: string): unknown {
  return mockRequest("GET", path, {}, {});
}

describe("starea cozii de procesare", () => {
  it("răspunde la GET, pe calea pe care o cere aplicația", () => {
    const answer = get("/documents/processing/health") as Record<string, unknown>;

    expect(answer).toHaveProperty("queued");
    expect(answer).toHaveProperty("recentFailures");
  });

  it("nu este umbrită de ruta documentului cu identificator", () => {
    // `/documents/:id` are două segmente, ruta asta are trei — dar dacă cineva
    // ar înregistra vreodată `/documents/:id/:section`, „processing/health" ar
    // ajunge acolo, iar panoul ar cere un document numit „processing".
    const answer = get("/documents/processing/health") as Record<string, unknown>;

    expect(answer).not.toHaveProperty("originalFilename");
  });

  it("o cale care nu există rămâne 404, nu un răspuns gol", () => {
    // Contra-proba: fără ea, primul test ar trece și cu o rută care prinde tot.
    expect(() => get("/documents/processing/inexistent")).toThrow(ApiError);
  });
});
