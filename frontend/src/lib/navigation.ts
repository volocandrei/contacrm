import {
  Archive,
  Bell,
  Building2,
  CalendarRange,
  ChartColumn,
  ClipboardList,
  Contact,
  FileSearch,
  FileStack,
  FileQuestionMark,
  Inbox,
  KeyRound,
  LayoutDashboard,
  MessageSquare,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { Permission } from "@/types/domain";

export type NavItem = {
  label: string;
  path: string;
  Icon: LucideIcon;
  /** Contor afișat ca badge; se va alimenta din API. */
  badgeKey?: BadgeKey;
  /**
   * Permisiunea fără de care intrarea nu se arată deloc.
   *
   * Este **aceeași** pe care o cere ruta din backend, nu una aproximativă:
   * un meniu care oferă uși încuiate trimite operatorul într-un 403 și îl lasă
   * să creadă că aplicația e stricată. Ascunderea rămâne ergonomie — refuzul
   * adevărat îl dă serverul, la fiecare cerere.
   *
   * Fără valoare înseamnă „oricine autentificat".
   */
  permission?: Permission;
};

export type NavGroup = {
  label: string;
  Icon: LucideIcon;
  items: NavItem[];
};

export type BadgeKey = "inbox" | "review" | "unmatched" | "tasks";

/**
 * Structura de navigație conform specificației (§51).
 * Rutele placeholder există pentru ca shell-ul să fie navigabil înainte de
 * implementarea fiecărui modul.
 */
export const NAV_ROOT: NavItem = {
  label: "Panou principal",
  path: "/",
  Icon: LayoutDashboard,
};

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "CRM",
    Icon: Building2,
    items: [
      { label: "Clienți", path: "/crm/clienti", Icon: Building2, permission: "clients:read" },
      { label: "Contacte", path: "/crm/contacte", Icon: Contact, permission: "clients:read" },
      {
        label: "Sarcini",
        path: "/crm/sarcini",
        Icon: ClipboardList,
        badgeKey: "tasks",
        permission: "tasks:read",
      },
    ],
  },
  {
    label: "Documente",
    Icon: FileStack,
    items: [
      {
        label: "Inbox",
        path: "/documente/inbox",
        Icon: Inbox,
        badgeKey: "inbox",
        permission: "documents:read",
      },
      {
        label: "În procesare",
        path: "/documente/procesare",
        Icon: FileSearch,
        permission: "documents:read",
      },
      {
        label: "Verificare",
        path: "/documente/verificare",
        Icon: ShieldCheck,
        badgeKey: "review",
        permission: "documents:read",
      },
      {
        label: "Arhivă",
        path: "/documente/arhiva",
        Icon: Archive,
        permission: "documents:read",
      },
    ],
  },
  {
    label: "Contabilitate",
    Icon: CalendarRange,
    items: [
      {
        label: "Perioade",
        path: "/contabilitate/perioade",
        Icon: CalendarRange,
        permission: "documents:read",
      },
      {
        label: "Documente lipsă",
        path: "/contabilitate/lipsa",
        Icon: FileQuestionMark,
        permission: "documents:read",
      },
    ],
  },
  {
    label: "Comunicare",
    Icon: MessageSquare,
    items: [
      {
        label: "Mesaje",
        path: "/comunicare/mesaje",
        Icon: MessageSquare,
        permission: "communication:send",
      },
      {
        label: "Șabloane",
        path: "/comunicare/sabloane",
        Icon: ScrollText,
        permission: "communication:send",
      },
      {
        label: "Remindere",
        path: "/comunicare/remindere",
        Icon: Bell,
        permission: "communication:send",
      },
    ],
  },
  {
    label: "Rapoarte",
    Icon: ChartColumn,
    items: [
      {
        label: "Rapoarte",
        path: "/rapoarte",
        Icon: ChartColumn,
        permission: "documents:read",
      },
    ],
  },
  {
    label: "Administrare",
    Icon: Settings,
    items: [
      {
        label: "Utilizatori",
        path: "/administrare/utilizatori",
        Icon: Users,
        permission: "admin:users",
      },
      {
        label: "Roluri",
        path: "/administrare/roluri",
        Icon: KeyRound,
        permission: "admin:users",
      },
      {
        label: "Setări",
        path: "/administrare/setari",
        Icon: Settings,
        permission: "admin:settings",
      },
      {
        label: "Jurnal audit",
        path: "/administrare/audit",
        Icon: ScrollText,
        permission: "audit:read",
      },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = [NAV_ROOT, ...NAV_GROUPS.flatMap((g) => g.items)];
