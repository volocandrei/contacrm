/**
 * Scrierea clienților, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_clients_write.py`. Cele două verificări care
 * contează sunt aceleași în ambele — CUI unic pe forma normalizată și adresă de
 * email unică între clienți — pentru că amândouă, când lipsesc, nu produc nicio
 * eroare: opresc tăcut preluarea automată a documentelor.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import {
  createClient,
  createContact,
  getClient,
  listContacts,
  mockLogin,
  updateClient,
  updateContact,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** OPERATOR are `documents:write`, dar nu `clients:write`. */
const OPERATOR = "operator@contacrm.test";

beforeEach(() => {
  mockLogin(ADMIN);
});

/**
 * Store-ul ține stare mutabilă la nivel de modul și nu se resetează între teste.
 * Un CUI refolosit s-ar lovi de clientul lăsat de testul dinainte, iar eșecul ar
 * arăta ca un defect al verificării de unicitate — când de fapt ea funcționează.
 */
let counter = 0;
function freshTaxId(): string {
  counter += 1;
  return `9000000${counter}`;
}

describe("createClient", () => {
  it("cere doar denumirea", () => {
    const client = createClient({ name: "Client Nou SRL" });
    expect(client.name).toBe("Client Nou SRL");
    // ACTIV, nu PROSPECT: cine adaugă un client îi ține contabilitatea.
    expect(client.status).toBe("ACTIVE");
    expect(getClient(client.id).id).toBe(client.id);
  });

  it("refuză o denumire din spații", () => {
    expect(() => createClient({ name: "   " })).toThrowError(ApiError);
  });

  it.each([
    ["identic", (code: string) => `RO${code}`, (code: string) => `RO${code}`],
    // `RO90000001` și `90000001` sunt același cod. Dacă ar intra amândouă,
    // identificarea automată ar găsi doi candidați și n-ar mai atribui nimic.
    ["cu și fără RO", (code: string) => `RO${code}`, (code: string) => code],
    ["cu spații și puncte", (code: string) => code, (code: string) => `RO ${code}`],
  ])("nu acceptă aceeași firmă de două ori (%s)", (_name, first, second) => {
    const code = freshTaxId();
    createClient({ name: "Prima Intrare SRL", taxId: first(code) });
    expect(() => createClient({ name: "A Doua SRL", taxId: second(code) })).toThrowError(
      /Prima Intrare SRL/,
    );
  });

  it("nu se lovește de propriul CUI la modificare", () => {
    const taxId = freshTaxId();
    const client = createClient({ name: "Se Editează SRL", taxId });
    const saved = updateClient(client.id, { name: "Alt Nume SRL" });
    expect(saved.taxId).toBe(taxId);
  });
});

describe("updateClient", () => {
  it("lasă neatins ce nu se trimite", () => {
    const taxId = freshTaxId();
    const client = createClient({ name: "Complet SRL", taxId, address: "Str. Exemplu 1" });
    const saved = updateClient(client.id, { status: "INACTIVE" });

    expect(saved.status).toBe("INACTIVE");
    expect(saved.taxId).toBe(taxId);
    expect(saved.address).toBe("Str. Exemplu 1");
  });

  it("dezactivarea păstrează clientul", () => {
    const client = createClient({ name: "Pleacă SRL" });
    updateClient(client.id, { status: "INACTIVE" });
    // Nu există ștergere: un client cu documente este istorie contabilă.
    expect(getClient(client.id).status).toBe("INACTIVE");
  });
});

describe("contacte", () => {
  it("normalizează adresa la litere mici", () => {
    const client = createClient({ name: "Cu Contact SRL" });
    const contact = createContact(client.id, {
      fullName: "Maria Ionescu",
      email: "Maria.Ionescu@Exemplu.TEST",
    });
    expect(contact.email).toBe("maria.ionescu@exemplu.test");
  });

  it("nu lasă aceeași adresă la doi clienți", () => {
    const first = createClient({ name: "Primul Client SRL" });
    const second = createClient({ name: "Al Doilea Client SRL" });
    createContact(first.id, { fullName: "Cineva", email: "unic@exemplu.test" });

    expect(() =>
      createContact(second.id, { fullName: "Altcineva", email: "UNIC@exemplu.test" }),
    ).toThrowError(/Primul Client SRL/);
  });

  it("un singur contact principal", () => {
    const client = createClient({ name: "Doi Oameni SRL" });
    const first = createContact(client.id, { fullName: "Primul", isPrimary: true });
    const second = createContact(client.id, { fullName: "Al Doilea", isPrimary: true });

    const stored = listContacts(client.id);
    expect(stored.find((c) => c.id === first.id)?.isPrimary).toBe(false);
    expect(stored.find((c) => c.id === second.id)?.isPrimary).toBe(true);
  });

  it("un contact al altui client nu este accesibil", () => {
    const first = createClient({ name: "Al Lui SRL" });
    const second = createClient({ name: "Al Altuia SRL" });
    const contact = createContact(first.id, { fullName: "Al Lui" });

    expect(() => updateContact(second.id, contact.id, { fullName: "Furat" })).toThrowError(
      ApiError,
    );
  });
});

describe("autorizare", () => {
  it("un operator nu poate adăuga un client", () => {
    mockLogin(OPERATOR);
    // Ascunderea butonului este ergonomie; decizia se ia aici și pe server.
    expect(() => createClient({ name: "Nu Se Poate SRL" })).toThrowError(/permisiunea/);
  });
});
