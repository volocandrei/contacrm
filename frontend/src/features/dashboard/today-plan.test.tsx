// @vitest-environment jsdom
/**
 * Ce vede cabinetul în strip-ul „Ce ai de făcut".
 *
 * **Proprietatea apărată aici.** Pe o instalare nouă, toate contoarele sunt zero
 * — și tocmai de aceea ecranul spunea „nimic de recuperat, toate documentele
 * sunt procesate, iar clienții au fost întrebați". Despre zero documente și zero
 * clienți. Fals liniștitor exact în minutul în care omul decide dacă aplicația
 * este bună de ceva, și fără niciun drum înainte.
 *
 * Distincția dintre „nimic de recuperat" și „totul de configurat" nu se poate
 * verifica decât randând: în ambele cazuri cifrele sunt identice.
 */
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";

import { TodayPlan } from "@/features/dashboard/dashboard-page";
import type { DashboardKpis } from "@/types/domain";

afterEach(cleanup);

/** O bază complet goală: exact ce vede un cabinet în primul minut. */
const EMPTY: DashboardKpis = {
  clientsTotal: 0,
  clientsActive: 0,
  clientsComplete: 0,
  clientsMissingDocs: 0,
  documentsToday: 0,
  documentsProcessing: 0,
  documentsError: 0,
  documentsNeedReview: 0,
  documentsDuplicate: 0,
  documentsUnmatched: 0,
  clientsNotAsked: 0,
  clientsAwaitingReply: 0,
};

function show(kpis: Partial<DashboardKpis>) {
  return render(
    <MemoryRouter>
      <TodayPlan
        kpis={{ ...EMPTY, ...kpis }}
        closing={null}
        deadlines={{ overdue: 0, soon: 0 }}
      />
    </MemoryRouter>,
  );
}

describe("prima rulare", () => {
  it("un cabinet fără clienți primește pașii, nu felicitări", () => {
    show({});

    expect(screen.getByText(/Aplicația este goală/)).toBeInTheDocument();
    expect(screen.queryByText(/Nimic de recuperat/)).not.toBeInTheDocument();
  });

  it("pașii sunt drumuri, nu text", () => {
    show({});

    // Fără link, sfatul „adaugă primul client" îl lasă pe om să caute singur.
    expect(screen.getByRole("link", { name: /Adaugă primul client/ })).toHaveAttribute(
      "href",
      "/crm/clienti",
    );
    expect(screen.getByRole("link", { name: /profil de client/ })).toHaveAttribute(
      "href",
      "/contabilitate/sabloane",
    );
  });
});

describe("un cabinet care lucrează", () => {
  it("cu clienți și fără restanțe, spune că nu e nimic de recuperat", () => {
    show({ clientsTotal: 6, clientsActive: 4 });

    expect(screen.getByText(/Nimic de recuperat/)).toBeInTheDocument();
    expect(screen.queryByText(/Aplicația este goală/)).not.toBeInTheDocument();
  });

  it("cu treabă de făcut, arată treaba", () => {
    show({ clientsTotal: 6, clientsActive: 4, documentsNeedReview: 3 });

    expect(screen.getByText(/documente de verificat/)).toBeInTheDocument();
    expect(screen.queryByText(/Nimic de recuperat/)).not.toBeInTheDocument();
  });
});
