// @vitest-environment jsdom
/**
 * Ce spune banda galbenă din capul demonstrației (§24).
 *
 * **Sesizarea care a produs testul:** „nu îmi apare în această listă clientul
 * adăugat de mine mai devreme". Pe backendul real nu s-a putut reproduce —
 * `backend/tests/test_new_client_is_visible.py` cere toate cele nouă liste pe
 * care le cer ecranele, iar clientul nou este în fiecare.
 *
 * Ce s-a întâmplat de fapt: demonstrația rulează pe backendul simulat, care
 * trăiește în memoria filei de browser. O reîncărcare de pagină îl golește, deci
 * clientul chiar dispărea. Aplicația nu pierduse nimic — nu avusese niciodată
 * unde să pună.
 *
 * Banda exista și înainte, dar scria „Mod development — date sintetice". Cine
 * citește asta înțelege „datele de pe ecran sunt inventate" și adaugă liniștit un
 * client. Nimic nu îl avertiza că **ce adaugă el** se pierde.
 *
 * Testul se uită la **text**, fiindcă acolo a fost greșeala: culoarea și poziția
 * n-au înșelat pe nimeni.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import { DemoBanner } from "@/components/layout/demo-banner";

vi.mock("@/api/client", () => ({ apiMode: () => mode }));

let mode: "mock" | "http" = "mock";

afterEach(() => {
  cleanup();
  mode = "mock";
});

describe("banda din modul simulat", () => {
  it("spune că ce adaugi se pierde la reîncărcare", () => {
    render(<DemoBanner />);

    expect(screen.getByRole("status")).toHaveTextContent(/se pierde la reîncărcarea paginii/i);
  });

  it("spune să nu se introducă date reale de client", () => {
    render(<DemoBanner />);

    expect(screen.getByRole("status")).toHaveTextContent(/nu introduce date reale de client/i);
  });

  it("nu se mai mulțumește să numească datele „sintetice”", () => {
    render(<DemoBanner />);

    // Formularea veche descria seed-ul, nu consecința pentru cel care scrie.
    expect(screen.getByRole("status")).not.toHaveTextContent(/date sintetice/i);
  });

  it("este anunțată asistiv, nu doar colorată", () => {
    render(<DemoBanner />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("nu apare pe backendul real, unde datele chiar se păstrează", () => {
    mode = "http";

    render(<DemoBanner />);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
