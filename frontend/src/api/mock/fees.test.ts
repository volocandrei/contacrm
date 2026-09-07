/**
 * Onorariile, pe backendul simulat.
 *
 * Regulile există în două locuri: aici și în `backend/app/services/fees.py`.
 * Ce ține cele două împreună sunt cazurile scrise identic aici și în
 * `tests/test_fees.py`:
 *
 * - o renegociere nu rescrie suma unei luni deja generate;
 * - a doua generare nu dublează rândul și nu pierde încasarea;
 * - nu se facturează luni de dinaintea relației;
 * - câmpul gol („nu-l facturez") nu este același lucru cu zero („gratuit");
 * - totalurile se rup pe monedă, fiindcă lei plus euro nu este o sumă.
 *
 * Dacă una dintre implementări se abate, testul ei cade — nu amândouă tăcut.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  generateFees,
  getClientFee,
  getClientFeeHistory,
  getFeeMonth,
  listClients,
  listDocuments,
  markFeePaid,
  mockLogin,
  setClientFee,
  unmarkFeePaid,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** Luna în curs în setul sintetic; seed-ul a generat-o deja. */
const MONTH = "2026-08";

/**
 * Luni pe care setul sintetic **nu** le atinge.
 *
 * Testele care verifică generarea au nevoie de o lună goală: pe una pe care
 * seed-ul a facturat-o deja, „a generat acum" și „era deja acolo" arată identic.
 * Fiecare test primește alta, fiindcă starea magazinului este comună întregului
 * fișier.
 */
const FRESH_MONTHS = [
  "2026-06",
  "2026-05",
  "2026-04",
  "2026-02",
  "2026-01",
  "2025-11",
  "2025-10",
];
let freshIndex = 0;

function freshMonth(): string {
  const month = FRESH_MONTHS[freshIndex];
  freshIndex += 1;
  expect(month, "nu mai sunt luni libere pentru teste").toBeDefined();
  return month!;
}

beforeEach(() => {
  mockLogin(ADMIN);
});

/** Un client activ, luat din aceeași listă pe care o vede ecranul. */
function someClient(index = 0): string {
  const row = listClients({ status: "ACTIVE", pageSize: 50 }).items[index];
  expect(row, "setul sintetic nu are atâția clienți activi").toBeDefined();
  return row!.id;
}

/** Un rând de pe luna cerută, sau eroare — un test care caută în gol trece oricând. */
function rowOf(clientId: string, month: string) {
  const row = getFeeMonth(month).rows.find(
    (entry) => entry.clientId === clientId,
  );
  expect(row, "clientul nu apare pe lună").toBeDefined();
  return row!;
}

describe("registrul nu își rescrie trecutul", () => {
  it("o renegociere nu schimbă suma unei luni deja generate", () => {
    const month = freshMonth();
    const clientId = someClient();
    setClientFee(clientId, { amount: "500", startsOn: "2020-01-01" });
    generateFees(month);
    expect(rowOf(clientId, month).amount).toBe("500.00");

    setClientFee(clientId, { amount: "800" });

    const row = rowOf(clientId, month);
    expect(row.amount).toBe("500.00");
    // Ce se va factura de acum înainte este totuși cel nou.
    expect(row.configured).toBe("800.00");
  });

  it("a doua generare nu dublează rândul și nu pierde încasarea", () => {
    const month = freshMonth();
    const clientId = someClient(1);
    setClientFee(clientId, { amount: "500", startsOn: "2020-01-01" });
    generateFees(month);
    markFeePaid({ clientId, referenceMonth: month, paidOn: `${month}-10` });
    setClientFee(clientId, { amount: "800" });

    const after = generateFees(month);

    const rows = after.rows.filter((entry) => entry.clientId === clientId);
    expect(rows).toHaveLength(1);
    expect(rows[0]!.amount).toBe("500.00");
    expect(rows[0]!.paidOn).toBe(`${month}-10`);
  });
});

describe("nu inventează datorii", () => {
  it("un onorariu care începe mai târziu nu facturează lunile dinainte", () => {
    const month = freshMonth();
    const clientId = someClient(2);
    setClientFee(clientId, { amount: "500", startsOn: `${month}-01` });

    const before = generateFees("2025-11");
    expect(
      before.rows.filter((row) => row.isGenerated && row.clientId === clientId),
    ).toEqual([]);

    // A doua jumătate contează: fără ea testul ar trece și dacă generarea n-ar
    // face nimic niciodată.
    generateFees(month);
    expect(rowOf(clientId, month).amount).toBe("500.00");
  });

  it("o lună viitoare este refuzată", () => {
    expect(() => generateFees("2027-01")).toThrow(/nu au început/i);
  });

  it("câmpul gol nu este același lucru cu zero", () => {
    const month = freshMonth();
    const clientId = someClient(3);

    setClientFee(clientId, { amount: "0", startsOn: "2020-01-01" });
    generateFees(month);
    // Zero se facturează: „îl servesc gratuit" este o afirmație, nu o absență.
    expect(rowOf(clientId, month).isGenerated).toBe(true);

    setClientFee(clientId, { amount: null });
    expect(getClientFee(clientId).amount).toBeNull();
    // Luna deja generată rămâne — chiar a fost facturată.
    expect(rowOf(clientId, month).isGenerated).toBe(true);
    // O lună nouă însă nu se mai generează pentru el.
    const later = generateFees("2025-12");
    expect(
      later.rows.filter((row) => row.isGenerated && row.clientId === clientId),
    ).toEqual([]);
  });
});

