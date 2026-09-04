/**
 * Cronologia recepțiilor, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_intakes_api.py`.
 *
 * Ecranul „Mesaje" cerea `GET /messages`, o rută care nu a existat niciodată.
 * Ce arată acum este partea de cronologie care chiar există în date.
 */
import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import { listIntakes, mockLogin } from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";

describe("recepții", () => {
  it("cele mai noi primele", () => {
    mockLogin(ADMIN);
    const moments = listIntakes({ pageSize: 50 }).items.map((item) => item.receivedAt);

    expect([...moments].sort((a, b) => b.localeCompare(a))).toEqual(moments);
  });

  it("fiecare rând spune de la cine a venit", () => {
    mockLogin(ADMIN);
    // Rostul ecranului: „de la cine a venit asta și când".
    for (const intake of listIntakes({ pageSize: 20 }).items) {
      expect(intake.sender).toBeTruthy();
      expect(intake.receivedAt).toBeTruthy();
    }
  });

  it("filtrarea pe sursă restrânge lista", () => {
    mockLogin(ADMIN);
    const filtered = listIntakes({ source: "ONEDRIVE", pageSize: 50 });

    expect(filtered.items.every((item) => item.source === "ONEDRIVE")).toBe(true);
  });

  it("încărcările manuale nu sunt recepții", () => {
    mockLogin(ADMIN);
    // Un fișier urcat de un coleg nu a „sosit de la cineva".
    expect(listIntakes({ pageSize: 200 }).items.some((item) => item.source === "UPLOAD")).toBe(
      false,
    );
  });

  it("conținutul intern nu iese", () => {
    mockLogin(ADMIN);
    const item = listIntakes({ pageSize: 1 }).items[0];
    if (!item) return;

    // `rawPayload` poartă căi de stocare și identificatori de provider (§73).
    expect(item).not.toHaveProperty("rawPayload");
    expect(JSON.stringify(item)).not.toContain("organizations/");
  });

  it("un cont dezactivat nu vede nimic", () => {
    // `vizitator@` este dezactivat intenționat în setul sintetic, ca fluxul
    // „cont dezactivat" să existe undeva.
    expect(() => mockLogin("vizitator@contacrm.test")).toThrowError(ApiError);
  });
});
