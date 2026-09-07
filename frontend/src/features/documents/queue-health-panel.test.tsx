// @vitest-environment jsdom
/**
 * Panoul stării cozii (§7, §36).
 *
 * Ce contează aici nu este că se randează cifrele, ci **ce citește cineva care a
 * deschis ecranul îngrijorat**. Trei proprietăți, în ordinea în care greșeala
 * costă:
 *
 * 1. o coadă blocată se citește ca blocată, nu ca „procesarea lucrează";
 * 2. o coadă în lucru nu alarmează degeaba — altfel panoul se ignoră până când
 *    nu mai contează;
 * 3. când starea nu s-a putut citi, panoul o spune. Ascuns la eroare, ar fi
 *    arătat identic cu o coadă sănătoasă, adică opusul rostului lui.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import { QueueHealthPanel } from "@/features/documents/queue-health-panel";
import type { QueueHealth } from "@/types/domain";
import * as hooks from "@/api/hooks";

const EMPTY: QueueHealth = {
  queued: 0,
  running: 0,
  stuck: 0,
  failedRecently: 0,
  waitingSeconds: null,
  recentFailures: [],
};

type HealthQuery = ReturnType<typeof hooks.useProcessingHealth>;

function show(data: QueueHealth | undefined, { isError = false } = {}) {
  vi.spyOn(hooks, "useProcessingHealth").mockReturnValue({
    data,
    isLoading: false,
    isError,
  } as HealthQuery);

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <QueueHealthPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("verdictul", () => {
  it("o coadă goală o spune, fără să pară o problemă", () => {
    show(EMPTY);

    expect(screen.getByText(/Coada este goală/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("o coadă în lucru nu alarmează", () => {
    // Treizeci de cereri într-o dimineață aglomerată sunt normale.
    show({ ...EMPTY, queued: 30, running: 2, waitingSeconds: 45 });

    expect(screen.getByText(/Procesarea lucrează/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("o cerere care așteaptă de prea mult spune că procesarea nu rulează", () => {
    // Motivul pentru care există panoul: cifra care contează nu este câte sunt
    // în coadă, ci de când așteaptă cea mai veche.
    show({ ...EMPTY, queued: 1, waitingSeconds: 40 * 60 });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/40 de minute/);
    expect(alert).toHaveTextContent(/nu rulează/);
  });

  it("numeralul respectă românește: „3 minute”, nu „3 de minute”", () => {
    // Pare un moft până când panoul scrie „3 de minute” pe un ecran citit de un
    // contabil: atunci verdictul se citește ca scris de o mașină, exact când are
    // nevoie să fie crezut.
    show({ ...EMPTY, queued: 1, waitingSeconds: 18 * 60 + 30 });

    expect(screen.getByText(/18 minute/)).toBeInTheDocument();
  });

  it("ceva blocat câștigă asupra unei cozi care pare să lucreze", () => {
    // Gravitatea, nu ordinea cifrelor: un job rămas pornit și neterminat este
    // mai rău decât o coadă lentă, iar „procesarea lucrează" l-ar fi ascuns.
    show({ ...EMPTY, queued: 3, running: 1, stuck: 1, waitingSeconds: 10 });

    expect(screen.getByRole("alert")).toHaveTextContent(/rămas/);
  });

  it("eșecurile recente se spun chiar și cu coada goală", () => {
    show({ ...EMPTY, failedRecently: 2 });

    // Verdictul, nu eticheta cifrei: „eșecuri recente" apare în amândouă.
    expect(screen.getByText(/Coada este goală, dar au fost eșecuri recente/)).toBeInTheDocument();
  });
});

describe("eșecurile", () => {
  it("arată fișierul, clientul și motivul scris în cuvinte", () => {
    show({
      ...EMPTY,
      failedRecently: 1,
      recentFailures: [
        {
          documentId: "doc-1",
          originalFilename: "factura-alfa.pdf",
          clientName: "Alfa Conta SRL",
          errorCode: "EXTRACTION_FAILED",
          errorDetail: "Extragerea datelor a eșuat.",
          attempt: 2,
          finishedAt: "2026-09-08T09:00:00Z",
        },
      ],
    });

    // Un cod gol — „EXTRACTION_FAILED" — nu spune nimănui ce să facă mai departe.
    expect(screen.getByText("Extragerea datelor a eșuat.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "factura-alfa.pdf" })).toHaveAttribute(
      "href",
      "/documente/verificare/doc-1",
    );
    expect(screen.getByText(/Alfa Conta SRL/)).toBeInTheDocument();
  });
});

describe("când nu se poate citi", () => {
  it("spune că nu știe, în loc să tacă", () => {
    show(undefined, { isError: true });

    expect(screen.getByRole("alert")).toHaveTextContent(/nu înseamnă că procesarea merge/);
  });
});