describe("cifrele", () => {
  it("totalurile se rup pe monedă", () => {
    const month = getFeeMonth(MONTH);

    for (const totals of month.totals) {
      const rows = month.rows.filter(
        (row) => row.isGenerated && row.currency === totals.currency,
      );
      const billed = rows.reduce((sum, row) => sum + Number(row.amount), 0);
      const collected = rows
        .filter((row) => row.isPaid)
        .reduce((sum, row) => sum + Number(row.amount), 0);

      expect(Number(totals.billed)).toBeCloseTo(billed, 2);
      expect(Number(totals.collected)).toBeCloseTo(collected, 2);
      expect(Number(totals.outstanding)).toBeCloseTo(billed - collected, 2);
    }
    // Setul sintetic are și euro: altfel bucla de mai sus ar verifica o singură
    // monedă și n-ar spune nimic despre ruperea lor.
    expect(month.totals.map((item) => item.currency)).toContain("EUR");
    expect(month.totals[0]!.currency).toBe("RON");
  });

  it("clienții neîncasați se numără peste toate monedele", () => {
    const month = getFeeMonth(MONTH);

    expect(month.unpaidClients).toBe(
      month.rows.filter((row) => row.isGenerated && !row.isPaid).length,
    );
  });

  it("restanțele sunt doar lunile mai vechi și neîncasate", () => {
    const month = getFeeMonth(MONTH);

    expect(month.arrears.length).toBeGreaterThan(0);
    for (const arrear of month.arrears) {
      expect(arrear.period < MONTH).toBe(true);
    }
  });

  it("o restanță plătită iese din listă", () => {
    const before = getFeeMonth(MONTH).arrears;
    const target = before[0]!;

    markFeePaid({ clientId: target.clientId, referenceMonth: target.period });

    const after = getFeeMonth(MONTH).arrears;
    expect(after).toHaveLength(before.length - 1);
    expect(
      after.some(
        (item) =>
          item.clientId === target.clientId && item.period === target.period,
      ),
    ).toBe(false);
  });
});

describe("încasarea", () => {
  it("se poate anula, iar rândul rămâne facturat", () => {
    const month = freshMonth();
    const clientId = someClient(4);
    setClientFee(clientId, { amount: "500", startsOn: "2020-01-01" });
    generateFees(month);

    const paid = markFeePaid({ clientId, referenceMonth: month });
    expect(paid.isPaid).toBe(true);
    expect(paid.paidByName).toBeTruthy();

    const undone = unmarkFeePaid({ clientId, referenceMonth: month });
    expect(undone.isPaid).toBe(false);
    expect(undone.isGenerated).toBe(true);
  });

  it("o lună negenerată nu se poate încasa", () => {
    expect(() =>
      markFeePaid({ clientId: someClient(), referenceMonth: "2024-01" }),
    ).toThrow();
  });
});

describe("cine are voie", () => {
  it("un contabil nu vede onorariile", () => {
    mockLogin("contabil@contacrm.test");

    expect(() => getFeeMonth(MONTH)).toThrow(/permisiune/i);
  });
});

describe("istoricul unui client", () => {
  it("listează lunile facturate, cea mai recentă întâi", () => {
    const clientId = someClient();

    const rows = getClientFeeHistory(clientId);

    expect(rows.length).toBeGreaterThan(1);
    const periods = rows.map((row) => row.period);
    expect([...periods].sort().reverse()).toEqual(periods);
  });

  it("păstrează suma fiecărei luni, nu pe cea în vigoare", () => {
    const month = freshMonth();
    const clientId = someClient(5);
    setClientFee(clientId, { amount: "500", startsOn: "2020-01-01" });
    generateFees(month);
    setClientFee(clientId, { amount: "900" });

    const row = getClientFeeHistory(clientId).find((entry) => entry.period === month);

    expect(row?.amount).toBe("500.00");
    expect(row?.configured).toBe("900.00");
  });

  it("un contabil nu are acces", () => {
    const clientId = someClient();
    mockLogin("contabil@contacrm.test");

    expect(() => getClientFeeHistory(clientId)).toThrow(/permisiune/i);
  });
});

describe("cât de mult de lucru pentru câți bani", () => {
  it("rândul poartă numărul de documente al lunii", () => {
    const month = getFeeMonth(MONTH);

    // Setul sintetic are documente pe luna în curs; dacă nu ar avea, testul de
    // mai jos ar trece degeaba.
    expect(month.rows.some((row) => row.documents > 0)).toBe(true);
    for (const row of month.rows) {
      expect(row.documents).toBe(
        listDocuments({ clientId: row.clientId, referenceMonth: MONTH, pageSize: 200 }).total,
      );
    }
  });
});
