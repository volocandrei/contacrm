/**
 * Administrarea colegilor, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_users_api.py`.
 *
 * Cel mai important lucru apărat: **nimeni nu se poate încuia singur pe
 * dinafară.** Un cabinet cu un singur administrator care își schimbă din greșeală
 * rolul rămâne afară din propria aplicație, iar remediul devine un terminal și un
 * SQL — exact ce încearcă modulul să nu mai fie necesar.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import {
  createUser,
  listRoles,
  listUsers,
  mockLogin,
  resetUserPassword,
  updateUser,
} from "@/api/mock/store";
import { ROLE_CODE } from "@/types/domain";

const ADMIN = "admin@contacrm.test";
/** ACCOUNTANT are `documents:approve`, dar nu `admin:users`. */
const ACCOUNTANT = "contabil@contacrm.test";

const GOOD_PASSWORD = "parola-noua-de-coleg-2026";

let counter = 0;
function freshEmail(): string {
  counter += 1;
  return `coleg.${counter}.${Date.now()}@contacrm.test`;
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("adăugarea unui coleg", () => {
  it("contul apare în listă", () => {
    const created = createUser({
      email: freshEmail(),
      fullName: "Andrei Popescu",
      role: "OPERATOR",
      password: GOOD_PASSWORD,
    });

    expect(listUsers().some((user) => user.id === created.id)).toBe(true);
    expect(created.isActive).toBe(true);
  });

  it("adresa se păstrează în litere mici", () => {
    // Altfel `Ion@` și `ion@` ar fi două conturi, iar al doilea ar trece de unicitate.
    const created = createUser({
      email: "Coleg.MAJUSCULE@Contacrm.TEST",
      fullName: "Cineva",
      role: "OPERATOR",
      password: GOOD_PASSWORD,
    });

    expect(created.email).toBe("coleg.majuscule@contacrm.test");
  });

  it("aceeași adresă nu poate fi folosită de două ori", () => {
    const email = freshEmail();
    createUser({ email, fullName: "Primul", role: "OPERATOR", password: GOOD_PASSWORD });

    expect(() =>
      createUser({ email, fullName: "Al Doilea", role: "OPERATOR", password: GOOD_PASSWORD }),
    ).toThrowError(ApiError);
  });

  it("o parolă scurtă este refuzată", () => {
    // Același prag ca la `create-admin`: drumul comod nu produce conturi mai slabe.
    expect(() =>
      createUser({
        email: freshEmail(),
        fullName: "Cineva",
        role: "OPERATOR",
        password: "scurta",
      }),
    ).toThrowError(/12 caractere/);
  });

  it("un contabil nu poate adăuga colegi", () => {
    mockLogin(ACCOUNTANT);

    expect(() =>
      createUser({
        email: freshEmail(),
        fullName: "Cineva",
        role: "OPERATOR",
        password: GOOD_PASSWORD,
      }),
    ).toThrowError(/permisiunea/);
  });
});

describe("nimeni nu se încuie singur pe dinafară", () => {
  it("nu te poți dezactiva pe tine", () => {
    const me = listUsers().find((user) => user.email === ADMIN)!;

    expect(() => updateUser(me.id, { isActive: false })).toThrowError(/alt administrator/);
  });

  it("nu îți poți schimba propriul rol", () => {
    const me = listUsers().find((user) => user.email === ADMIN)!;

    expect(() => updateUser(me.id, { role: "VIEWER" })).toThrowError(/alt administrator/);
  });

  it("dar te poți redenumi", () => {
    // Restricția este despre acces, nu despre orice atingere a propriului cont.
    const me = listUsers().find((user) => user.email === ADMIN)!;

    expect(updateUser(me.id, { fullName: "Ioana M. Marinescu" }).fullName).toBe(
      "Ioana M. Marinescu",
    );
  });
});

describe("când cineva pleacă", () => {
  it("contul se dezactivează, nu se șterge", () => {
    // Un utilizator apare în audit ca autor: ștergerea lui ar rupe urma.
    const colleague = createUser({
      email: freshEmail(),
      fullName: "Pleacă",
      role: "OPERATOR",
      password: GOOD_PASSWORD,
    });

    updateUser(colleague.id, { isActive: false });

    const stored = listUsers().find((user) => user.id === colleague.id);
    expect(stored?.isActive).toBe(false);
  });

  it("rolul se poate schimba", () => {
    const colleague = createUser({
      email: freshEmail(),
      fullName: "Promovat",
      role: "OPERATOR",
      password: GOOD_PASSWORD,
    });

    expect(updateUser(colleague.id, { role: "ACCOUNTANT" }).role).toBe("ACCOUNTANT");
  });
});

describe("resetarea parolei", () => {
  it("o parolă scurtă este refuzată și aici", () => {
    const colleague = createUser({
      email: freshEmail(),
      fullName: "Uituc",
      role: "OPERATOR",
      password: GOOD_PASSWORD,
    });

    expect(() => resetUserPassword(colleague.id, "scurta")).toThrowError(/12 caractere/);
  });

  it("un contabil nu resetează parole", () => {
    const colleague = createUser({
      email: freshEmail(),
      fullName: "Cineva",
      role: "OPERATOR",
      password: GOOD_PASSWORD,
    });
    mockLogin(ACCOUNTANT);

    expect(() => resetUserPassword(colleague.id, GOOD_PASSWORD)).toThrowError(/permisiunea/);
  });
});

describe("matricea de roluri", () => {
  it("descrie fiecare rol, în ordinea din vocabular", () => {
    const roles = listRoles();

    expect(roles.map((role) => role.code)).toEqual([...ROLE_CODE]);
    expect(roles.every((role) => role.label.length > 0)).toBe(true);
  });

  it("SUPER_ADMIN le are pe toate, VIEWER doar citește", () => {
    const roles = listRoles();
    const superAdmin = roles.find((role) => role.code === "SUPER_ADMIN")!;
    const viewer = roles.find((role) => role.code === "VIEWER")!;

    expect(superAdmin.permissions).toContain("documents:delete");
    expect(viewer.permissions).toEqual(["clients:read", "documents:read", "tasks:read"]);
    expect(viewer.permissions).not.toContain("documents:write");
  });

  it("cine nu împarte roluri nu citește matricea", () => {
    mockLogin(ACCOUNTANT);

    expect(() => listRoles()).toThrow(ApiError);
  });
});
