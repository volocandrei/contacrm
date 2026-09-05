/**
 * Solicitarea de documente, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_document_request.py`.
 *
 * Ce se apără, în ordinea gravității:
 *
 * 1. **Cererea și drumul pleacă împreună.** O listă cu ce lipsește îi spune
 *    clientului *ce* să caute și îl lasă singur cu *cum* trimite. Asta e toată
 *    ideea funcției.
 * 2. **Nu se deschide un drum degeaba** — dacă nu lipsește nimic, nu se creează
 *    nimic.
 * 3. **Cel care aleargă după documente poate**: gardul este `documents:write`,
 *    nu `clients:write`, pe care îl are numai administratorul.
 * 4. **Asistentul propune, nu deschide.**
 *
 * Starea backendului simulat trăiește în modul, deci testele de aici numără
 * relativ — câte linkuri s-au adăugat —, nu absolut.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { clients } from "@/api/endpoints";
import {
  assistantAnswer,
  composeDocumentRequest,
  createUploadLink,
  listMissingDocuments,
  listUploadLinks,
  mockLogin,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** Contabilul are `documents:write`, nu `clients:write`. El cere documentele. */
const ACCOUNTANT = "contabil@contacrm.test";

/** O lună începută și neterminată, luată din datele sintetice, nu inventată. */
function aClientWithGaps(): { clientId: string; referenceMonth: string } {
  for (const referenceMonth of ["2026-08", "2026-07", "2026-06"]) {
    const entry = listMissingDocuments(referenceMonth)[0];
    if (entry) return { clientId: entry.period.clientId, referenceMonth };
  }
  throw new Error("setul sintetic nu are nicio lună cu documente lipsă");
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("cererea de documente", () => {
  it("poartă drumul pe care sosește răspunsul", () => {
    const { clientId, referenceMonth } = aClientWithGaps();

    const request = composeDocumentRequest(clientId, referenceMonth);

    expect(request.uploadUrl).toContain("/incarca/");
    expect(request.message).toContain(request.uploadUrl);
    // Și până când merge: altfel clientul care încearcă peste patru luni nu
    // află de ce nu mai merge, iar contabilul nu-și amintește când l-a deschis.
    expect(request.message).toContain("valabil până la");
  });

  it("listează ce lipsește, ca listă, nu ca propoziție", () => {
    const { clientId, referenceMonth } = aClientWithGaps();

    const { message } = composeDocumentRequest(clientId, referenceMonth);

    expect(message.startsWith("Bună ziua,")).toBe(true);
    expect(message).toContain("•");
  });

  it("deschide un link, care apare apoi în fișa clientului", () => {
    const { clientId, referenceMonth } = aClientWithGaps();
    const before = listUploadLinks(clientId).length;

    composeDocumentRequest(clientId, referenceMonth);

    expect(listUploadLinks(clientId)).toHaveLength(before + 1);
  });

  it("nu deschide nimic când nu e nimic de cerut", () => {
    const { clientId } = aClientWithGaps();
    const complete = ["2026-08", "2026-07", "2026-06", "2026-05"].find(
      (month) => !listMissingDocuments(month).some((entry) => entry.period.clientId === clientId),
    );
    expect(complete).toBeDefined();
    const before = listUploadLinks(clientId).length;

    expect(() => composeDocumentRequest(clientId, complete!)).toThrow();
    expect(listUploadLinks(clientId)).toHaveLength(before);
  });

  it("îl lasă pe contabil să ceară documentele", () => {
    // Negativul — cine doar citește nu poate — stă în `test_document_request.py`:
    // singurul rol fără `documents:write` este VIEWER, iar contul acela este
    // dezactivat în setul sintetic, deliberat, ca fluxul „cont dezactivat" să
    // existe undeva.
    const { clientId, referenceMonth } = aClientWithGaps();
    mockLogin(ACCOUNTANT);

    expect(() => composeDocumentRequest(clientId, referenceMonth)).not.toThrow();
  });
});

describe("drumul întreg, prin clientul de API", () => {
  it("ruta există în backendul simulat, cu tot cu interogarea ei", async () => {
    // Testele de mai sus cheamă magazinul direct și nu ating ruterul. Ăsta trece
    // prin clientul de API, ca ecranul: interogarea merge prin `params`, fiindcă
    // lipită în cale n-ar mai potrivi niciun tipar — un 404 care s-ar fi văzut
    // abia în demo, unde modul simulat este singurul care rulează.
    const { clientId, referenceMonth } = aClientWithGaps();

    const request = await clients.documentRequest(clientId, referenceMonth);

    expect(request.uploadUrl).toContain("/incarca/");
    expect(request.message).toContain(request.uploadUrl);
  });
});

describe("urma cererii", () => {
  /** Un client cu goluri pe care nu l-a întrebat încă nimeni, în luna dată. */
  function untouched(referenceMonth: string) {
    const entry = listMissingDocuments(referenceMonth).find((row) => row.requestedAt === null);
    expect(entry, "setul sintetic nu mai are niciun client neîntrebat").toBeDefined();
    return entry!.period.clientId;
  }

  function traceOf(clientId: string, referenceMonth: string) {
    return listMissingDocuments(referenceMonth).find((row) => row.period.clientId === clientId)!;
  }

  it("spune cui nu i s-a cerut încă, și își amintește după aceea", () => {
    // Fără urmă pe ecran, un cabinet cu treizeci de clienți cere de două ori
    // unuia și îl uită complet pe altul. Uitatul nu costă timp, costă o lună.
    const month = "2026-08";
    const clientId = untouched(month);

    composeDocumentRequest(clientId, month);

    expect(traceOf(clientId, month).requestedAt).not.toBeNull();
  });

  it("un link deschis din fișă nu este o cerere", () => {
    // Dacă ar conta, ecranul ar spune „i s-a cerut" despre un client pe care
    // nu l-a întrebat nimeni — exact clientul care așteaptă degeaba.
    const month = "2026-08";
    const clientId = untouched(month);

    createUploadLink(clientId);

    expect(traceOf(clientId, month).requestedAt).toBeNull();
  });
});

describe("asistentul", () => {
  it("pregătește cererea, dar nu deschide el drumul", () => {
    const reply = assistantAnswer("scrie solicitarea pentru Alfa");

    expect(reply.used).toEqual(["draft_request"]);
    // Textul nu poartă niciun link: deschiderea scrie, iar asistentul nu scrie.
    expect(reply.text).not.toContain("/incarca/");
    for (const action of reply.actions) {
      expect(action.kind).toBe("request_documents");
    }
  });
});
