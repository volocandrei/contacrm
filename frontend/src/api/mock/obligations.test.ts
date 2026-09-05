/**
 * Termenele de depunere, pe backendul simulat.
 *
 * Aritmetica termenelor există în două locuri: aici și în
 * `backend/app/domain/obligations.py`. Nu este ideal, dar este ce înseamnă un
 * backend simulat. **Ce ține cele două împreună sunt cazurile de margine scrise
 * identic** aici și în `test_obligations_domain.py`:
 *
 * - ziua care nu există în luna termenului se retează, nu dispare;
 * - un trimestru se numește după luna în care se **încheie**;
 * - un termen deja trecut rămâne în listă, marcat, fiindcă nu se rezolvă
 *   așteptând;
 * - o depunere marcată de două ori rămâne o singură depunere.
 *
 * Dacă una dintre implementări se abate, testul ei cade — nu amândouă tăcut.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  listClientObligations,
  listClients,
  listObligationTypes,
  listObligations,
  markObligationFiled,
  mockLogin,
  setClientObligations,
  unmarkObligationFiled,
  updateObligationType,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** Operatorul are `documents:*`, nu `periods:manage`. */
const OPERATOR = "operator@contacrm.test";

/** Ceasul simulat: `MOCK_NOW` este 27 august 2026. */
const TODAY = "2026-08-27";

function aClient(): string {
  return listClients({ pageSize: 5 }).items[0]!.id;
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("ce are cabinetul de depus", () => {
  it("dă termene pentru clienții care au declarații configurate", () => {
    const rows = listObligations({});

    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((row) => row.clientName.length > 0)).toBe(true);
  });

  it("le întoarce în ordinea termenelor", () => {
    const deadlines = listObligations({}).map((row) => row.deadline);

    expect([...deadlines].sort()).toEqual(deadlines);
  });

  it("păstrează în listă termenele deja trecute", () => {
    // Un termen ratat nu se rezolvă trecând timpul. O listă care ar începe de
    // azi l-ar ascunde exact pe cel care contează cel mai mult.
    const overdue = listObligations({}).filter((row) => row.isOverdue);

    expect(overdue.length).toBeGreaterThan(0);
    expect(overdue.every((row) => row.deadline < TODAY)).toBe(true);
    expect(overdue.every((row) => row.filedAt === null)).toBe(true);
  });

  it("refuză un interval întors în loc să întoarcă o listă goală", () => {
    // Zero rezultate s-ar citi ca „nu am nimic de depus".
    expect(() => listObligations({ since: "2026-10-01", until: "2026-09-01" })).toThrow(
      /interval/i,
    );
  });

  it("filtrează pe client", () => {
    const clientId = aClient();

    const rows = listObligations({ clientId });

    expect(rows.every((row) => row.clientId === clientId)).toBe(true);
  });
});

describe("aritmetica termenului", () => {
  it("pune termenul în luna următoare perioadei", () => {
    const clientId = aClient();
    const monthly = listObligationTypes().find((type) => type.code === "D300")!;
    setClientObligations(clientId, [monthly.id]);

    const row = listObligations({ clientId }).find((entry) => entry.period === "2026-08")!;

    expect(row.deadline).toBe("2026-09-25");
  });

  it("reteaza o zi care nu există în luna termenului", () => {
    // Un termen pe 30 nu are ce căuta în februarie. Retezat, nu sărit: unul care
    // dispare exact în luna în care cade nu se vede că lipsește.
    const clientId = aClient();
    const monthly = listObligationTypes().find((type) => type.code === "D300")!;
    updateObligationType(monthly.id, { deadlineDay: 31 });
    setClientObligations(clientId, [monthly.id]);

    const row = listObligations({
      clientId,
      since: "2027-02-01",
      until: "2027-02-28",
    })[0]!;

    expect(row.period).toBe("2027-01");
    expect(row.deadline).toBe("2027-02-28");

    updateObligationType(monthly.id, { deadlineDay: 25 });
  });

  it("numește trimestrul după luna în care se încheie", () => {
    // Trimestrul II 2026 este `2026-06`, nu `2026-04`: perioada se numește după
    // ce acoperă.
    const clientId = aClient();
    const quarterly = listObligationTypes().find((type) => type.code === "D300_TRIM")!;
    setClientObligations(clientId, [quarterly.id]);

    const rows = listObligations({ clientId, since: "2026-10-01", until: "2026-10-31" });

    expect(rows.map((row) => row.period)).toEqual(["2026-09"]);
    expect(rows[0]!.deadline).toBe("2026-10-25");
  });

  it("dă un singur termen pe trimestru, nu trei", () => {
    const clientId = aClient();
    const quarterly = listObligationTypes().find((type) => type.code === "D300_TRIM")!;
    setClientObligations(clientId, [quarterly.id]);

    const rows = listObligations({ clientId, since: "2026-09-01", until: "2027-12-31" });

    expect(rows.map((row) => row.period)).toEqual([
      "2026-09",
      "2026-12",
      "2027-03",
      "2027-06",
      "2027-09",
    ]);
  });
});

