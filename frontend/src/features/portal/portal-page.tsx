/**
 * Pagina pe care o deschide clientul cabinetului.
 *
 * **Cine ajunge aici.** Cineva care nu are cont, nu vrea unul, și probabil
 * deschide linkul de pe telefon, în cinci minute libere. Fiecare pas cerut în
 * plus înseamnă o lună întârziată pentru cabinet.
 *
 * De aceea pagina nu are: meniu, autentificare, teme, setări, explicații lungi.
 * Are un titlu, o zonă în care se trag fișiere, și o listă cu ce a plecat.
 *
 * **Ce nu scrie pe ea, deliberat.** Numele clientului. Un link ajuns din greșeală
 * la altcineva n-are voie să spună cine este clientul cabinetului — de aceea
 * serverul nici nu îl trimite. Se vede numele cabinetului, ca omul să știe cui
 * trimite.
 *
 * **Ce nu poate face.** Nu poate citi nimic: nu vede ce s-a trimis înainte, nu
 * descarcă. Doar adaugă.
 */
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { CircleCheck, CloudUpload, LoaderCircle, TriangleAlert } from "lucide-react";
import { api } from "@/api/client";
import { ApiError } from "@/api/types";

type PortalInfo = {
  organizationName: string;
  maxFileSizeMb: number;
  acceptedTypes: string[];
};

type Sent = {
  id: number;
  name: string;
  state: "sending" | "done" | "failed";
  message?: string;
};

export function PortalPage() {
  const { token = "" } = useParams<{ token: string }>();
  const [info, setInfo] = useState<PortalInfo | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [sent, setSent] = useState<Sent[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const counter = useRef(0);

  useEffect(() => {
    let alive = true;
    api
      .get<PortalInfo>(`/portal/${encodeURIComponent(token)}`)
      .then((data) => alive && setInfo(data))
      .catch(() =>
        alive &&
        setProblem(
          "Linkul nu mai este valabil. Cere-i cabinetului unul nou — cel vechi poate să fi expirat.",
        ),
      );
    return () => {
      alive = false;
    };
  }, [token]);

  async function send(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) {
      counter.current += 1;
      const id = counter.current;
      setSent((current) => [...current, { id, name: file.name, state: "sending" }]);

      try {
        const reply = await api.upload<{ message: string }>(
          `/portal/${encodeURIComponent(token)}`,
          file,
        );
        setSent((current) =>
          current.map((row) =>
            row.id === id ? { ...row, state: "done", message: reply.message } : row,
          ),
        );
      } catch (caught) {
        // Motivul se spune. Un „nu a mers" fără cauză îl face pe om să
        // reîncerce același fișier de trei ori.
        const message =
          caught instanceof ApiError
            ? caught.message
            : "Nu s-a putut trimite. Încearcă din nou.";
        setSent((current) =>
          current.map((row) => (row.id === id ? { ...row, state: "failed", message } : row)),
        );
      }
    }
  }

  if (problem) {
    return (
      <Shell>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center">
          <TriangleAlert className="mx-auto mb-3 h-8 w-8 text-amber-600" aria-hidden="true" />
          <p className="text-sm text-amber-900">{problem}</p>
        </div>
      </Shell>
    );
  }

  if (!info) {
    return (
      <Shell>
        <p className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          Se încarcă…
        </p>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Trimite documentele
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          către <strong>{info.organizationName}</strong>
        </p>
      </div>

      {/* Zona de tras fișiere. Și un buton, pentru cine e pe telefon și n-are
          ce să tragă. */}
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void send(event.dataTransfer.files);
        }}
        className={`rounded-2xl border-2 border-dashed p-10 text-center transition-colors ${
          dragging ? "border-blue-400 bg-blue-50" : "border-slate-300 bg-white"
        }`}
      >
        <CloudUpload className="mx-auto mb-3 h-10 w-10 text-slate-400" aria-hidden="true" />
        <p className="mb-4 text-sm text-slate-600">
          Trage fișierele aici, sau alege-le de pe dispozitiv.
        </p>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="h-11 rounded-xl bg-blue-600 px-6 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          Alege fișiere
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          aria-label="Alege fișierele de trimis"
          onChange={(event) => void send(event.target.files)}
          className="hidden"
        />
        <p className="mt-4 text-xs text-slate-500">
          Până la {info.maxFileSizeMb} MB per fișier. PDF, imagini sau XML.
        </p>
      </div>

      {sent.length > 0 && (
        <ul className="mt-6 space-y-2">
          {sent.map((row) => (
            <li
              key={row.id}
              className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm"
            >
              {row.state === "sending" && (
                <LoaderCircle
                  className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-slate-400"
                  aria-hidden="true"
                />
              )}
              {row.state === "done" && (
                <CircleCheck
                  className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600"
                  aria-hidden="true"
                />
              )}
              {row.state === "failed" && (
                <TriangleAlert
                  className="mt-0.5 h-4 w-4 shrink-0 text-red-600"
                  aria-hidden="true"
                />
              )}
              <span className="min-w-0">
                <span className="block truncate font-medium text-slate-900">{row.name}</span>
                {row.message && (
                  <span
                    className={row.state === "failed" ? "text-xs text-red-600" : "text-xs text-slate-500"}
                  >
                    {row.message}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}

/**
 * Cadrul paginii publice.
 *
 * Fără temă închisă, fără bară laterală, fără nimic din aplicație: cine ajunge
 * aici nu este utilizatorul aplicației, ci clientul cabinetului.
 */
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-10">
      <div className="mx-auto w-full max-w-xl">{children}</div>
    </div>
  );
}
