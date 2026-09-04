/**
 * Așteptările lunare, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_periods_api.py::TestExpectations`.
 *
 * Piesa lipsă din tot lanțul de contabilitate: checklistul lunii, „Documente
 * lipsă" și starea perioadei se derivă din lista asta, care exista în date fără
 * niciun drum prin care s-o scrie cineva.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import {
  listClients,
  listExpectations,
  mockLogin,
  setExpectations,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** OPERATOR are `documents:write`, dar nu `periods:manage`. */
const OPERATOR = "operator@contacrm.test";

let clientId = "";

beforeEach(() => {
  mockLogin(ADMIN);
  clientId = listClients({ pageSize: 5 }).items[0]!.id;
});

describe("așteptări lunare", () => {
  it("lista întreagă se înlocuiește, nu se completează", () => {
    setExpectations(clientId, [{ documentTypeCode: "FACTURA_INTRARE", expectedMinCount: 5 }]);

    const after = listExpectations(clientId);
    // Ce nu mai apare în listă nu se mai așteaptă.
    expect(after.map((item) => item.documentTypeCode)).toEqual(["FACTURA_INTRARE"]);
    expect(after[0]?.expectedMinCount).toBe(5);
  });

  it("eticheta vine de la server, nu dintr-o hartă locală", () => {
    setExpectations(clientId, [{ documentTypeCode: "EXTRAS_CONT", expectedMinCount: 1 }]);

    expect(listExpectations(clientId)[0]?.documentTypeLabel.trim().length).toBeGreaterThan(0);
  });

  it("zero nu este o așteptare", () => {
    // Absența se exprimă scoțând rândul, nu cerând zero documente.
    expect(() =>
      setExpectations(clientId, [{ documentTypeCode: "FACTURA_INTRARE", expectedMinCount: 0 }]),
    ).toThrowError(ApiError);
  });

  it("un tip de document inexistent este refuzat", () => {
    expect(() =>
      setExpectations(clientId, [{ documentTypeCode: "INVENTAT", expectedMinCount: 1 }]),
    ).toThrowError(/inexistent/);
  });

  it("un operator nu hotărăște ce datorează un client", () => {
    mockLogin(OPERATOR);
    // Act contabil, nu editare de fișă: aceeași permisiune ca închiderea lunii.
    expect(() =>
      setExpectations(clientId, [{ documentTypeCode: "FACTURA_INTRARE", expectedMinCount: 1 }]),
    ).toThrowError(/permisiunea/);
  });
});
