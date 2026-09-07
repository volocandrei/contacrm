/**
 * Reminderele către clienți, pe backendul simulat.
 *
 * Backendul simulat este **contractul** (§14): ce se verifică aici trebuie să se
 * comporte identic în `tests/test_reminders.py`. Regulile de mai jos nu sunt
 * detalii de implementare — sunt promisiunea făcută clienților cabinetului
 * despre cât de des le scrie o aplicație în numele contabilului lor.
 *
 * Ce se apără, în ordinea gravității:
 *
 * 1. **Nu se reamintește ce nu s-a cerut niciodată.**
 * 2. **Cel mult două pe lună**, și nu de două ori în aceeași zi.
 * 3. **Nu celui care tocmai a trimis ceva.**
 * 4. **Citirea ecranului nu trimite nimic** și nu deschide niciun drum public.
 * 5. **Butonul respectă aceleași reguli ca ceasul** — altfel lista de deasupra
 *    ar fi o previzualizare mincinoasă.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { getReminders, listUploadLinks, mockLogin, sendReminders } from "@/api/mock/store";
import type { ReminderRow } from "@/types/domain";

const ADMIN = "admin@contacrm.test";
/** Verificatorul aprobă documente, dar nu scrie clienților. `vizitator@` este
 *  dezactivat intenționat în setul sintetic, deci nici nu se poate autentifica. */
const REVIEWER = "verificator@contacrm.test";

/**
 * Ziua în care se uită testele: chiar ziua termenului.
 *
 * Este ultima zi în care aplicația mai scrie — de mâine se sună. Aleasă fix, nu
 * „azi", pentru că altfel aceleași teste ar fi început să pice după 25 ale lunii
 * următoare, iar picarea n-ar fi spus nimic despre cod.
 */
function today(): Date {
  return new Date(getReminders().deadline ?? new Date().toISOString().slice(0, 10));
}

function rowsByStatus(when: Date = today()): Map<ReminderRow["status"], ReminderRow[]> {
  const grouped = new Map<ReminderRow["status"], ReminderRow[]>();
  for (const row of getReminders(when).rows) {
    grouped.set(row.status, [...(grouped.get(row.status) ?? []), row]);
  }
  return grouped;
}

beforeEach(() => {
  mockLogin(ADMIN);
});

describe("cine primește o reamintire", () => {
  it("arată un motiv pentru fiecare client căruia îi lipsește ceva", () => {
    // Partea utilă a ecranului nu este lista celor care primesc, ci răspunsul la
    // „bine, dar pe ăsta de ce nu-l anunță?".
    const data = getReminders(today());

    expect(data.rows.length).toBeGreaterThan(0);
    for (const row of data.rows) {
      expect(row.status).toBeTruthy();
      expect(row.missingCount).toBeGreaterThan(0);
    }
  });

  it("nu reamintește nimic cui nu i s-a cerut niciodată", () => {
    const notAsked = rowsByStatus().get("NOT_ASKED") ?? [];

    expect(notAsked.length).toBeGreaterThan(0);
    for (const row of notAsked) {
      expect(row.lastMessageAt).toBeNull();
      expect(row.sentCount).toBe(0);
    }
  });

  it("tace pentru cel care a trimis ceva după ultimul mesaj", () => {
    // A trimis ieri jumătate din documente: omul lucrează. Un reminder aici l-ar
    // anunța că nu ne uităm la ce face.
    const answered = rowsByStatus().get("ANSWERED") ?? [];

    expect(answered.length).toBeGreaterThan(0);
  });

  it("se oprește după câte remindere trimite într-o lună", () => {
    const data = getReminders(today());
    const full = data.rows.filter((row) => row.status === "MAX_REACHED");

    expect(full.length).toBeGreaterThan(0);
    for (const row of full) {
      expect(row.sentCount).toBeGreaterThanOrEqual(data.maxPerMonth);
    }
  });
});

describe("ecranul nu trimite", () => {
  it("citirea nu deschide niciun drum public", () => {
    // Fără regula asta, o singură linie mutată ar face ca fiecare reîncărcare de
    // pagină să deschidă un link de trimitere per client.
    const data = getReminders(today());
    const client = data.rows[0]!.clientId;
    const before = listUploadLinks(client).length;

    getReminders(today());
    getReminders(today());

    expect(listUploadLinks(client)).toHaveLength(before);
  });

  it("cine nu are voie să scrie clienților nu vede nici lista", () => {
    mockLogin(REVIEWER);

    expect(() => getReminders()).toThrow();
    expect(() => sendReminders()).toThrow();
  });
});

describe("butonul", () => {
  it("trimite ce era de trimis, și nimic altceva", () => {
    const when = today();
    const before = getReminders(when);
    const due = before.rows.filter((row) => row.status === "DUE").length;

    const report = sendReminders(when);

    expect(report.sent).toBe(due);
    expect(report.skipped).toBe(before.rows.length - due);
  });

  it("apăsat de două ori la rând, a doua oară nu mai trimite nimănui", () => {
    // Ce face cronul repetabil nu este idempotența, ci chiar regula zilelor de
    // tăcere: primul mesaj îl face pe al doilea să nu mai plece.
    const when = today();
    sendReminders(when);

    expect(sendReminders(when).sent).toBe(0);
  });
});
