/**
 * Integrarea e-Factura / SPV ANAF pe backendul simulat (M11).
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_anaf_api.py` și `tests/test_anaf_sync.py`.
 *
 * Trei lucruri sunt aceleași în ambele, pentru că fiecare, când lipsește, se
 * manifestă tăcut:
 *
 * - o factură ajunge ca **trei fișiere pe un singur document** — un contabil
 *   vede o factură, nu trei documente;
 * - **un CUI, o singură împuternicire**: două rânduri ar aduce fiecare factură
 *   de două ori și ar dubla cererile către ANAF, care le numără;
 * - **factura ajunge la clientul interogat**, fără nicio ghicire — este singura
 *   sursă din tot sistemul în care atribuirea nu poate greși.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/types";
import {
  addAnafMandate,
  connectAnaf,
  createClient,
  disconnectAnaf,
  getAnafStatus,
  getDocument,
  listDocuments,
  mockLogin,
  removeAnafMandate,
  syncAnaf,
  updateAnafMandate,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** ACCOUNTANT are `documents:approve`, dar nu `admin:settings`. */
const ACCOUNTANT = "contabil@contacrm.test";

beforeEach(() => {
  mockLogin(ADMIN);
  // Starea integrării trăiește în modul: fiecare test pornește neconectat.
  if (getAnafStatus().connected) disconnectAnaf();
});

/** Store-ul ține stare mutabilă între teste; un CUI refolosit s-ar lovi de ea. */
let counter = 0;
function freshClient(name: string) {
  counter += 1;
  return createClient({ name, taxId: `RO8100000${counter}` });
}

describe("acces", () => {
  it("cere `admin:settings`, nu doar o sesiune", () => {
    // Cine autorizează SPV-ul poate citi facturile tuturor clienților.
    mockLogin(ACCOUNTANT);
    expect(() => getAnafStatus()).toThrow(ApiError);
  });
});

describe("autorizarea", () => {
  it("pornește neconectat", () => {
    const status = getAnafStatus();
    expect(status.connected).toBe(false);
    expect(status.mandates).toEqual([]);
  });

  it("autorizarea arată al cui este certificatul", () => {
    const status = connectAnaf("Ioana Marinescu");
    expect(status.connected).toBe(true);
    expect(status.certificateHolder).toBe("Ioana Marinescu");
  });

  it("spune când expiră", () => {
    // ANAF o dă pe un an, iar reînnoirea cere iar certificatul: fără data asta,
    // oprirea preluării s-ar descoperi prin tăcere.
    expect(connectAnaf()).toHaveProperty("expiresAt", expect.any(String));
  });

  it("deconectarea nu lasă împuterniciri în urmă", () => {
    connectAnaf();
    addAnafMandate(freshClient("Alfa E-Factura SRL").id);

    disconnectAnaf();

    expect(getAnafStatus().mandates).toEqual([]);
  });
});

describe("împuterniciri", () => {
  beforeEach(() => {
    connectAnaf();
  });

  it("nu se pot adăuga înainte de autorizare", () => {
    disconnectAnaf();
    const client = freshClient("Prea Devreme SRL");

    expect(() => addAnafMandate(client.id)).toThrowError(ApiError);
  });

  it("CUI-ul se normalizează la forma pe care o cere ANAF", () => {
    const client = freshClient("Cu Prefix SRL");

    // `RO81000001` și `81000001` sunt același cod; API-ul ANAF îl vrea pe al doilea.
    expect(addAnafMandate(client.id).taxId).not.toMatch(/^RO/);
  });

  it("un client fără CUI este refuzat cu motivul", () => {
    const client = createClient({ name: "Fara CUI SRL" });

    expect(() => addAnafMandate(client.id)).toThrowError(/nu are CUI/);
  });

  it("același client nu poate fi adăugat de două ori", () => {
    const client = freshClient("O Singura Data SRL");
    addAnafMandate(client.id);

    expect(() => addAnafMandate(client.id)).toThrowError(ApiError);
  });

  it("oprirea și repornirea șterg eroarea de dinainte", () => {
    const mandate = addAnafMandate(freshClient("Pauza SRL").id);

    updateAnafMandate(mandate.id, false);
    const resumed = updateAnafMandate(mandate.id, true);

    expect(resumed.isActive).toBe(true);
    expect(resumed.lastError).toBeNull();
  });

  it("ștergerea scoate rândul din listă", () => {
    const mandate = addAnafMandate(freshClient("Pleaca SRL").id);

    removeAnafMandate(mandate.id);

    expect(getAnafStatus().mandates.some((row) => row.id === mandate.id)).toBe(false);
  });
});

describe("preluarea", () => {
  beforeEach(() => {
    connectAnaf();
  });

  it("o factură ajunge ca trei fișiere pe un singur document", () => {
    const client = freshClient("Trei Fisiere SRL");
    addAnafMandate(client.id);

    syncAnaf();

    const listed = listDocuments({ source: "EFACTURA", pageSize: 50 }).items.find(
      (document) => document.clientId === client.id,
    );
    expect(listed).toBeDefined();
    // Contractul: `files` este pe document, nu trei documente separate. Lista nu
    // îl poartă — fișierele se văd în fișa documentului, unde se și descarcă.
    const kinds = new Set(getDocument(listed!.id).files.map((file) => file.kind));
    expect(kinds).toEqual(new Set(["original", "anaf_zip", "anaf_pdf"]));
  });

  it("arhiva ANAF este printre ele — este dovada acceptării", () => {
    const client = freshClient("Cu Sigiliu SRL");
    addAnafMandate(client.id);

    syncAnaf();

    const listed = listDocuments({ source: "EFACTURA", pageSize: 50 }).items.find(
      (document) => document.clientId === client.id,
    );
    const seal = getDocument(listed!.id).files.find((file) => file.kind === "anaf_zip");
    expect(seal?.mimeType).toBe("application/zip");
  });

  it("factura ajunge la clientul interogat, nu la altul", () => {
    const client = freshClient("Al Cui SRL");
    addAnafMandate(client.id);

    const result = syncAnaf();

    expect(result.ingested).toBe(1);
    const invoice = listDocuments({ source: "EFACTURA", pageSize: 50 }).items.find(
      (document) => document.clientId === client.id,
    );
    expect(invoice?.clientName).toBe(client.name);
  });

  it("o împuternicire oprită nu este interogată", () => {
    const mandate = addAnafMandate(freshClient("Oprita SRL").id);
    updateAnafMandate(mandate.id, false);

    expect(syncAnaf().ingested).toBe(0);
  });

  it("fără autorizare nu se sincronizează nimic", () => {
    disconnectAnaf();

    expect(() => syncAnaf()).toThrowError(ApiError);
  });
});
