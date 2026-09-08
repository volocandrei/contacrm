/**
 * Extrasele bancare, în backendul simulat (§14).
 *
 * **Ce reproduce.** Forma răspunsurilor și **regulile pe care le vede omul**:
 * propunerile vin cu motive, nimic nu se leagă singur, o alocare parțială lasă
 * rândul în lucru, iar o legătură se poate scoate. Cu ele, ecranul se poate
 * dezvolta și demonstra fără backend.
 *
 * **Ce nu reproduce.** Motorul de potrivire. Regulile adevărate stau în
 * `backend/app/domain/bank_matching.py`, cu ponderi și praguri; aici se caută
 * numărul facturii în referință și suma exactă, atât. Un al doilea motor scris în
 * TypeScript s-ar fi despărțit de primul la prima corectură, iar demonstrația ar
 * fi arătat propuneri pe care serverul nu le face.
 *
 * Fișier separat de `store.ts` fiindcă acela are deja o mie opt sute de rânduri;
 * un modul nou nu are de ce să înceapă acolo.
 */
import { ApiError } from "@/api/types";
import type {
  BankStatement,
  BankTransaction,
  BankTransactionStatus,
  MatchSuggestion,
  TransactionMatch,
} from "@/types/domain";

/** Facturile pe care le poate plăti extrasul din demonstrație. */
type Invoice = {
  id: string;
  number: string;
  date: string;
  partnerName: string;
  total: string;
  /** Factură de la furnizor (bani ieșiți) sau emisă (bani intrați). */
  incoming: boolean;
};

const INVOICES: Invoice[] = [
  {
    id: "bank-doc-1",
    number: "7001",
    date: "2026-08-14",
    partnerName: "Terț Furnizor SRL",
    total: "1190.00",
    incoming: true,
  },
  {
    id: "bank-doc-2",
    number: "7002",
    date: "2026-08-16",
    partnerName: "Terț Furnizor SRL",
    total: "690.00",
    incoming: true,
  },
  {
    id: "bank-doc-3",
    number: "118",
    date: "2026-08-05",
    partnerName: "Gama Distribuție SRL",
    total: "4500.50",
    incoming: false,
  },
];

const STATEMENT: BankStatement = {
  id: "bank-stmt-1",
  clientId: "client-1",
  clientName: "Alfa Conta SRL",
  bankName: "Banca de Probă",
  iban: "RO49AAAA1B31007593840000",
  statementNumber: "8",
  currency: "RON",
  periodStart: "2026-08-01",
  periodEnd: "2026-08-31",
  openingBalance: "12000.00",
  closingBalance: "15306.50",
  transactionCount: 4,
  openCount: 4,
};

function row(
  id: string,
  position: number,
  bookingDate: string,
  description: string,
  amount: string,
  extra: Partial<BankTransaction> = {},
): BankTransaction {
  const outgoing = amount.startsWith("-");
  return {
    id,
    statementId: STATEMENT.id,
    clientId: STATEMENT.clientId,
    position,
    bookingDate,
    valueDate: bookingDate,
    description,
    amount,
    currency: "RON",
    direction: outgoing ? "DEBIT" : "CREDIT",
    counterpartyName: null,
    counterpartyIban: null,
    reference: null,
    status: "UNMATCHED",
    note: null,
    allocated: "0.00",
    unallocated: outgoing ? amount.slice(1) : amount,
    matches: [],
    ...extra,
  };
}

let transactions: BankTransaction[] = [
  row("bank-tx-1", 1, "2026-08-20", "Plata factura", "-1190.00", {
    counterpartyName: "TERT FURNIZOR SRL",
    reference: "FCT 7001",
  }),
  row("bank-tx-2", 2, "2026-08-22", "Incasare", "4500.50", {
    counterpartyName: "GAMA DISTRIBUTIE SRL",
    reference: "Contravaloare factura 118",
  }),
  // Plată parțială: acoperă jumătate din a doua factură. Rândul rămâne în lucru.
  row("bank-tx-3", 3, "2026-08-24", "Plata partiala", "-345.00", {
    counterpartyName: "TERT FURNIZOR SRL",
    reference: "avans 7002",
  }),
  // Cazul pentru care există starea „lămurit": nu are și nu va avea factură.
  row("bank-tx-4", 4, "2026-08-31", "Comision administrare cont", "-3.50"),
];

function find(id: string): BankTransaction {
  const found = transactions.find((item) => item.id === id);
  if (!found) throw new ApiError("NOT_FOUND", "Tranzacția nu există.", 404);
  return found;
}

function absolute(amount: string): number {
  return Math.abs(Number(amount));
}

function allocated(transaction: BankTransaction): number {
  return transaction.matches.reduce((total, match) => total + Number(match.amount), 0);
}

function covered(documentId: string): number {
  return transactions
    .flatMap((item) => item.matches)
    .filter((match) => match.documentId === documentId)
    .reduce((total, match) => total + Number(match.amount), 0);
}

/**
 * Starea iese din sume, nu se scrie de mână.
 *
 * Aceeași regulă ca pe server: o stare setată explicit s-ar desincroniza de
 * legături la a treia operațiune.
 */
function refresh(transaction: BankTransaction): void {
  const used = allocated(transaction);
  const total = absolute(transaction.amount);
  transaction.allocated = used.toFixed(2);
  transaction.unallocated = (total - used).toFixed(2);
  transaction.status = ((): BankTransactionStatus => {
    if (used <= 0) return transaction.status === "IGNORED" ? "IGNORED" : "UNMATCHED";
    if (Math.abs(used - total) < 0.005) return "MATCHED";
    return "NEEDS_REVIEW";
  })();
}

