// @vitest-environment jsdom
/**
 * Rândul din ecranul de remindere: **de ce**, nu doar **ce**.
 *
 * Pastila spune starea; rândul mic de sub ea spune motivul. Fără al doilea,
 * primul nu se poate verifica: „așteptăm" fără „i-am scris acum două zile" este
 * o afirmație pe care contabilul o poate doar crede. Iar contabilul care nu are
 * cum să verifice de ce tace aplicația începe să scrie el tuturor — adică exact
 * munca pe care ecranul ar fi trebuit s-o scutească.
 *
 * În date, toate stările arată identic: același client, același număr de tipuri
 * lipsă. Diferența trăiește numai în text, deci nu se poate apăra decât randând.
 */
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import { ReminderLine } from "@/features/communication/communication-pages";
import type { ReminderRow } from "@/types/domain";

afterEach(cleanup);

const BASE: ReminderRow = {
  clientId: "c1",
  clientName: "Alfa Conta SRL",
  missingCount: 2,
  status: "DUE",
  lastMessageAt: "2026-09-01T08:00:00Z",
  daysSilent: 5,
  sentCount: 0,
  email: "contact@alfa.test",
  whatsappNumber: "0722 123 456",
};

function show(row: Partial<ReminderRow>) {
  render(
    <MemoryRouter>
      <ul>
        <ReminderLine row={{ ...BASE, ...row }} />
      </ul>
    </MemoryRouter>,
  );
}

describe("motivul de pe rând", () => {
  it("spune de câte zile așteptăm, când asta e explicația", () => {
    show({ status: "WAITING", daysSilent: 2 });

    expect(screen.getByText("așteptăm")).toBeInTheDocument();
    expect(screen.getByText("i-am scris acum 2 zile")).toBeInTheDocument();
  });

  it("nu confundă „nu i s-a cerut” cu „mai așteptăm”", () => {
    // Cele două arată la fel în cifre — niciun mesaj plecat — dar cer lucruri
    // diferite de la om: unul o apăsare acum, celălalt răbdare.
    show({ status: "NOT_ASKED", lastMessageAt: null, daysSilent: null });

    expect(screen.getByText("necerut")).toBeInTheDocument();
    expect(screen.getByText("nu i s-a cerut încă nimic")).toBeInTheDocument();
  });

  it("spune câte remindere au plecat deja, când s-a atins plafonul", () => {
    show({ status: "MAX_REACHED", sentCount: 2 });

    expect(screen.getByText("2 remindere luna asta")).toBeInTheDocument();
  });

  it("trimite la telefon după termen, nu la încă un mesaj", () => {
    show({ status: "PAST_DEADLINE" });

    expect(screen.getByText("termenul a trecut — sună-l")).toBeInTheDocument();
  });

  it("spune ce lipsește de pe fișă, când nu are unde scrie", () => {
    show({ status: "NO_EMAIL", email: null });

    expect(screen.getByText(/fără adresă de email/)).toBeInTheDocument();
    expect(screen.getByText("adaugă un contact cu email pe fișă")).toBeInTheDocument();
  });
});

describe("drumul către client", () => {
  it("normalizează numărul, nu doar îi scoate spațiile", () => {
    // `0722 123 456` curățat de tot ce nu e cifră ar da `wa.me/0722123456` — un
    // număr fără prefix de țară, pe care WhatsApp îl refuză.
    show({});

    expect(screen.getByRole("link", { name: /WhatsApp/ })).toHaveAttribute(
      "href",
      "https://wa.me/40722123456",
    );
  });

  it("rămâne acolo și pentru clientul căruia nu-i putem scrie pe email", () => {
    // Pentru el este singurul drum rămas — de aceea butonul stă pe fiecare rând,
    // nu doar pe cele care primesc un mesaj automat.
    show({ status: "NO_EMAIL", email: null });

    expect(screen.getByRole("link", { name: /WhatsApp/ })).toBeInTheDocument();
  });

  it("nu apare deloc când numărul nu poate fi un telefon", () => {
    // Un interior notat în graba unui apel. Un link stricat este mai rău decât
    // un buton absent: omul apasă o dată și pe urmă nu mai are încredere.
    show({ whatsappNumber: "int. 204" });

    expect(screen.queryByRole("link", { name: /WhatsApp/ })).not.toBeInTheDocument();
  });
});
