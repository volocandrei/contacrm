/**
 * Securitatea contului meu (§1, §45).
 *
 * **Golul pe care îl umple.** Aplicația avea autentificare bună — Argon2id,
 * contor pe eșecuri, familii de tokenuri cu detecția refolosirii — și niciun
 * ecran în care omul să poată face ceva cu ea. Concret, două lipsuri:
 *
 * 1. **Nimeni nu-și putea schimba propria parolă.** Exista doar resetarea făcută
 *    de un administrator **altcuiva**; pe o instalare proaspătă administratorul
 *    este unul singur, deci parola pusă la instalare nu mai putea fi schimbată
 *    din aplicație de nimeni. Iar ea păzește documentele financiare ale tuturor
 *    clienților cabinetului.
 * 2. **Nu se putea afla cine mai are o fereastră deschisă pe cont.** Întrebarea
 *    se pune exact în ziua proastă — după un laptop lăsat deschis, după o parolă
 *    tastată pe alt calculator — iar singurul remediu era schimbarea parolei,
 *    adică o măsură mai mare decât problema, pe care omul o amână.
 *
 * **Ecran de cont, nu de administrator.** Îl deschide oricine, indiferent de rol:
 * parola operatorului păzește aceleași documente. Ce este administrativ — ceilalți
 * utilizatori, rolurile, jurnalul întreg — rămâne unde era.
 *
 * **Nu se afișează niciun secret.** Nici token, nici hash, nici parola veche.
 * Sesiunile se arată prin ce a rămas din ele: când au început, când au fost văzute
 * ultima oară, de la ce adresă și cu ce browser.
 */
import { useState } from "react";
import { KeyRound, MonitorSmartphone, ShieldCheck } from "lucide-react";
import { PageHeader, Panel } from "@/components/page";
import { useAuth } from "@/features/auth/use-auth";
import { useChangePassword, useRevokeOtherSessions, useSessions } from "@/api/hooks";
import { ApiError } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { ROLE_LABEL } from "@/lib/labels";
import { MIN_LENGTH, passwordProblems } from "@/lib/password";
import { buttonPrimary, mutedText, pillClass } from "@/lib/ui";
import { cn } from "@/lib/utils";

const FIELD_CLASS =
  "h-9 w-full rounded-lg border border-slate-200 px-3 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100";

