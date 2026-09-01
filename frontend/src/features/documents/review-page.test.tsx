// @vitest-environment jsdom
/**
 * Ecranul de verificare, pe backendul simulat (§47).
 *
 * Testele trec prin stratul real de API (`hooks` → `endpoints` → `client` → mock),
 * nu prin componente izolate cu date inventate: exact lucrurile care s-au rupt până
 * acum — un buton oferit într-o stare greșită, un câmp care nu se salvează — se văd
 * doar când drumul întreg este parcurs.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import { ReviewPage } from "@/features/documents/review-page";
import * as store from "@/api/mock/store";
import type { DocumentStatus } from "@/types/domain";

function renderReview(documentId: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/documente/verificare/${documentId}`]}>
        <Routes>
          <Route path="/documente/verificare/:id" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * Un document sintetic aflat în starea cerută.
 *
 * `index` există pentru testele care modifică documentul: două teste care iau
 * același rând s-ar influența reciproc prin starea partajată a backendului simulat.
 */
function documentInStatus(status: DocumentStatus, index = 0): string {
  const found = store.listDocuments({ status, pageSize: index + 1 }).items[index];
  if (!found) throw new Error(`Setul sintetic nu are destule documente ${status}.`);
  return found.id;
}

async function openReview(documentId: string) {
  renderReview(documentId);
  // Ecranul este gata când formularul de câmpuri a apărut.
  await screen.findByLabelText(/^Furnizor/);
}

beforeEach(() => {
  store.mockLogin("admin@contacrm.test");
});

afterEach(() => {
  cleanup();
});

describe("ce arată ecranul", () => {
  it("afișează câmpurile extrase cu proveniența lor", async () => {
    await openReview(documentInStatus("REVIEW_REQUIRED"));

    expect(screen.getByLabelText(/^Tip document/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Total/)).toBeInTheDocument();
    // Proveniența fiecărei valori este vizibilă, nu doar valoarea (§22).
    expect(screen.getAllByText(/AI \d+%/).length).toBeGreaterThan(0);
  });

  it("oferă perioada de referință ca selector de lună, nu ca text liber", async () => {
    await openReview(documentInStatus("REVIEW_REQUIRED"));

    // Perioada decide în ce lună contabilă intră documentul: „august" scris de mână
    // nu este o lună.
    expect(screen.getByLabelText(/^Perioadă de referință/)).toHaveAttribute("type", "month");
  });

  it("explică de ce documentul a ajuns la verificare", async () => {
    await openReview(documentInStatus("REVIEW_REQUIRED"));
    expect(screen.getByText("De ce a ajuns la verificare")).toBeInTheDocument();
  });
});

describe("acțiunile pe care le oferă", () => {
  it("un document în verificare poate fi aprobat, respins sau marcat duplicat", async () => {
    await openReview(documentInStatus("REVIEW_REQUIRED"));

    expect(screen.getByRole("button", { name: /Aprobă/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Respinge/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Duplicat/ })).toBeInTheDocument();
  });

  it("un document deja aprobat nu mai poate fi aprobat o dată", async () => {
    await openReview(documentInStatus("APPROVED"));
    expect(screen.queryByRole("button", { name: /Aprobă/ })).not.toBeInTheDocument();
  });

  it("un document arhivat nu se poate decât reprocesa", async () => {
    await openReview(documentInStatus("ARCHIVED"));

    expect(screen.getByRole("button", { name: /Reprocesează/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aprobă/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Respinge/ })).not.toBeInTheDocument();
  });

  it("un operator fără drept de aprobare nu vede nici aprobarea, nici respingerea", async () => {
    store.mockLogin("operator@contacrm.test");
    await openReview(documentInStatus("REVIEW_REQUIRED"));

    expect(screen.queryByRole("button", { name: /Aprobă/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Respinge/ })).not.toBeInTheDocument();
    // Dar poate corecta câmpurile și marca duplicatele — asta e munca lui.
    expect(screen.getByRole("button", { name: /Salvează/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Duplicat/ })).toBeInTheDocument();
  });
});

describe("corectarea datelor", () => {
  it("salvează valoarea corectată și o marchează ca provenind de la om", async () => {
    const user = userEvent.setup();
    const documentId = documentInStatus("REVIEW_REQUIRED");
    await openReview(documentId);

    const supplier = screen.getByLabelText(/^Furnizor/);
    await user.clear(supplier);
    await user.type(supplier, "Furnizor Corectat Șerbănescu SRL");
    await user.click(screen.getByRole("button", { name: /Salvează/ }));

    await screen.findByText("Modificările au fost salvate.");
    expect(store.getDocument(documentId).fields.supplierName).toMatchObject({
      value: "Furnizor Corectat Șerbănescu SRL",
      source: "MANUAL",
      confidence: null,
    });
  });

  it("butonul de salvare rămâne inactiv cât timp nimic nu s-a schimbat", async () => {
    await openReview(documentInStatus("REVIEW_REQUIRED"));
    expect(screen.getByRole("button", { name: /Salvează/ })).toBeDisabled();
  });
});

