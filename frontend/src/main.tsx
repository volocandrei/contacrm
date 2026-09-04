import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { API_MODE_PROBLEM } from "@/api/client";
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
    </StrictMode>,
  );
}
