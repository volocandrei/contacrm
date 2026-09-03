/**
 * Alegerea backendului nu are voie să fie tăcută într-un build de producție.
 *
 * Implicit era `mock`, oriunde. Un `npm run build` fără `VITE_API_MODE=http` — o
 * variabilă uitată în panoul de deploy — livra aplicația completă rulând pe
 * backendul simulat din browser: clienți inventați, documente inventate, și o
 * autentificare care acceptă orice parolă. Nimic din interfață nu semnala nimic.
 */
import { describe, expect, it } from "vitest";
import { apiModeProblem } from "@/api/client";

describe("modul API", () => {
  it("acceptă o alegere explicită, în orice build", () => {
    for (const production of [true, false]) {
      expect(apiModeProblem("http", production)).toBeNull();
      expect(apiModeProblem("mock", production)).toBeNull();
    }
  });

  it("lasă development-ul să pornească fără configurare", () => {
    expect(apiModeProblem(undefined, false)).toBeNull();
    expect(apiModeProblem("", false)).toBeNull();
  });

  it("refuză un build de producție fără alegere", () => {
    expect(apiModeProblem(undefined, true)).toContain("VITE_API_MODE");
    expect(apiModeProblem("", true)).toContain("VITE_API_MODE");
  });

  it("refuză și o valoare pe care nu o înțelege", () => {
    // `htpp`, `HTTP`, `real` — o greșeală de tastare nu trebuie să cadă tăcut
    // înapoi pe date inventate.
    expect(apiModeProblem("HTTP", true)).toContain("VITE_API_MODE");
    expect(apiModeProblem("real", true)).toContain("VITE_API_MODE");
  });
});
