/**
 * Rapoartele pe backend-ul simulat (§84).
 *
 * Ce se verifică aici este că oglinda se poartă ca originalul. Regulile care
 * contează — ce înseamnă „procesat", ce se răspunde când nu s-a terminat nimic,
 * unde ajung documentele fără lună sau fără client — sunt aceleași în
 * `app/services/report_service.py`. Dacă se despart, demonstrația arată altceva
 * decât aplicația, iar diferența se descoperă târziu și la client.
 *
 * Ce **nu** se oglindește, deliberat: plafonul de 200 de documente. Acolo era
 * greșeala pe care mutarea agregării în backend a reparat-o.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { listDocuments, mockLogin, reportSummary } from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("acoperire", () => {
  it("numără toate documentele, nu prima pagină", () => {
    // Motivul pentru care raportul s-a mutat în backend: interfața cerea primele
    // 200 și afișa rezultatul ca și cum ar fi acoperit tot.
    const everything = listDocuments({ pageSize: 200 });
    expect(reportSummary({}).total).toBe(everything.total);
  });

  it("suma găleților pe stare este totalul", () => {
    const summary = reportSummary({});
    const sum = summary.byStatus.reduce((acc, bucket) => acc + bucket.count, 0);
    expect(sum).toBe(summary.total);
  });

  it("suma găleților pe lună este tot totalul — nimic nu se pierde pe drum", () => {
    const summary = reportSummary({});
    const sum = summary.byMonth.reduce((acc, bucket) => acc + bucket.count, 0);
    expect(sum).toBe(summary.total);
  });
});

describe("rata de reușită", () => {
  it("nu numără în numitor ce este încă în lucru", () => {
    const summary = reportSummary({});
    const inProgress = listDocuments({ pageSize: 200 }).items.filter(
      (doc) => doc.status === "RECEIVED" || doc.status === "PROCESSING",
    ).length;

    expect(summary.processed).toBe(summary.total - inProgress);
  });

  it("este `null`, nu zero, când nu s-a terminat nimic", () => {
    // Zero s-ar citi ca „totul a eșuat", ceea ce este altceva. Filtrăm pe o lună
    // în care nu există niciun document.
    const summary = reportSummary({ fromMonth: "2019-01", toMonth: "2019-01" });

    expect(summary.total).toBe(0);
    expect(summary.successRate).toBeNull();
  });
});

describe("ce lipsește se numără", () => {
  it("luna absentă are gălata ei, la coadă", () => {
    const summary = reportSummary({});
    const keys = summary.byMonth.map((bucket) => bucket.key);
    const undated = keys.filter((key) => key === null);

    // Dacă setul sintetic are documente fără lună, ele apar ultimele.
    if (undated.length > 0) expect(keys.at(-1)).toBeNull();
    // Iar lunile datate rămân în ordine descrescătoare.
    const dated = keys.filter((key): key is string => key !== null);
    expect(dated).toEqual([...dated].sort((a, b) => b.localeCompare(a)));
  });

  it("gălata absenței nu poartă etichetă", () => {
    // Formularea o alege interfața; dacă ar veni și de aici, ar exista două
    // surse pentru același text.
    for (const bucket of [...reportSummary({}).byClient, ...reportSummary({}).byType]) {
      if (bucket.key === null) expect(bucket.label).toBeNull();
    }
  });

  it("stările nu poartă etichetă — `status-badge.tsx` le traduce", () => {
    for (const bucket of reportSummary({}).byStatus) {
      expect(bucket.label).toBeNull();
    }
  });
});

describe("filtre", () => {
  it("intervalul de luni include ambele capete", () => {
    const all = reportSummary({});
    const months = all.byMonth.filter((b) => b.key !== null).map((b) => b.key!);
    const [recent, older] = [months[0]!, months.at(-1)!];

    const ranged = reportSummary({ fromMonth: older, toMonth: recent });
    const inRange = all.byMonth
      .filter((b) => b.key !== null && b.key >= older && b.key <= recent)
      .reduce((acc, b) => acc + b.count, 0);

    expect(ranged.total).toBe(inRange);
  });

  it("un interval de luni exclude documentele fără lună", () => {
    const all = reportSummary({});
    const undated = all.byMonth.find((b) => b.key === null)?.count ?? 0;
    const months = all.byMonth.filter((b) => b.key !== null).map((b) => b.key!);

    const ranged = reportSummary({ fromMonth: months.at(-1)!, toMonth: months[0]! });
    expect(ranged.total).toBe(all.total - undated);
  });

  it("filtrarea pe client restrânge totalul", () => {
    const all = reportSummary({});
    const first = all.byClient.find((bucket) => bucket.key !== null);
    expect(first).toBeDefined();

    const scoped = reportSummary({ clientId: first!.key! });
    expect(scoped.total).toBe(first!.count);
  });
});

describe("clasament", () => {
  it("lista de clienți este scurtă, dar numărul real nu se ascunde", () => {
    const summary = reportSummary({});
    expect(summary.byClient.length).toBeLessThanOrEqual(10);
    expect(summary.clientCount).toBeGreaterThanOrEqual(summary.byClient.length);
  });

  it("este ordonat descrescător după volum", () => {
    const counts = reportSummary({}).byClient.map((bucket) => bucket.count);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
  });
});

describe("permisiuni", () => {
  it("orice rol care vede documentele le poate și număra", () => {
    // Decizia din backend: un raport este o numărătoare peste documente, deci
    // permisiunea este aceeași (`documents:read`). Toate rolurile o au — inclusiv
    // VIEWER — deci aici nu există niciun refuz de verificat. Refuzul pentru
    // anonimi se verifică unde este chiar aplicat: `tests/test_reports_api.py`.
    for (const email of [ADMIN, "contabil@contacrm.test", "operator@contacrm.test"]) {
      mockLogin(email);
      expect(reportSummary({}).total).toBeGreaterThan(0);
    }
  });
});