describe("aprobarea", () => {
  it("nu se oferă cât timp documentul nu are client", async () => {
    const documentId = documentInStatus("UNMATCHED");
    await openReview(documentId);

    const approve = screen.queryByRole("button", { name: /Aprobă/ });
    // Din `UNMATCHED` aprobarea nici nu este o tranziție permisă.
    expect(approve).not.toBeInTheDocument();
    expect(screen.getByText("Atribuie client")).toBeInTheDocument();
  });

  it("enumeră ce mai lipsește când documentul nu e gata", async () => {
    // Al doilea document: testul îi golește un câmp, iar celelalte teste nu trebuie
    // să găsească un document mutilat de acesta.
    const documentId = documentInStatus("REVIEW_REQUIRED", 1);
    // Golim un câmp obligatoriu pe calea normală, ca serverul simulat să recalculeze.
    store.updateDocumentFields(documentId, [{ field: "totalAmount", value: null }]);

    await openReview(documentId);

    const approve = screen.getByRole("button", { name: /Aprobă/ });
    expect(approve).toBeDisabled();
    expect(screen.getByText(/Câmpuri obligatorii lipsă/)).toBeInTheDocument();
  });

  it("trimite documentul mai departe când totul este complet", async () => {
    const user = userEvent.setup();
    const documentId = documentInStatus("REVIEW_REQUIRED");
    await openReview(documentId);

    await user.click(screen.getByRole("button", { name: /Aprobă/ }));
    await screen.findByText("Document aprobat și arhivat.");

    // Aprobarea și arhivarea sunt un singur act, în ambele backend-uri: un document
    // aprobat care nu a ajuns în arhivă nu este nicăieri (§10, §11).
    const approved = store.getDocument(documentId);
    expect(approved.status).toBe("ARCHIVED");
    expect(approved.reviewRequired).toBe(false);
    expect(approved.storedFilename).toMatch(/.pdf$|.jpg$/);
    expect(approved.history.at(-1)).toMatchObject({ action: "DOCUMENT_APPROVED" });
  });
});

describe("respingerea", () => {
  it("cere un motiv înainte de a fi confirmată", async () => {
    const user = userEvent.setup();
    const documentId = documentInStatus("REVIEW_REQUIRED");
    await openReview(documentId);

    await user.click(screen.getByRole("button", { name: /Respinge/ }));
    const confirm = screen.getByRole("button", { name: /Confirmă respingerea/ });
    // Un document respins fără motiv nu poate fi corectat de nimeni.
    expect(confirm).toBeDisabled();

    await user.type(screen.getByLabelText(/Motivul respingerii/), "Document ilizibil.");
    expect(confirm).toBeEnabled();

    await user.click(confirm);
    await screen.findByText("Document respins.");
    expect(store.getDocument(documentId).status).toBe("REJECTED");
  });
});

describe("istoricul", () => {
  it("arată ce s-a întâmplat cu documentul, cu autor și moment", async () => {
    const documentId = documentInStatus("REVIEW_REQUIRED");
    await openReview(documentId);

    const history = screen.getByText("Istoric").closest("section") ?? document.body;
    await waitFor(() => {
      expect(within(history).getByText("DOCUMENT_RECEIVED")).toBeInTheDocument();
    });
  });
});

describe("reprocesarea", () => {
  it("anunță că documentul este în lucru și că ecranul se actualizează singur", async () => {
    await openReview(documentInStatus("PROCESSING"));
    expect(screen.getByText(/Documentul este în procesare/)).toBeInTheDocument();
  });

  it("nu se oferă după ce încercările s-au epuizat, dar spune de ce", async () => {
    const documentId = documentInStatus("ERROR");
    // Un document care a eșuat de trei ori nu se repară a patra oară.
    store.getDocument(documentId).processingAttempts = 3;

    await openReview(documentId);

    expect(screen.queryByRole("button", { name: /Reproceseaz/ })).not.toBeInTheDocument();
    expect(screen.getByText(/limita configurată a fost atinsă/)).toBeInTheDocument();
  });

  it("arată motivul eșecului, nu doar faptul că a eșuat", async () => {
    await openReview(documentInStatus("ERROR", 1));
    expect(screen.getByText("Procesarea a eșuat")).toBeInTheDocument();
    expect(screen.getByText(/Recunoașterea textului a eșuat/)).toBeInTheDocument();
  });
});

describe("documentele arhivate", () => {
  it("nu se mai pot corecta, iar ecranul spune de ce", async () => {
    await openReview(documentInStatus("ARCHIVED"));

    expect(screen.getByLabelText(/^Furnizor/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Salvează/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Cere o reprocesare dacă trebuie corectate/)).toBeInTheDocument();
  });

  it("nu oferă atribuirea clientului", async () => {
    await openReview(documentInStatus("ARCHIVED"));
    expect(screen.queryByText("Atribuie client")).not.toBeInTheDocument();
  });
});