describe("de când are aplicația dreptul să spună ceva", () => {
  it("nu produce termene dinainte de ziua în care i s-a spus", () => {
    // Un cabinet care instalează azi a depus, evident, și luna trecută — dar
    // aplicația nu are de unde ști, fiindcă nu exista. Prima variantă arăta 52
    // de rânduri roșii pe o instalare proaspătă: nu informație, ci o afirmație
    // despre ceva ce nu a văzut. După a treia zi nimeni nu s-ar mai fi uitat la
    // culoarea aia, nici când ar fi însemnat ceva.
    const clientId = aClient();
    const monthly = listObligationTypes().find((type) => type.code === "D300")!;

    setClientObligations(clientId, [monthly.id]);

    expect(listObligations({ clientId }).every((row) => row.deadline >= TODAY)).toBe(true);
    expect(listObligations({ clientId }).some((row) => row.isOverdue)).toBe(false);
  });

  it("păstrează perioada încheiată al cărei termen încă nu a trecut", () => {
    // Configurat azi, decontul lunii trecute are termen peste trei săptămâni și
    // este al cabinetului. Se compară cu termenul, nu cu perioada.
    const clientId = aClient();
    const monthly = listObligationTypes().find((type) => type.code === "D300")!;

    setClientObligations(clientId, [monthly.id]);

    const periods = listObligations({ clientId }).map((row) => row.period);
    expect(periods).toContain("2026-08");
  });
});

describe("marcarea unei depuneri", () => {
  it("o arată ca depusă, cu cine a depus", () => {
    const row = listObligations({})[0]!;

    markObligationFiled({
      clientId: row.clientId,
      obligationTypeId: row.obligationTypeId,
      period: row.period,
    });

    const after = listObligations({}).find(
      (entry) => entry.clientId === row.clientId && entry.period === row.period,
    )!;
    expect(after.filedAt).not.toBeNull();
    expect(after.filedByName).toBeTruthy();
    expect(after.isOverdue).toBe(false);
  });

  it("nu scoate rândul din listă", () => {
    // O listă care ar ascunde depusele arată identic când munca e gata și când
    // clientul nu are nimic configurat — două situații care cer lucruri opuse.
    const before = listObligations({}).length;
    const row = listObligations({})[0]!;

    markObligationFiled({
      clientId: row.clientId,
      obligationTypeId: row.obligationTypeId,
      period: row.period,
    });

    expect(listObligations({}).length).toBe(before);
  });

  it("marcată de două ori rămâne o singură depunere", () => {
    const row = listObligations({})[0]!;
    const key = {
      clientId: row.clientId,
      obligationTypeId: row.obligationTypeId,
      period: row.period,
    };

    const first = markObligationFiled(key);
    const second = markObligationFiled(key);

    // Cine a depus rămâne cine a depus.
    expect(second.filedAt).toBe(first.filedAt);
  });

  it("se poate anula, dacă s-a apăsat pe rândul greșit", () => {
    const row = listObligations({})[0]!;
    const key = {
      clientId: row.clientId,
      obligationTypeId: row.obligationTypeId,
      period: row.period,
    };
    markObligationFiled(key);

    unmarkObligationFiled(key);

    const after = listObligations({}).find(
      (entry) => entry.clientId === row.clientId && entry.period === row.period,
    )!;
    expect(after.filedAt).toBeNull();
  });

  it("anularea a ceva nedepus este 404, nu o reușită tăcută", () => {
    const row = listObligations({})[0]!;

    expect(() =>
      unmarkObligationFiled({
        clientId: row.clientId,
        obligationTypeId: row.obligationTypeId,
        period: "2020-01",
      }),
    ).toThrow();
  });
});

describe("catalogul", () => {
  it("termenul se schimbă din aplicație, iar lista îl urmează", () => {
    // Aplicația nu pretinde că știe legea: cine constată că un termen este altul
    // îl schimbă de aici.
    const clientId = aClient();
    const monthly = listObligationTypes().find((type) => type.code === "D300")!;
    setClientObligations(clientId, [monthly.id]);

    updateObligationType(monthly.id, { deadlineDay: 15 });

    expect(listObligations({ clientId }).every((row) => row.deadline.endsWith("-15"))).toBe(true);
    updateObligationType(monthly.id, { deadlineDay: 25 });
  });

  it("o declarație dezactivată nu mai produce termene, dar rămâne în catalog", () => {
    const clientId = aClient();
    const monthly = listObligationTypes().find((type) => type.code === "D300")!;
    setClientObligations(clientId, [monthly.id]);

    updateObligationType(monthly.id, { isActive: false });

    expect(listObligations({ clientId })).toEqual([]);
    // Una care dispare când o dezactivezi nu se mai poate reactiva.
    expect(listObligationTypes().some((type) => type.code === "D300")).toBe(true);
    updateObligationType(monthly.id, { isActive: true });
  });
});

describe("cine ce depune", () => {
  it("setul se înlocuiește, nu se adaugă", () => {
    // Ce se trimite înapoi este starea de pe ecran. O rută care doar adaugă ar
    // face imposibilă scoaterea unei declarații.
    const clientId = aClient();
    const [first, second] = listObligationTypes();

    setClientObligations(clientId, [first!.id, second!.id]);
    const after = setClientObligations(clientId, [second!.id]);

    expect(after.map((type) => type.id)).toEqual([second!.id]);
  });

  it("un set gol lasă clientul fără termene", () => {
    const clientId = aClient();

    setClientObligations(clientId, []);

    expect(listClientObligations(clientId)).toEqual([]);
    expect(listObligations({ clientId })).toEqual([]);
  });
});

describe("permisiuni", () => {
  it("un operator poate citi, dar nu poate marca", () => {
    // Marcarea unei depuneri este o decizie contabilă, nu una de operare.
    const row = listObligations({})[0]!;
    mockLogin(OPERATOR);

    expect(() => listObligations({})).not.toThrow();
    expect(() =>
      markObligationFiled({
        clientId: row.clientId,
        obligationTypeId: row.obligationTypeId,
        period: row.period,
      }),
    ).toThrow();
  });
});
