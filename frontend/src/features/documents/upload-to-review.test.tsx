// @vitest-environment jsdom
/**
 * De la încărcare la ecranul de verificare, pe **configurarea reală** a cache-ului.
 *
 * Testul acesta există pentru un defect pe care suita nu avea cum să-l vadă:
 * fiecare test își făcea propriul `QueryClient`, cu alte valori decât aplicația.
 * Aplicația rulează cu `staleTime` de 30 de secunde, iar mutația de încărcare
 * pune în cache documentul proaspăt urcat — care este `RECEIVED`, cu toate
 * câmpurile goale. Dacă navigarea de pe panoul de încărcare către verificare ar
 * citi acel instantaneu și ar rămâne pe el, operatorul ar privi un formular gol
 * la nesfârșit, în timp ce serverul demult a terminat.
 *
 * Aici se folosește `createQueryClient()`, adică exact ce rulează în browser.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import { createQueryClient } from "@/api/query-client";
import { UploadPanel } from "@/features/documents/upload-panel";
import { ReviewPage } from "@/features/documents/review-page";
import * as store from "@/api/mock/store";

function renderFlow() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/documente/inbox"]}>
        <Routes>
          <Route path="/documente/inbox" element={<UploadPanel />} />
          <Route path="/documente/verificare/:id" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function pdf(name: string): File {
  return new File([new Uint8Array(4096)], name, { type: "application/pdf" });
}

beforeEach(() => {
  store.mockLogin("admin@contacrm.test");
  vi.useRealTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("de la încărcare la verificare", () => {
  it("ecranul se completează singur când procesarea s-a terminat", async () => {
    const user = userEvent.setup();
    renderFlow();

    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await user.upload(input, pdf("factura.pdf"));

    await user.click(await screen.findByRole("link", { name: /deschide/i }));

    // Prima randare arată instantaneul din mutație: `RECEIVED`, câmpuri goale.
    const numberField = await screen.findByLabelText(/^Număr/);
    expect(numberField).toHaveValue("");

    // Serverul simulat termină procesarea; ecranul trebuie să afle singur, prin
    // reinterogarea care rulează cât timp documentul este în lucru.
    vi.setSystemTime(Date.now() + 10_000);

    await waitFor(
      () => {
        expect(screen.getByLabelText(/^Număr/)).not.toHaveValue("");
      },
      { timeout: 10_000 },
    );
  }, 20_000);

  it("documentul deschis direct arată aceleași date", async () => {
    // Drumul fără mutație în mijloc: dacă acesta merge și celălalt nu, vinovat
    // este instantaneul pus în cache, nu extracția.
    const document = store.uploadDocument({
      filename: "directa.pdf",
      size: 4096,
      mimeType: "application/pdf",
    });
    vi.setSystemTime(Date.now() + 10_000);

    render(
      <QueryClientProvider client={createQueryClient()}>
        <MemoryRouter initialEntries={[`/documente/verificare/${document.id}`]}>
          <Routes>
            <Route path="/documente/verificare/:id" element={<ReviewPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/^Număr/)).not.toHaveValue("");
    });
  });
});
