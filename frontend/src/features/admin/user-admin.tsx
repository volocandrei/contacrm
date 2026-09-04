/**
 * Administrarea colegilor din cabinet (M12).
 *
 * `/users` era doar citire: lista exista, iar singurul mod de a adăuga pe cineva
 * era `python -m app.cli create-admin` — o comandă gândită pentru **primul** cont
 * al unei baze goale. Un cabinet care angajează pe cineva marți nu are de ce să
 * deschidă un terminal; iar dacă cineva pleca, contul lui rămânea activ până se
 * ocupa cineva prin SQL.
 *
 * Trei alegeri care se văd în ecran:
 *
 * - **Parola o pune administratorul și o comunică direct.** Nu există invitație
 *   prin email pentru că nu există provider (Faza 2), iar o invitație care nu
 *   pleacă este mai rea decât absența ei. Nu se generează nici una „temporară" pe
 *   care apoi s-o afișăm: un secret care trece prin ecran și prin log-ul unui
 *   proxy nu mai este un secret.
 * - **Nu există ștergere.** Un utilizator apare în jurnalul de audit ca autor al
 *   unor acțiuni contabile; ștergerea lui ar rupe urma. Ce se cere de fapt când
 *   cineva pleacă este „să nu mai poată intra", iar asta se face dezactivând.
 * - **Nimeni nu se poate încuia singur pe dinafară.** Propriul rând are rolul și
 *   dezactivarea blocate. Ascunderea rămâne ergonomie — serverul verifică
 *   același lucru, la fiecare cerere.
 */
import { useState } from "react";
import { Plus } from "lucide-react";
import { useCreateUser, useResetPassword, useUpdateUser } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { useAuth } from "@/features/auth/use-auth";
import { avatarTone, initials } from "@/lib/avatar";
import { formatDateTime } from "@/lib/format";
import { ROLE_LABEL } from "@/lib/labels";
import { iconChip, mutedText, pillClass } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { RoleCode, UserSummary } from "@/types/domain";

/** Minimul cerut și de server, și de `create-admin`. */
export const MIN_PASSWORD_LENGTH = 12;

const FIELD_CLASS =
  "h-9 w-full rounded-lg border border-slate-200 px-3 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100";

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

function RoleOptions() {
  return (
    <>
      {(Object.keys(ROLE_LABEL) as RoleCode[]).map((code) => (
        <option key={code} value={code}>
          {ROLE_LABEL[code]}
        </option>
      ))}
    </>
  );
}

/* ─── Un rând ──────────────────────────────────────────────────────────────── */

export function UserRow({ user }: { user: UserSummary }) {
  const { user: me } = useAuth();
  const update = useUpdateUser();
  const [problem, setProblem] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  const isMe = me?.id === user.id;

  function change(input: { role?: RoleCode; isActive?: boolean }) {
    setProblem(null);
    update.mutate(
      { id: user.id, input },
      {
        onError: (caught) =>
          setProblem(
            caught instanceof ApiError ? caught.message : "Schimbarea nu a fost salvată.",
          ),
      },
    );
  }

  return (
    <>
      <tr>
        <td className="px-4 py-3">
          <div className="flex items-center gap-3">
            {/* Aceleași inițiale colorate ca la clienți: un rând de tabel devine
                o persoană înainte de a fi citit. */}
            <span
              className={cn(
                "grid h-9 w-9 shrink-0 place-content-center rounded-lg text-xs font-semibold",
                iconChip[avatarTone(user.fullName)],
              )}
              aria-hidden="true"
            >
              {initials(user.fullName)}
            </span>
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {user.fullName}
              {isMe && <span className={cn("ml-2 text-xs", mutedText)}>(tu)</span>}
            </span>
          </div>
        </td>
        <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{user.email}</td>
        <td className="px-4 py-3">
          <label className="sr-only" htmlFor={`role-${user.id}`}>
            Rol pentru {user.fullName}
          </label>
          <select
            id={`role-${user.id}`}
            value={user.role}
            disabled={isMe || update.isPending}
            onChange={(event) => change({ role: event.target.value as RoleCode })}
            className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            <RoleOptions />
          </select>
        </td>
        <td className="px-4 py-3">
          <span className={pillClass(user.isActive ? "green" : "slate")}>
            {user.isActive ? "Activ" : "Dezactivat"}
          </span>
        </td>
        <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
          {user.lastLoginAt ? formatDateTime(user.lastLoginAt) : "—"}
        </td>
        <td className="px-4 py-3 text-right whitespace-nowrap">
          <button
            type="button"
            onClick={() => setResetting((open) => !open)}
            className="mr-3 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Resetează parola
          </button>
          <button
            type="button"
            disabled={isMe || update.isPending}
            onClick={() => change({ isActive: !user.isActive })}
            className="text-sm font-medium text-slate-600 hover:underline disabled:opacity-40 dark:text-slate-300"
          >
            {user.isActive ? "Dezactivează" : "Reactivează"}
          </button>
        </td>
      </tr>

      {problem && (
        <tr>
          <td colSpan={6} className="px-4 pb-2">
            <p role="alert" className="text-xs text-red-600 dark:text-red-400">
              {problem}
            </p>
          </td>
        </tr>
      )}

      {resetting && (
        <tr>
          <td colSpan={6} className="bg-slate-50 px-4 py-3 dark:bg-slate-800/60">
            <PasswordResetForm user={user} onDone={() => setResetting(false)} />
          </td>
        </tr>
      )}
    </>
  );
}

