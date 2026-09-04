/**
 * Cum se numesc stările în interfață.
 *
 * Etichetele stăteau în `components/status-badge.tsx`, lângă componentele care
 * le desenau. Cât timp doar insigna avea nevoie de ele, era în regulă; din
 * momentul în care legenda unui grafic scrie același nume, harta trebuie să iasă
 * de acolo. Două copii s-ar despărți la prima redenumire, iar graficul ar spune
 * altceva decât rândul de lângă el.
 *
 * Fișierul nu exportă componente, deliberat: un modul care amestecă etichete și
 * componente rupe reîmprospătarea rapidă din development.
 *
 * Vocabularul în sine — ce stări există — vine din backend (§53) și este
 * verificat automat de `tests/test_contract_enums.py`. Aici este doar traducerea.
 */
import type { ClientStatus, DocumentStatus, PeriodStatus } from "@/types/domain";

export const DOCUMENT_STATUS_LABEL: Record<DocumentStatus, string> = {
  RECEIVED: "Recepționat",
  PROCESSING: "În procesare",
  REVIEW_REQUIRED: "Necesită verificare",
  APPROVED: "Aprobat",
  ARCHIVED: "Arhivat",
  ERROR: "Eroare",
  DUPLICATE: "Duplicat",
  REJECTED: "Respins",
  UNMATCHED: "Client neidentificat",
};

export const PERIOD_STATUS_LABEL: Record<PeriodStatus, string> = {
  NOT_STARTED: "Neînceput",
  COLLECTING: "În colectare",
  PARTIAL: "Parțial",
  COMPLETE: "Documente complete",
  PROCESSING: "În procesare",
  REVIEW: "Verificare",
  FINALIZED: "Finalizat",
};

export const CLIENT_STATUS_LABEL: Record<ClientStatus, string> = {
  ACTIVE: "Activ",
  INACTIVE: "Inactiv",
  PROSPECT: "Prospect",
  SUSPENDED: "Suspendat",
};
