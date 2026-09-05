/**
 * Șabloanele de așteptări, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_expectation_templates.py`.
 *
 * Ce se apără, în ordinea gravității:
 *
 * 1. **Aplicarea chiar schimbă checklistul.** Un șablon care se salvează frumos
 *    dar nu ajunge în listele clienților n-a făcut nimic — și nimeni n-ar
 *    observa până la sfârșitul lunii.
 * 2. **Înlocuiește, nu adaugă.** Două profiluri aplicate pe rând ar lăsa o listă
 *    pe care n-a ales-o nimeni.
 * 3. **Șablonul nu este o legătură**: schimbat sau șters, clienții rămân cum au
 *    fost configurați.
 * 4. **Decizia este contabilă**: `periods:manage`, ca și așteptările unui client.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  applyExpectationTemplate,
  createExpectationTemplate,
  deleteExpectationTemplate,
  listClients,
  listExpectationTemplates,
  listExpectations,
  mockLogin,
  saveExpectationTemplate,
  setExpectations,
  templateFromClient,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** Operatorul are `documents:*`, nu `periods:manage`. */
const OPERATOR = "operator@contacrm.test";

const PROFILE = [
  { documentTypeCode: "FACTURA_INTRARE", expectedMinCount: 3 },
  { documentTypeCode: "EXTRAS_CONT", expectedMinCount: 1 },
];

let counter = 0;

/** Nume unic per test: magazinul simulat trăiește în modul, între teste. */
function uniqueName(): string {
  counter += 1;
  return `Profil ${counter}`;
}

function aClient(): string {
  return listClients({ pageSize: 5 }).items[0]!.id;
}

function expectationsOf(clientId: string): Record<string, number> {
  return Object.fromEntries(
    listExpectations(clientId).map((item) => [item.documentTypeCode, item.expectedMinCount]),
  );
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("profilul", () => {
  it("se salvează cu numele pe care i-l dă cabinetul", () => {
    const name = uniqueName();

    const template = createExpectationTemplate(name, PROFILE);

    expect(template.name).toBe(name);
    expect(listExpectationTemplates().some((row) => row.id === template.id)).toBe(true);
  });

  it("aplicat, schimbă ce cere luna de la client", () => {
    const clientId = aClient();
    const template = createExpectationTemplate(uniqueName(), PROFILE);

    const result = applyExpectationTemplate(template.id, [clientId]);

    expect(result.applied).toBe(1);
    expect(expectationsOf(clientId)).toEqual({ FACTURA_INTRARE: 3, EXTRAS_CONT: 1 });
  });

  it("înlocuiește lista, nu se adaugă la ea", () => {
    const clientId = aClient();
    const wide = createExpectationTemplate(uniqueName(), PROFILE);
    const narrow = createExpectationTemplate(uniqueName(), [
      { documentTypeCode: "FACTURA_INTRARE", expectedMinCount: 1 },
    ]);
    applyExpectationTemplate(wide.id, [clientId]);

    applyExpectationTemplate(narrow.id, [clientId]);

    expect(expectationsOf(clientId)).toEqual({ FACTURA_INTRARE: 1 });
  });

  it("se poate salva din ce s-a configurat deja pe un client", () => {
    const clientId = aClient();
    setExpectations(clientId, [{ documentTypeCode: "EXTRAS_CONT", expectedMinCount: 2 }]);

    const template = templateFromClient(clientId, uniqueName());

    expect(template.expectations).toEqual([
      expect.objectContaining({ documentTypeCode: "EXTRAS_CONT", expectedMinCount: 2 }),
    ]);
  });
});

describe("ce nu face", () => {
  it("schimbat, lasă neatinși clienții cărora li s-a aplicat", () => {
    // Dacă ar moșteni la distanță, o bifă scoasă azi ar dispărea de pe
    // doisprezece clienți fără ca cineva să le fi atins ecranul.
    const clientId = aClient();
    const template = createExpectationTemplate(uniqueName(), PROFILE);
    applyExpectationTemplate(template.id, [clientId]);

    saveExpectationTemplate(template.id, template.name, [
      { documentTypeCode: "FACTURA_INTRARE", expectedMinCount: 9 },
    ]);

    expect(expectationsOf(clientId)).toEqual({ FACTURA_INTRARE: 3, EXTRAS_CONT: 1 });
  });

  it("șters, lasă neatinși clienții cărora li s-a aplicat", () => {
    const clientId = aClient();
    const template = createExpectationTemplate(uniqueName(), PROFILE);
    applyExpectationTemplate(template.id, [clientId]);

    deleteExpectationTemplate(template.id);

    expect(expectationsOf(clientId)).toEqual({ FACTURA_INTRARE: 3, EXTRAS_CONT: 1 });
  });

  it("nu lasă două profiluri cu același nume", () => {
    // Două rânduri pe care nimeni nu le poate deosebi, iar unul rescrie clienți.
    const name = uniqueName();
    createExpectationTemplate(name, PROFILE);

    expect(() => createExpectationTemplate(name.toUpperCase(), PROFILE)).toThrow();
  });

  it("refuză un nume din spații", () => {
    expect(() => createExpectationTemplate("   ", PROFILE)).toThrow();
  });

  it("refuză un tip de document inexistent", () => {
    // Ignorat în tăcere, ar lipsi din raport abia peste o lună.
    expect(() =>
      createExpectationTemplate(uniqueName(), [
        { documentTypeCode: "NU_EXISTA", expectedMinCount: 1 },
      ]),
    ).toThrow();
  });
});

describe("cine are voie", () => {
  it("cere `periods:manage` pentru scriere, ca așteptările unui client", () => {
    mockLogin(OPERATOR);

    expect(() => createExpectationTemplate(uniqueName(), PROFILE)).toThrow();
  });

  it("lasă pe oricine vede documentele să vadă și profilurile", () => {
    mockLogin(OPERATOR);

    expect(() => listExpectationTemplates()).not.toThrow();
  });
});
