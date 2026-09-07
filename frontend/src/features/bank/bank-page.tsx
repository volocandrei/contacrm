/**
 * Extrase bancare și reconciliere (§11–§15).
 *
 * **Munca pe care o înlocuiește ecranul.** Contabilul are extrasul într-o parte,
 * facturile în alta, și le potrivește cu ochiul. Trei sute de rânduri pe lună,
 * per client. Este una dintre cele mai lungi ore ale lunii, și una dintre cele
 * mai ușor de greșit — o plată pusă pe factura vecină iese la închiderea anului,
 * dacă iese.
 *
 * **Cum este așezat, și de ce.** Stânga: rândurile din extras, în ordinea din
 * fișier. Dreapta: ce ar putea fi rândul deschis, cu **motivul** fiecărei
 * propuneri. Nu invers: omul parcurge extrasul, nu lista de facturi.
 *
 * **Nimic nu se leagă singur.** Propunerea are un buton, iar butonul are o sumă
 * scrisă pe el înainte de apăsare. Diferența dintre un asistent și un sistem care
 * mută bani este exact apăsarea aceea.
 *
 * **Motivele sunt afișate întotdeauna, nu sub un „vezi detalii".** Fără ele,
 * contabilul fie verifică tot de la zero — și atunci ecranul n-a economisit
 * nimic — fie acceptă fără să verifice, ceea ce este mai rău decât munca de mână.
 */
