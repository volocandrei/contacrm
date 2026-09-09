import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { API_MODE_PROBLEM, DEMO_WARNING } from "@/api/client";
import { createQueryClient } from "@/api/query-client";
import { AuthProvider } from "@/features/auth/auth-provider";
import "./index.css";
import App from "./App.tsx";

const queryClient = createQueryClient();

const root = createRoot(document.getElementById("root")!);

/**
 * O configurare greșită nu are voie să arate ca o aplicație care merge.
 *
 * Un build de producție fără `VITE_API_MODE` ar porni pe backendul simulat din
 * browser — cu clienți, documente și autentificare inventate — și nimic din
 * interfață nu ar spune asta. Mai bine un ecran care refuză să pornească și
 * explică de ce.
 */
if (API_MODE_PROBLEM) {
  root.render(
    <StrictMode>
      <main className="mx-auto max-w-xl p-8 font-sans">
        <h1 className="mb-3 text-lg font-semibold text-red-700">
          Aplicația nu este configurată
        </h1>
        <p className="text-sm text-slate-700">{API_MODE_PROBLEM}</p>
      </main>
    </StrictMode>,
  );
} else {
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
      {/* Banda stă în afara routerului, deci și peste ecranul de intrare — acolo
          unde „orice parolă merge" costă cel mai mult. Fixată jos: nu mișcă
          nimic din pagină, dar nu poate fi derulată în afara vederii. */}
      {DEMO_WARNING ? (
        <div
          role="status"
          className="fixed inset-x-0 bottom-0 z-50 bg-amber-500 px-4 py-2 text-center text-sm font-semibold text-amber-950 shadow-lg"
        >
          {DEMO_WARNING}
        </div>
      ) : null}
    </StrictMode>,
  );
}