/* ─── Resetarea parolei ────────────────────────────────────────────────────── */

function PasswordResetForm({ user, onDone }: { user: UserSummary; onDone: () => void }) {
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setProblem(null);
    reset.mutate(
      { id: user.id, password },
      {
        onSuccess: () => {
          setPassword("");
          setDone(true);
        },
        onError: (caught) =>
          setProblem(caught instanceof ApiError ? caught.message : "Parola nu a fost schimbată."),
      },
    );
  }

  if (done) {
    return (
      <p className="text-sm text-green-700 dark:text-green-400">
        Parola lui {user.fullName} a fost schimbată. Spune-i-o direct — aplicația nu trimite
        mesaje.{" "}
        <button type="button" onClick={onDone} className="font-medium hover:underline">
          Închide
        </button>
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
      <Field id={`password-${user.id}`} label={`Parolă nouă pentru ${user.fullName}`}>
        <input
          id={`password-${user.id}`}
          type="password"
          value={password}
          minLength={MIN_PASSWORD_LENGTH}
          onChange={(event) => setPassword(event.target.value)}
          className={`${FIELD_CLASS} w-72`}
        />
      </Field>
      <button
        type="submit"
        disabled={password.length < MIN_PASSWORD_LENGTH || reset.isPending}
        className="h-9 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
      >
        Schimbă parola
      </button>
      <button
        type="button"
        onClick={onDone}
        className="h-9 text-sm font-medium text-slate-600 hover:underline dark:text-slate-300"
      >
        Renunță
      </button>
      {problem && (
        <p role="alert" className="w-full text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </form>
  );
}

/* ─── Colegul nou ──────────────────────────────────────────────────────────── */

export function AddUserButton() {
  const create = useCreateUser();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    email: "",
    fullName: "",
    role: "OPERATOR" as RoleCode,
    password: "",
  });
  const [problem, setProblem] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setProblem(null);
    create.mutate(form, {
      onSuccess: () => {
        setForm({ email: "", fullName: "", role: "OPERATOR", password: "" });
        setOpen(false);
      },
      onError: (caught) =>
        setProblem(caught instanceof ApiError ? caught.message : "Contul nu a putut fi creat."),
    });
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700"
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        Coleg nou
      </button>
    );
  }

  return (
    <form
      onSubmit={submit}
      className="w-full max-w-2xl rounded-xl border border-slate-200 p-4 text-left dark:border-slate-800"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field id="user-fullName" label="Nume complet">
          <input
            id="user-fullName"
            value={form.fullName}
            onChange={(event) => setForm({ ...form, fullName: event.target.value })}
            className={FIELD_CLASS}
          />
        </Field>
        <Field id="user-email" label="Email">
          <input
            id="user-email"
            type="email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            className={FIELD_CLASS}
          />
        </Field>
        <Field id="user-role" label="Rol">
          <select
            id="user-role"
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value as RoleCode })}
            className={FIELD_CLASS}
          >
            <RoleOptions />
          </select>
        </Field>
        <Field id="user-password" label={`Parolă (minimum ${MIN_PASSWORD_LENGTH} caractere)`}>
          <input
            id="user-password"
            type="password"
            value={form.password}
            minLength={MIN_PASSWORD_LENGTH}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            className={FIELD_CLASS}
          />
        </Field>
      </div>

      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        Parola o alegi tu și i-o spui colegului direct. Nu pleacă niciun email — aplicația încă
        nu trimite mesaje.
      </p>

      {problem && (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}

      <div className="mt-3 flex justify-end gap-3">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="h-9 text-sm font-medium text-slate-600 hover:underline dark:text-slate-300"
        >
          Renunță
        </button>
        <button
          type="submit"
          disabled={create.isPending}
          className="h-9 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
        >
          Adaugă colegul
        </button>
      </div>
    </form>
  );
}
