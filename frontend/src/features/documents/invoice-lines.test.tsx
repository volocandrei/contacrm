// @vitest-environment jsdom
/**
 * Liniile facturii pe ecran: cotele, și ce se întâmplă când lipsesc (§9).
 *
 * Ce se apără aici nu se poate verifica din date: în bază, o factură cu trei cote
 * și una cu o singură cotă arată la fel — un tabel cu rânduri. Diferența pe care o
 * caută contabilul trăiește numai în ce se randează.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import { InvoiceLines } from "@/features/documents/invoice-lines";
import type { DocumentLine } from "@/types/domain";

afterEach(cleanup);

function line(overrides: Partial<DocumentLine> & { position: number }): DocumentLine {
  return {
    number: String(overrides.position),
    description: "Ceva",
    quantity: "1",
    unitCode: "H87",
    unitPrice: "100.00",
    netAmount: "100.00",
    vatRate: "21",
    vatAmount: null,
    grossAmount: null,
    vatCategory: "S",
    ...overrides,
  };
}

const THREE_RATES: DocumentLine[] = [
  line({ position: 1, description: "Monitor 24 inch", netAmount: "1000.00", vatRate: "21" }),
  line({ position: 2, description: "Manual tipărit", netAmount: "250.00", vatRate: "11" }),
  line({
    position: 3,
    description: "Transport intracomunitar",
    netAmount: "300.00",
    vatRate: "0",
    vatCategory: "AE",
  }),
];

describe("liniile facturii", () => {
  it("arată descrierea și cota fiecărei linii", () => {
    // Exact ce a cerut cabinetul: „TVA-ul pe fiecare produs, și descrierea lui".
    render(<InvoiceLines lines={THREE_RATES} currency="RON" />);

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("Monitor 24 inch")).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/21%/)).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/11%/)).toBeInTheDocument();
  });

  it("adună baza pe fiecare cotă, sus", () => {
    // Numărul pe care îl caută contabilul. Pus la coada unei facturi cu patruzeci
    // de linii, ar fi un total pe care nimeni nu îl vede.
    render(<InvoiceLines lines={THREE_RATES} currency="RON" />);

    expect(screen.getByText(/^21%:/)).toHaveTextContent("1.000");
    expect(screen.getByText(/^11%:/)).toHaveTextContent("250");
  });

  it("explică un zero prin categoria lui", () => {
    // Fără explicație, `0%` arată ca o eroare de citire. La achiziții
    // intracomunitare zero este corect și trebuie să fie zero.
    render(<InvoiceLines lines={THREE_RATES} currency="RON" />);

    expect(screen.getByText("taxare inversă")).toBeInTheDocument();
  });

  it("nu se afișează deloc când documentul nu are linii", () => {
    // Un tabel gol cu „—" pe fiecare coloană ar sugera că documentul chiar nu are
    // linii. Adevărul este altul: nu s-au putut citi (un PDF, nu un XML).
    const { container } = render(<InvoiceLines lines={[]} currency="RON" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("un câmp absent rămâne gol, nu zero", () => {
    render(
      <InvoiceLines
        lines={[line({ position: 1, unitPrice: null, quantity: null, vatRate: null })]}
        currency="RON"
      />,
    );

    const row = screen.getAllByRole("row")[1]!;
    // Trei liniuțe: cantitate, preț unitar, cotă. Niciuna nu este „0".
    expect(within(row).getAllByText("—")).toHaveLength(3);
    expect(within(row).queryByText("0%")).not.toBeInTheDocument();
  });

  it("moneda documentului este cea folosită la sume", () => {
    render(<InvoiceLines lines={THREE_RATES} currency="EUR" />);

    expect(screen.getByText(/^21%:/)).toHaveTextContent("EUR");
  });
});
