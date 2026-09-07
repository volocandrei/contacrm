/**
 * Descărcarea unui fișier care cere autentificare.
 *
 * Numerele se vedeau pe ecran și nu puteau ieși din aplicație: un cabinet care
 * trebuie să pună situația lunii într-un raport intern, sau s-o trimită cuiva,
 * le retasta.
 *
 * **Nu este un `<a href>`**: ruta cere autentificare, iar un token în URL este
 * interzis (§27). Se citește cu `fetch`, cu cookie-ul de sesiune la locul lui, și
 * se salvează dintr-un `blob:` — la fel ca descărcarea unui document.
 *
 * Fișierul se cere cu **aceleași filtre** ca ecranul: un export care ar acoperi
 * altceva decât ce se vede ar fi mai rău decât niciunul.
 *
 * Stă aici, nu în ecranul de rapoarte unde s-a născut, fiindcă ecranul de
 * onorarii are nevoie de exact același buton — iar a doua copie s-ar fi despărțit
 * de prima la primul defect reparat într-una din ele.
 */
import { useState } from "react";
import { Download, LoaderCircle } from "lucide-react";
import { apiMode, fetchFile } from "@/api/client";
import { ApiError } from "@/api/types";

export function ExportButton({
  filters,
  path,
  fallbackName,
  label,
  title,
  primary = false,
}: {
  filters: Record<string, string>;
  path: string;
  fallbackName: string;
  label: string;
  title: string;
  primary?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function download() {
    setProblem(null);
    if (apiMode() === "mock") {
      // Fișierul îl compune serverul, din aceleași numere ca ecranul. L-am putea
      // genera aici din ce e deja afișat, dar atunci ar exista două căi de calcul
      // pentru același fișier — exact ce evită ruta.
      setProblem("În modul simulat nu există server care să compună fișierul.");
      return;
    }
    setBusy(true);
    try {
      const query = new URLSearchParams(
        Object.entries(filters).filter(([, value]) => value !== ""),
      ).toString();
      const file = await fetchFile(`${path}${query ? `?${query}` : ""}`);
      const url = URL.createObjectURL(file.blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = file.filename ?? fallbackName;
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        // Revocarea imediată ar putea prinde salvarea înainte să pornească.
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (caught) {
      setProblem(caught instanceof ApiError ? caught.message : "Fișierul nu a putut fi descărcat.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={() => void download()}
        disabled={busy}
        title={title}
        className={
          primary
            ? "flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-3 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:opacity-50"
            : "flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        }
      >
        {busy ? (
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Download className="h-4 w-4" aria-hidden="true" />
        )}
        {label}
      </button>
      {problem && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </div>
  );
}