export function SecurityPage() {
  const { user } = useAuth();

  return (
    <div>
      <PageHeader
        title="Securitate"
        description="Parola contului tău și ferestrele deschise pe el. Nimic din ce se vede aici nu este un secret."
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-5">
          <Panel title="Contul meu">
            <dl className="space-y-3 text-sm">
              <Row label="Nume">{user?.fullName ?? "—"}</Row>
              <Row label="Email">{user?.email ?? "—"}</Row>
              <Row label="Rol">
                <span className={pillClass("slate")}>
                  {user ? ROLE_LABEL[user.role] : "—"}
                </span>
              </Row>
              <Row label="Cabinet">{user?.organizationName ?? "—"}</Row>
            </dl>
          </Panel>

          <PasswordPanel />
        </div>

        <SessionsPanel />
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className={cn("text-xs uppercase tracking-wide", mutedText)}>{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium text-slate-900 dark:text-slate-100">
        {children}
      </dd>
    </div>
  );
}

function PasswordPanel() {
  const { user } = useAuth();
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [done, setDone] = useState(false);

  // Motivele se calculează în browser, cu **aceleași reguli** ca serverul
  // (`lib/password.ts` este portul lui `app/domain/passwords.py`). Altfel omul
  // scrie, apasă, așteaptă și primește refuzul — de trei ori la rând, fiindcă
  // motivele ar veni unul câte unul.
  const reasons = next ? passwordProblems(next, user?.email, user?.fullName) : [];
  const mismatch = repeat.length > 0 && next !== repeat;
  const ready = current.length > 0 && next.length > 0 && reasons.length === 0 && !mismatch;

  const failure = change.error instanceof ApiError ? change.error.message : null;

  return (
    <Panel title="Schimbă parola">
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready) return;
          setDone(false);
          change.mutate(
            { currentPassword: current, newPassword: next },
            {
              onSuccess: () => {
                setCurrent("");
                setNext("");
                setRepeat("");
                setDone(true);
              },
            },
          );
        }}
      >
        <p className={cn("text-xs", mutedText)}>
          Minimum {MIN_LENGTH} caractere. Fără majusculă sau simbol obligatoriu — o frază
          lungă apără mai bine decât <code>Parola123!</code>.
        </p>

        <Field id="current-password" label="Parola actuală">
          <input
            id="current-password"
            type="password"
            autoComplete="current-password"
            className={FIELD_CLASS}
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </Field>

        <Field id="new-password" label="Parola nouă">
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            className={FIELD_CLASS}
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        </Field>

        <Field id="repeat-password" label="Repetă parola nouă">
          <input
            id="repeat-password"
            type="password"
            autoComplete="new-password"
            className={FIELD_CLASS}
            value={repeat}
            onChange={(event) => setRepeat(event.target.value)}
          />
        </Field>

        {reasons.length > 0 && (
          <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-300">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        {mismatch && (
          <p className="text-xs text-amber-700 dark:text-amber-300">
            Cele două parole nu coincid.
          </p>
        )}
        {failure && (
          <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">
            {failure}
          </p>
        )}
        {done && (
          <p role="status" className="text-xs text-emerald-700 dark:text-emerald-400">
            Parola a fost schimbată. Celelalte ferestre deschise pe cont au fost închise.
          </p>
        )}

        <button type="submit" className={buttonPrimary} disabled={!ready || change.isPending}>
          <KeyRound className="size-4" aria-hidden />
          {change.isPending ? "Se schimbă…" : "Schimbă parola"}
        </button>
      </form>
    </Panel>
  );
}

function SessionsPanel() {
  const sessions = useSessions();
  const revoke = useRevokeOtherSessions();
  const rows = sessions.data ?? [];
  const others = rows.filter((item) => !item.current).length;

  return (
    <Panel
      title="Ferestre deschise pe contul meu"
      action={
        others > 0 ? (
          <button
            type="button"
            className={buttonPrimary}
            disabled={revoke.isPending}
            onClick={() => revoke.mutate()}
          >
            <ShieldCheck className="size-4" aria-hidden />
            Închide celelalte ({others})
          </button>
        ) : null
      }
    >
      {sessions.isLoading && <p className={cn("text-sm", mutedText)}>Se încarcă…</p>}

      {!sessions.isLoading && rows.length === 0 && (
        <p className={cn("text-sm", mutedText)}>Nicio sesiune activă.</p>
      )}

      <ul className="space-y-3">
        {rows.map((item) => (
          <li
            key={item.id}
            className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
          >
            <MonitorSmartphone
              className="mt-0.5 size-4 shrink-0 text-slate-400"
              aria-hidden
            />
            <div className="min-w-0 flex-1 text-sm">
              <p className="flex flex-wrap items-center gap-2 font-medium text-slate-900 dark:text-slate-100">
                <span className="truncate">{item.userAgent ?? "Browser necunoscut"}</span>
                {item.current && <span className={pillClass("green")}>sesiunea curentă</span>}
              </p>
              <p className={cn("mt-0.5 text-xs", mutedText)}>
                {item.ip ?? "adresă necunoscută"} · începută {formatDateTime(item.startedAt)} ·
                ultima activitate {formatDateTime(item.lastSeenAt)}
              </p>
            </div>
          </li>
        ))}
      </ul>

      {others > 0 && (
        <p className={cn("mt-4 text-xs", mutedText)}>
          Nu recunoști una dintre ele? Închide-le pe toate, apoi schimbă parola.
        </p>
      )}
    </Panel>
  );
}

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
