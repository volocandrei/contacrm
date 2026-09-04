import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { CircleAlert, LoaderCircle, LogIn } from "lucide-react";
import { apiMode } from "@/api/client";
import { ApiError } from "@/api/types";
import { useAuth } from "@/features/auth/use-auth";
import { buttonPrimary, inputField, mutedText, surface } from "@/lib/ui";
import { cn } from "@/lib/utils";

/** Conturi din setul sintetic, ca să poți intra rapid în demonstrație. */
const DEMO_ACCOUNTS = [
  { email: "admin@contacrm.test", label: "Administrator" },
  { email: "contabil@contacrm.test", label: "Contabil" },
  { email: "operator@contacrm.test", label: "Operator" },
  { email: "verificator@contacrm.test", label: "Verificator" },
];

/**
 * Ajutoarele de mai jos se arată **doar** pe backendul simulat.
 *
 * Bannerul „parola nu este verificată" apărea pe orice ecran, inclusiv într-o
 * instalare reală unde parola chiar este verificată — iar câmpul venea completat
 * cu una care acolo nu funcționează. Un ecran de autentificare care minte despre
 * autentificare este primul lucru pe care îl vede un utilizator nou.
 */
const DEMO_MODE = apiMode() === "mock";

export function LoginPage() {
  const { user, login, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState(DEMO_MODE ? "admin@contacrm.test" : "");
  const [password, setPassword] = useState(DEMO_MODE ? "demo" : "");
  const [error, setError] = useState<string | null>(null);

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Autentificarea nu a putut fi finalizată.",
      );
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 p-6 dark:bg-slate-950">
      {/* Două pete de culoare foarte estompate. Ecranul de autentificare era o
          casetă albă pe un gri plat — corect și fără niciun caracter. Nu distrag:
          stau în spate, la 10% opacitate, și nu se mișcă. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 -left-40 h-96 w-96 rounded-full bg-blue-500/10 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-40 -bottom-40 h-96 w-96 rounded-full bg-violet-500/10 blur-3xl"
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid size-12 place-content-center rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 shadow-lg shadow-blue-500/25">
            <svg width="24" viewBox="0 0 50 39" fill="none" className="fill-white" aria-hidden="true">
              <path d="M16.4992 2H37.5808L22.0816 24.9729H1L16.4992 2Z" />
              <path d="M17.4224 27.102L11.4192 36H33.5008L49 13.0271H32.7024L23.2064 27.102H17.4224Z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
              ContaCRM
            </h1>
            <p className={cn("text-xs", mutedText)}>Documentele clienților, la locul lor</p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className={cn(surface, "space-y-4 p-6 shadow-lg shadow-slate-900/5")}
        >
          <div>
            <label
              htmlFor="email"
              className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className={cn(inputField, "h-10 w-full")}
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300"
            >
              Parolă
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className={cn(inputField, "h-10 w-full")}
            />
          </div>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300"
            >
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className={cn(buttonPrimary, "h-10 w-full")}
          >
            {isLoading ? (
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <LogIn className="h-4 w-4" aria-hidden="true" />
            )}
            Intră în cont
          </button>
        </form>

        {DEMO_MODE && (
          <div className="mt-4 rounded-xl border border-dashed border-amber-300 bg-amber-50 p-4 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
            <p className="mb-2 font-medium">
              Demonstrație — backend simulat în browser, parola nu este verificată.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {DEMO_ACCOUNTS.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  onClick={() => setEmail(account.email)}
                  className="rounded-md bg-white px-2 py-1 font-medium text-amber-900 ring-1 ring-amber-200 transition-colors hover:bg-amber-100 dark:bg-slate-900 dark:text-amber-200 dark:ring-amber-800"
                >
                  {account.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
