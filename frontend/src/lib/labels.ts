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
import type {
  ClientStatus,
  DocumentStatus,
  Permission,
  PeriodStatus,
  RoleCode,
} from "@/types/domain";

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

/**
 * Numele rolurilor.
 *
 * `GET /roles` trimite eticheta serverului, iar ecranul de roluri o folosește pe
 * aceea. Harta de aici rămâne pentru locurile care nu au lista de la server —
 * formularul prin care alegi rolul unui coleg nou, de pildă — și pentru
 * backendul simulat. `tests/test_contract_permissions.py` cade dacă cele două
 * se despart: un rol nu are voie să se numească altfel pe ecran decât în
 * răspunsul serverului.
 */
export const ROLE_LABEL: Record<RoleCode, string> = {
  SUPER_ADMIN: "Super administrator",
  ADMIN: "Administrator",
  ACCOUNTANT: "Contabil",
  OPERATOR: "Operator",
  REVIEWER: "Verificator",
  VIEWER: "Vizitator",
};

/** Ce înseamnă, în cuvinte, fiecare permisiune. */
export const PERMISSION_LABEL: Record<Permission, string> = {
  "clients:read": "Vizualizare clienți",
  "clients:write": "Modificare clienți",
  "documents:read": "Vizualizare documente",
  "documents:write": "Modificare documente",
  "documents:approve": "Aprobare documente",
  "documents:delete": "Ștergere documente",
  "periods:manage": "Administrare perioade",
  "tasks:read": "Vizualizare sarcini",
  "tasks:write": "Modificare sarcini",
  "communication:send": "Trimitere mesaje",
  "admin:users": "Administrare utilizatori",
  "admin:settings": "Administrare setări",
  "audit:read": "Acces jurnal audit",
};

/**
 * Zona din aplicație pe care o deschide o permisiune.
 *
 * Treisprezece rânduri fără despărțituri se citesc ca o listă oarecare. Grupate,
 * întrebarea „ce poate face un operator cu documentele?" are un răspuns care se
 * vede dintr-o privire.
 */
export const PERMISSION_AREA_LABEL: Record<string, string> = {
  clients: "Clienți",
  documents: "Documente",
  periods: "Perioade contabile",
  tasks: "Sarcini",
  communication: "Comunicare",
  admin: "Administrare",
  audit: "Audit",
};
