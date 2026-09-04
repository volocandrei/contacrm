/**
 * Agenda, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_contacts_api.py`.
 */
import { describe, expect, it } from "vitest";
import { listAllContacts, mockLogin } from "@/api/mock/store";

mockLogin("admin@contacrm.test");

describe("agenda cabinetului", () => {
  it("aduce contacte din firme diferite, dintr-o singură chemare", () => {
    const page = listAllContacts({ pageSize: 100 });

    expect(page.items.length).toBeGreaterThan(0);
    expect(new Set(page.items.map((contact) => contact.clientName)).size).toBeGreaterThan(1);
    expect(page.items.every((contact) => contact.clientName.length > 0)).toBe(true);
  });

  it("contactul principal stă primul în firma lui", () => {
    const page = listAllContacts({ pageSize: 100 });
    const firm = page.items[0]!.clientName;
    const sameFirm = page.items.filter((contact) => contact.clientName === firm);

    if (sameFirm.some((contact) => contact.isPrimary)) {
      expect(sameFirm[0]!.isPrimary).toBe(true);
    }
  });

  it("căutarea prinde și persoana, și firma", () => {
    const all = listAllContacts({ pageSize: 100 });
    const person = all.items[0]!;

    const byPerson = listAllContacts({ q: person.fullName, pageSize: 100 });
    const byFirm = listAllContacts({ q: person.clientName, pageSize: 100 });

    expect(byPerson.items.map((c) => c.id)).toContain(person.id);
    expect(byFirm.items.map((c) => c.id)).toContain(person.id);
  });

  it("cine a plecat din firmă nu se propune", () => {
    const active = listAllContacts({ pageSize: 200 });
    const everyone = listAllContacts({ pageSize: 200, includeInactive: true });

    expect(active.items.every((contact) => contact.isActive)).toBe(true);
    expect(everyone.total).toBeGreaterThanOrEqual(active.total);
  });
});
