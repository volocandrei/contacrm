/**
 * Politica de parolă, în browser — și contractul cu serverul.
 *
 * `password.ts` este portul lui `backend/app/domain/passwords.py`. Cele două nu
 * au voie să se despartă în tăcere: dacă browserul acceptă ce serverul refuză,
 * omul apasă și primește o eroare pe care formularul i-o promisese rezolvată;
 * dacă refuză ce serverul acceptă, îi cerem o parolă mai grea degeaba.
 *
 * De aceea cazurile de mai jos sunt **specificația executabilă**, în forma pe
 * care o citește și `backend/tests/test_password_contract.py` — aceleași intrări,
 * același verdict, rulate în amândouă limbajele.
 */
import { describe, expect, it } from "vitest";
import { MIN_DISTINCT, MIN_LENGTH, passwordProblems } from "@/lib/password";

/** Identitatea contului pe care se verifică toate cazurile de mai jos. */
export const IDENTITY = {
  email: "ioana.marinescu@cabinet.ro",
  fullName: "Ioana Marinescu",
};

describe("parole refuzate", () => {
  it("prea scurtă", () => {
    expect(passwordProblems("scurta1234")).not.toHaveLength(0);
  });

  it("o literă repetată", () => {
    expect(passwordProblems("aaaaaaaaaaaa")).not.toHaveLength(0);
  });

  it("un tipar de patru cifre", () => {
    expect(passwordProblems("123412341234")).not.toHaveLength(0);
  });

  it("conține numele contului", () => {
    expect(
      passwordProblems("ioana-marinescu-2026", IDENTITY.email, IDENTITY.fullName),
    ).not.toHaveLength(0);
  });

  it("conține domeniul din adresă", () => {
    expect(
      passwordProblems("parola-cabinet-buna", IDENTITY.email, IDENTITY.fullName),
    ).not.toHaveLength(0);
  });

  it("goală", () => {
    expect(passwordProblems("")).not.toHaveLength(0);
  });
});

describe("parole acceptate", () => {
  it("o frază lungă, fără legătură cu contul", () => {
    expect(
      passwordProblems("trei-mere-verzi-pe-pervaz", IDENTITY.email, IDENTITY.fullName),
    ).toHaveLength(0);
  });

  it("fără majusculă și fără simbol", () => {
    expect(passwordProblems("iarna devreme pe strada")).toHaveLength(0);
  });

  it("o bucată scurtă din nume nu otrăvește tot", () => {
    // `Ion` are trei litere și apare în cuvinte întregi; nu se caută.
    expect(passwordProblems("campionatul-de-iarna", "ion@cabinet.ro", "Ion Vasile")).toHaveLength(
      0,
    );
  });

  it("exact la limita de lungime", () => {
    expect("abcdefghijkl").toHaveLength(MIN_LENGTH);
    expect(passwordProblems("abcdefghijkl")).toHaveLength(0);
  });
});

describe("cum se spun motivele", () => {
  it("toate deodată, nu unul câte unul", () => {
    // Cine repară un motiv și primește următorul încearcă a treia oară degeaba.
    expect(passwordProblems("ioana", IDENTITY.email, IDENTITY.fullName).length).toBeGreaterThan(1);
  });

  it("pragurile sunt cele din server", () => {
    expect(MIN_LENGTH).toBe(12);
    expect(MIN_DISTINCT).toBe(5);
  });
});