export function listStatements(): BankStatement[] {
  return [
    {
      ...STATEMENT,
      transactionCount: transactions.length,
      openCount: transactions.filter(
        (item) => item.status === "UNMATCHED" || item.status === "NEEDS_REVIEW",
      ).length,
    },
  ];
}

/**
 * Rândurile din extras, filtrate ca pe server.
 *
 * **Filtrele nu se ignoră.** Pe server au fost o vreme declarate `snake_case`
 * într-un contract camelCase, deci `?statementId=` se pierdea în tăcere și
 * ecranul de reconciliere arăta toate tranzacțiile cabinetului, nu pe cele ale
 * extrasului ales. Backendul simulat are un singur extras, deci nu s-ar fi văzut
 * niciodată aici — cu atât mai mult trebuie să aplice aceleași filtre: el este
 * contractul (§14).
 */
export function listTransactions(query: Record<string, string> = {}): BankTransaction[] {
  return transactions
    .filter((item) => !query.statementId || item.statementId === query.statementId)
    .filter((item) => !query.clientId || item.clientId === query.clientId)
    .filter((item) => !query.status || item.status === query.status)
    .map((item) => ({ ...item, matches: [...item.matches] }));
}

/**
 * Propunerile pentru un rând.
 *
 * Două semnale, nu cinci: numărul facturii în referință și suma exactă. Serverul
 * are mai multe — vezi antetul fișierului pentru de ce nu se copiază aici.
 */
export function suggestions(transactionId: string): MatchSuggestion[] {
  const transaction = find(transactionId);
  const outgoing = transaction.direction === "DEBIT";
  const remaining = Number(transaction.unallocated);
  if (remaining <= 0) return [];

  const text = `${transaction.reference ?? ""} ${transaction.description ?? ""}`.toLowerCase();

  return INVOICES.filter((invoice) => invoice.incoming === outgoing)
    .map((invoice) => {
      const reasons: string[] = [];
      let score = 0;

      if (new RegExp(`\\b${invoice.number}\\b`).test(text)) {
        score += 0.55;
        reasons.push("numărul facturii apare în plată");
      }
      const open = Number(invoice.total) - covered(invoice.id);
      if (Math.abs(absolute(transaction.amount) - Number(invoice.total)) < 0.005) {
        score += 0.3;
        reasons.push("sumă exactă");
      } else if (Math.abs(remaining - open) < 0.005) {
        score += 0.25;
        reasons.push("acoperă exact restul de plată");
      }
      if (transaction.counterpartyName && reasons.length > 0) {
        score += 0.2;
        reasons.push("numele partenerului se potrivește");
      }

      return { invoice, score, reasons, open };
    })
    .filter((item) => item.reasons.length > 0 && item.score >= 0.6 && item.open > 0)
    .sort((a, b) => b.score - a.score)
    .map((item) => ({
      documentId: item.invoice.id,
      documentNumber: item.invoice.number,
      documentDate: item.invoice.date,
      partnerName: item.invoice.partnerName,
      total: item.invoice.total,
      amount: Math.min(remaining, item.open).toFixed(2),
      score: Math.min(Math.round(item.score * 100) / 100, 1),
      reasons: item.reasons,
    }));
}

export function match(
  transactionId: string,
  documentId: string,
  amount: string | null,
): BankTransaction {
  const transaction = find(transactionId);
  const invoice = INVOICES.find((item) => item.id === documentId);
  const remaining = Number(transaction.unallocated);
  if (remaining <= 0) {
    throw new ApiError("VALIDATION_ERROR", "Tranzacția este deja alocată integral.", 422);
  }

  const open = invoice ? Number(invoice.total) - covered(documentId) : remaining;
  const wanted = amount !== null ? Number(amount) : Math.min(remaining, open);

  if (wanted <= 0) {
    throw new ApiError("VALIDATION_ERROR", "Suma trebuie să fie pozitivă.", 422);
  }
  if (wanted > remaining + 0.005) {
    throw new ApiError(
      "VALIDATION_ERROR",
      "Suma depășește ce a mai rămas din tranzacție.",
      422,
    );
  }
  if (invoice && wanted > open + 0.005) {
    throw new ApiError("VALIDATION_ERROR", "Suma depășește restul de plată al facturii.", 422);
  }

  const existing = transaction.matches.find((item) => item.documentId === documentId);
  if (existing) {
    existing.amount = (Number(existing.amount) + wanted).toFixed(2);
  } else {
    const entry: TransactionMatch = {
      documentId,
      documentNumber: invoice?.number ?? null,
      amount: wanted.toFixed(2),
      confidence: null,
      reasons: null,
    };
    transaction.matches.push(entry);
  }
  refresh(transaction);
  return transaction;
}

export function unmatch(transactionId: string, documentId: string): BankTransaction {
  const transaction = find(transactionId);
  transaction.matches = transaction.matches.filter((item) => item.documentId !== documentId);
  refresh(transaction);
  return transaction;
}

export function ignore(transactionId: string, note: string | null): BankTransaction {
  const transaction = find(transactionId);
  if (transaction.matches.length > 0) {
    throw new ApiError(
      "VALIDATION_ERROR",
      "Tranzacția are legături. Scoate-le înainte să o marchezi lămurită.",
      422,
    );
  }
  transaction.status = "IGNORED";
  transaction.note = note?.trim() || null;
  return transaction;
}

export function reopen(transactionId: string): BankTransaction {
  const transaction = find(transactionId);
  transaction.note = null;
  transaction.status = "UNMATCHED";
  refresh(transaction);
  return transaction;
}

/** Pentru teste: readuce extrasul la starea de la pornire. */
export function reset(): void {
  transactions = transactions.map((item) => ({
    ...item,
    matches: [],
    status: "UNMATCHED",
    note: null,
    allocated: "0.00",
    unallocated: absolute(item.amount).toFixed(2),
  }));
}
