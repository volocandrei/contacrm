/**
 * Cutiile poștale IMAP, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14). Aici nu există server IMAP, deci
 * nicio cutie nu aduce documente — și demonstrația spune asta, în loc să
 * inventeze un rezultat ca să pară că merge ceva.
 *
 * Ce se poate verifica sunt deciziile, iar prima dintre ele este cea mai
 * importantă: **parola nu iese niciodată înapoi** (§73).
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  addImapMailbox,
  getDocumentSources,
  listImapMailboxes,
  mockLogin,
  removeImapMailbox,
} from "@/api/mock/store";

const ADMIN = "admin@contacrm.test";
/** Cutia poștală a cabinetului este configurare, nu muncă de zi cu zi. */
const ACCOUNTANT = "contabil@contacrm.test";

const PAROLA = "parola-de-aplicatie";

let counter = 0;
function freshMailbox() {
  counter += 1;
  return {
    host: "imap.exemplu.ro",
    username: `cutie${counter}@cabinet.test`,
    password: PAROLA,
    folder: "INBOX",
  };
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("parola", () => {
  it("nu se întoarce niciodată, în niciun răspuns", () => {
    const created = addImapMailbox(freshMailbox());

    expect(JSON.stringify(created)).not.toContain(PAROLA);
    expect(JSON.stringify(listImapMailboxes())).not.toContain(PAROLA);
    // Nici măcar câmpul: un „password": "****" ar sugera că se poate afla.
    expect(JSON.stringify(created)).not.toContain("password");
  });
});

describe("ce refuză", () => {
  it("aceeași cutie și același dosar, de două ori", () => {
    // Ar produce două intake-uri pentru fiecare atașament, adică arhiva dublată.
    const input = freshMailbox();
    addImapMailbox(input);

    expect(() => addImapMailbox(input)).toThrow();
  });

  it("nu lasă contabilul să umble la configurare", () => {
    mockLogin(ACCOUNTANT);

    expect(() => listImapMailboxes()).toThrow();
    expect(() => addImapMailbox(freshMailbox())).toThrow();
  });
});

describe("harta surselor", () => {
  it("drumul IMAP devine „merge acum” odată cu prima cutie", () => {
    // Starea nu se scrie de mână nicăieri: se calculează din cutii, ca pe server.
    const created = addImapMailbox(freshMailbox());
    const row = getDocumentSources().sources.find((item) => item.code === "EMAIL_IMAP")!;

    expect(row.state).toBe("LIVE");
    // „conectat", nu „cutie": la mai multe cutii pluralul este „cutii".
    expect(row.detail).toContain("conectat");

    removeImapMailbox(created.id);
  });

  it("fără nicio cutie, cere una — nu spune că nu există", () => {
    for (const mailbox of listImapMailboxes()) removeImapMailbox(mailbox.id);

    const row = getDocumentSources().sources.find((item) => item.code === "EMAIL_IMAP")!;

    expect(row.state).toBe("NEEDS_SETUP");
    expect(row.requirement).toContain("cutie");
  });
});
