/**
 * Cifrele cu care se deschide ziua, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_dashboard_kpis.py`.
 *
 * Panoul numără, de la M5, ce **s-a întâmplat**: documente sosite, în procesare,
 * cu erori. Nu spunea nimic despre ce mai are cabinetul de **făcut** — cine n-a
 * fost întrebat și cine a fost dar tace. Iar dimineața nu începe uitându-te la ce
 * a intrat, ci la ce mai ai de recuperat.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  collectionState,
  composeDocumentRequest,
  getDashboard,
  listMissingDocuments,
  mockLogin,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";

/** Luna pe care o descriu cifrele panoului, ca în `getDashboard`. */
function monthWithGaps(): string {
  for (const month of ["2026-08", "2026-07", "2026-06"]) {
    if (listMissingDocuments(month).length > 0) return month;
  }
  throw new Error("setul sintetic nu are nicio lună cu documente lipsă");
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("ce mai are cabinetul de făcut", () => {
  it("numără la fel ca ecranul „Documente lipsă”", () => {
    // Două moduri de a număra „cine n-a fost întrebat" ar fi dat, într-o zi,
    // două răspunsuri — iar cel de pe panou ar fi fost cel crezut.
    const month = monthWithGaps();
    const rows = listMissingDocuments(month);

    const state = collectionState(month);

    expect(state.notAsked).toBe(rows.filter((row) => row.requestedAt === null).length);
    expect(state.awaitingReply).toBe(
      rows.filter((row) => row.requestedAt !== null && row.receivedThroughLink === 0).length,
    );
  });

  it("după ce ceri, clientul trece de la «neîntrebat» la «așteaptă răspuns»", () => {
    // Două acțiuni diferite: la primul mai ceri, la al doilea suni.
    const month = monthWithGaps();
    const target = listMissingDocuments(month).find((row) => row.requestedAt === null);
    expect(target, "setul sintetic nu mai are niciun client neîntrebat").toBeDefined();
    const before = collectionState(month);

    composeDocumentRequest(target!.period.clientId, month);

    const after = collectionState(month);
    expect(after.notAsked).toBe(before.notAsked - 1);
    expect(after.awaitingReply).toBe(before.awaitingReply + 1);
  });

  it("panoul publică amândouă cifrele", () => {
    const kpis = getDashboard().kpis;

    expect(typeof kpis.clientsNotAsked).toBe("number");
    expect(typeof kpis.clientsAwaitingReply).toBe("number");
  });
});
