// @vitest-environment jsdom
/**
 * Panoul de încărcare, prin stratul real de API (§47).
 *
 * Ce contează aici nu este că butonul se randează, ci ce vede operatorul după ce
 * a lăsat un teanc de fișiere: care au intrat, care nu, și **de ce** nu. Un lot
 * în care al treilea fișier e respins nu are voie să ascundă că primele două au
 * ajuns — asta este proprietatea pe care o apără testele de mai jos.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import { UploadPanel } from "@/features/documents/upload-panel";
import * as store from "@/api/mock/store";

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <UploadPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function pdf(name: string, bytes = 2048): File {
  return new File([new Uint8Array(bytes)], name, { type: "application/pdf" });
}

/** Câmpul de fișiere este ascuns vizual, dar este cel pe care îl apasă eticheta. */
function fileInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Panoul nu are câmp de fișiere.");
  return input;
}

async function results() {
  return within(await screen.findByRole("list", { name: /încărcărilor/i })).getAllByRole(
    "listitem",
  );
}

beforeEach(() => {
  store.mockLogin("admin@contacrm.test");
});

afterEach(() => {
  cleanup();
});

describe("încărcarea", () => {
  it("acceptă mai multe fișiere deodată și le raportează pe fiecare", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.upload(fileInput(), [pdf("prima.pdf"), pdf("a-doua.pdf")]);

    await waitFor(async () => expect(await results()).toHaveLength(2));
    expect(screen.getByText("prima.pdf")).toBeInTheDocument();
    expect(screen.getByText("a-doua.pdf")).toBeInTheDocument();
  });

  it("duce la documentul creat, ca operatorul să nu-l caute în listă", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.upload(fileInput(), pdf("factura.pdf"));

    const link = await screen.findByRole("link", { name: /deschide/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/documente/verificare/"));
  });

  it("documentul chiar ajunge în sistem, nu doar pe ecran", async () => {
    const user = userEvent.setup();
    renderPanel();
    const before = store.listDocuments({ pageSize: 1 }).total;

    await user.upload(fileInput(), pdf("intrata.pdf"));

    await screen.findByRole("link", { name: /deschide/i });
    expect(store.listDocuments({ pageSize: 1 }).total).toBe(before + 1);
  });
});

describe("când serverul refuză", () => {
  it("arată motivul concret, nu „a eșuat”", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.upload(
      fileInput(),
      new File([new Uint8Array(16)], "raport.docx", { type: "application/msword" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/tip de fișier neacceptat/i);
  });

  it("un eșec în mijlocul lotului nu ascunde reușitele din jur", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.upload(fileInput(), [
      pdf("buna.pdf"),
      new File([new Uint8Array(16)], "rea.txt", { type: "text/plain" }),
      pdf("si-buna.pdf"),
    ]);

    await waitFor(async () => expect(await results()).toHaveLength(3));
    await waitFor(() =>
      expect(screen.getAllByRole("link", { name: /deschide/i })).toHaveLength(2),
    );
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });
});

describe("clientul", () => {
  it("implicit se identifică automat — nu îl alegem noi în locul sistemului", () => {
    renderPanel();
    expect(screen.getByRole("combobox")).toHaveValue("");
    expect(screen.getByRole("option", { name: /identifică automat/i })).toBeInTheDocument();
  });
});
