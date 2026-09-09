/**
 * Alegerea backendului nu are voie să fie tăcută într-un build de producție.
 *
 * Implicit era `mock`, oriunde. Un `npm run build` fără `VITE_API_MODE=http` — o
 * variabilă uitată în panoul de deploy — livra aplicația completă rulând pe
 * backendul simulat din browser: clienți inventați, documente inventate, și o
 * autentificare care acceptă orice parolă. Nimic din interfață nu semnala nimic.
 */
import { describe, expect, it } from "vitest";
import { apiModeProblem, demoWarning } from "@/api/client";

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

/**
 * Cazul pe care `apiModeProblem` nu îl prinde: modul simulat cerut **explicit**
 * într-un build de producție. Nu este o configurare greșită — o demonstrație
 * este o folosință legitimă — dar arată identic cu aplicația adevărată și
 * acceptă orice parolă. Singurul lucru care lipsea era să o spună.
 */
describe("avertismentul de demonstrație", () => {
  it("apare într-un build de producție pe date inventate", () => {
    const warning = demoWarning("mock", true);
    expect(warning).not.toBeNull();
    // Cele două lucruri pentru care banda există: datele și parola.
    expect(warning).toContain("inventate");
    expect(warning).toContain("parolă");
  });

  it("nu apare când aplicația vorbește cu API-ul real", () => {
    // Contra-proba. Fără ea, banda ar putea fi lipită pe orice build — iar un
    // avertisment care apare mereu nu mai avertizează despre nimic.
    expect(demoWarning("http", true)).toBeNull();
  });

  it("nu deranjează development-ul", () => {
    // Acolo modul simulat este chiar rostul lui, iar dezvoltatorul știe.
    expect(demoWarning("mock", false)).toBeNull();
    expect(demoWarning(undefined, false)).toBeNull();
  });

  it("tace și când modul lipsește, fiindcă atunci refuză deja pornirea", () => {
    // Două mesaje despre aceeași problemă ar fi însemnat ca niciunul să nu fie
    // citit; `apiModeProblem` oprește build-ul acela înainte de orice ecran.
    expect(demoWarning(undefined, true)).toBeNull();
  });
});