import { useState } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  Link2Off,
  Landmark,
  Undo2,
  X,
} from "lucide-react";
import { EmptyState, LoadingState, PageHeader, Panel } from "@/components/page";
import {
  useBankStatements,
  useBankTransactions,
  useIgnoreTransaction,
  useMatchSuggestions,
  useMatchTransaction,
  useReopenTransaction,
  useUnmatchTransaction,
} from "@/api/hooks";
import { ApiError } from "@/api/types";
import { formatDate, formatMoney } from "@/lib/format";
import { buttonPrimary, mutedText, pillClass, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import type { BankTransaction, BankTransactionStatus, MatchSuggestion } from "@/types/domain";

const STATUS_LABEL: Record<BankTransactionStatus, string> = {
  UNMATCHED: "Nepotrivit",
  SUGGESTED: "Propus",
  MATCHED: "Potrivit",
  IGNORED: "Lămurit",
  NEEDS_REVIEW: "Parțial",
};

const STATUS_TONE: Record<BankTransactionStatus, Tone> = {
  UNMATCHED: "slate",
  SUGGESTED: "blue",
  MATCHED: "green",
  IGNORED: "slate",
  NEEDS_REVIEW: "amber",
};

export function BankPage() {
  const statements = useBankStatements();
  const [statementId, setStatementId] = useState<string | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);

  const rows = statements.data ?? [];
  const selected = statementId ?? rows[0]?.id ?? null;
  const transactions = useBankTransactions(selected ? { statementId: selected } : {});

  if (statements.isLoading) return <LoadingState />;

  return (
    <div>
      <PageHeader
        title="Extrase bancare"
        description="Ce factură a plătit fiecare rând. Sistemul propune și spune de ce; confirmi tu."
      />

      {rows.length === 0 ? (
        <EmptyState
          title="Niciun extras importat"
          description="Exportă extrasul din internet banking ca CSV și încarcă-l. Coloanele se recunosc după nume, oricum le-ar scrie banca."
        />
      ) : (
        <>
          <div className="mb-5 flex flex-wrap gap-2">
            {rows.map((statement) => {
              const active = statement.id === selected;
              return (
                <button
                  key={statement.id}
                  type="button"
                  onClick={() => {
                    setStatementId(statement.id);
                    setOpenRow(null);
                  }}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-left text-sm transition",
                    active
                      ? "border-blue-500 bg-blue-50 dark:border-blue-400 dark:bg-blue-500/10"
                      : "border-slate-200 hover:border-slate-300 dark:border-slate-800",
                  )}
                >
                  <span className="flex items-center gap-1.5 font-medium text-slate-900 dark:text-slate-100">
                    <Landmark className="size-4" aria-hidden />
                    {statement.bankName ?? "Extras"}
                  </span>
                  <span className={cn("mt-0.5 block text-xs", mutedText)}>
                    {formatDate(statement.periodStart)} – {formatDate(statement.periodEnd)}
                    {statement.clientName ? ` · ${statement.clientName}` : ""}
                  </span>
                  <span className="mt-1 block">
                    {/* Singurul număr după care se alege extrasul de deschis. */}
                    <span className={pillClass(statement.openCount > 0 ? "amber" : "green")}>
                      {statement.openCount > 0
                        ? `${statement.openCount} de lămurit`
                        : "reconciliat"}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
            <Panel title="Rânduri din extras" bodyClassName="p-0">
              {transactions.isLoading ? (
                <LoadingState />
              ) : (
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {(transactions.data ?? []).map((item) => (
                    <TransactionRow
                      key={item.id}
                      transaction={item}
                      open={openRow === item.id}
                      onOpen={() => setOpenRow(openRow === item.id ? null : item.id)}
                    />
                  ))}
                </ul>
              )}
            </Panel>

            <Suggestions transactionId={openRow} />
          </div>
        </>
      )}
    </div>
  );
}

function TransactionRow({
  transaction,
  open,
  onOpen,
}: {
  transaction: BankTransaction;
  open: boolean;
  onOpen: () => void;
}) {
  const unmatch = useUnmatchTransaction();
  const ignore = useIgnoreTransaction();
  const reopen = useReopenTransaction();
  const money = transaction.currency ?? "RON";
  const outgoing = transaction.direction === "DEBIT";

  return (
    <li className={cn(open && "bg-slate-50 dark:bg-slate-800/40")}>
      <button
        type="button"
        onClick={onOpen}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3 text-left"
      >
        {outgoing ? (
          <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-rose-500" aria-hidden />
        ) : (
          <ArrowDownLeft className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden />
        )}

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="truncate font-medium text-slate-900 dark:text-slate-100">
              {transaction.counterpartyName ?? transaction.description ?? "—"}
            </span>
            <span
              className={cn(
                "font-medium whitespace-nowrap",
                outgoing
                  ? "text-rose-600 dark:text-rose-400"
                  : "text-emerald-700 dark:text-emerald-400",
              )}
            >
              {formatMoney(transaction.amount, money)}
            </span>
          </span>
          <span className={cn("mt-0.5 flex flex-wrap items-center gap-2 text-xs", mutedText)}>
            <span>{formatDate(transaction.bookingDate)}</span>
            {transaction.reference && <span>· {transaction.reference}</span>}
            <span className={pillClass(STATUS_TONE[transaction.status])}>
              {STATUS_LABEL[transaction.status]}
            </span>
            {transaction.status === "NEEDS_REVIEW" && (
              <span>rest {formatMoney(transaction.unallocated, money)}</span>
            )}
          </span>
        </span>
      </button>

      {transaction.matches.length > 0 && (
        <ul className="space-y-1 px-4 pb-3 pl-11">
          {transaction.matches.map((match) => (
            <li
              key={match.documentId}
              className="flex items-center justify-between gap-2 rounded-md bg-white px-2 py-1 text-xs dark:bg-slate-900"
            >
              <span className="min-w-0 truncate text-slate-700 dark:text-slate-300">
                Factura {match.documentNumber ?? "—"} · {formatMoney(match.amount, money)}
                {match.reasons && (
                  <span className={cn("ml-1", mutedText)}>({match.reasons})</span>
                )}
              </span>
              <button
                type="button"
                className="shrink-0 text-slate-400 hover:text-rose-600"
                aria-label={`Scoate legătura cu factura ${match.documentNumber ?? ""}`}
                onClick={() =>
                  unmatch.mutate({
                    transactionId: transaction.id,
                    documentId: match.documentId,
                  })
                }
              >
                <Link2Off className="size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && transaction.matches.length === 0 && (
        <div className="px-4 pb-3 pl-11">
          {transaction.status === "IGNORED" ? (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
              onClick={() => reopen.mutate({ transactionId: transaction.id })}
            >
              <Undo2 className="size-3.5" aria-hidden />
              Readu în lista de lucru
              {transaction.note && <span className={mutedText}>· {transaction.note}</span>}
            </button>
          ) : (
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
              onClick={() =>
                ignore.mutate({
                  transactionId: transaction.id,
                  // Comisioane, dobânzi, transferuri între conturile proprii.
                  note: "Fără factură în spate",
                })
              }
            >
              <X className="size-3.5" aria-hidden />
              Nu are factură (comision, dobândă, transfer propriu)
            </button>
          )}
        </div>
      )}
    </li>
  );
}

function Suggestions({ transactionId }: { transactionId: string | null }) {
  const suggestions = useMatchSuggestions(transactionId);
  const match = useMatchTransaction();

  if (!transactionId) {
    return (
      <Panel title="Ce factură ar putea fi">
        <p className={cn("text-sm", mutedText)}>
          Deschide un rând din extras ca să vezi propunerile pentru el.
        </p>
      </Panel>
    );
  }

  const rows = suggestions.data ?? [];
  const failure = match.error instanceof ApiError ? match.error.message : null;

  return (
    <Panel title="Ce factură ar putea fi">
      {suggestions.isLoading && <p className={cn("text-sm", mutedText)}>Se caută…</p>}

      {!suggestions.isLoading && rows.length === 0 && (
        <p className={cn("text-sm", mutedText)}>
          Nicio factură nu se potrivește destul de bine. Tăcerea este un răspuns: o
          propunere pe o singură coincidență leagă, mai des decât credem, factura greșită.
        </p>
      )}

      {failure && (
        <p role="alert" className="mb-3 text-xs text-rose-600 dark:text-rose-400">
          {failure}
        </p>
      )}

      <ul className="space-y-3">
        {rows.map((item) => (
          <SuggestionCard
            key={item.documentId}
            suggestion={item}
            pending={match.isPending}
            onAccept={() =>
              match.mutate({
                transactionId,
                documentId: item.documentId,
                amount: item.amount,
              })
            }
          />
        ))}
      </ul>
    </Panel>
  );
}

function SuggestionCard({
  suggestion,
  pending,
  onAccept,
}: {
  suggestion: MatchSuggestion;
  pending: boolean;
  onAccept: () => void;
}) {
  return (
    <li className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium text-slate-900 dark:text-slate-100">
          Factura {suggestion.documentNumber ?? "—"}
          {suggestion.partnerName && (
            <span className={cn("ml-1 font-normal", mutedText)}>· {suggestion.partnerName}</span>
          )}
        </p>
        {/* Scorul, ca număr, lângă motivele care l-au produs. Fără motive ar fi
            o cifră pe care nimeni nu o poate verifica. */}
        <span className={pillClass(suggestion.score >= 0.9 ? "green" : "blue")}>
          {Math.round(suggestion.score * 100)}%
        </span>
      </div>

      <p className={cn("mt-0.5 text-xs", mutedText)}>
        {suggestion.documentDate ? formatDate(suggestion.documentDate) : "fără dată"}
        {suggestion.total && ` · total ${formatMoney(suggestion.total, "RON")}`}
      </p>

      <ul className={cn("mt-2 space-y-0.5 text-xs", mutedText)}>
        {suggestion.reasons.map((reason) => (
          <li key={reason}>· {reason}</li>
        ))}
      </ul>

      <button
        type="button"
        className={cn(buttonPrimary, "mt-3")}
        disabled={pending}
        onClick={onAccept}
      >
        <Check className="size-4" aria-hidden />
        Leagă {formatMoney(suggestion.amount, "RON")}
      </button>
    </li>
  );
}
