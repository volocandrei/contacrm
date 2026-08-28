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

export type NavItem = {
  label: string;
  path: string;
  Icon: LucideIcon;
  /** Contor afișat ca badge; se va alimenta din API. */
  badgeKey?: BadgeKey;
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
      { label: "Clienți", path: "/crm/clienti", Icon: Building2 },
      { label: "Contacte", path: "/crm/contacte", Icon: Contact },
      { label: "Sarcini", path: "/crm/sarcini", Icon: ClipboardList, badgeKey: "tasks" },
    ],
  },
  {
    label: "Documente",
    Icon: FileStack,
    items: [
      { label: "Inbox", path: "/documente/inbox", Icon: Inbox, badgeKey: "inbox" },
      { label: "În procesare", path: "/documente/procesare", Icon: FileSearch },
      { label: "Verificare", path: "/documente/verificare", Icon: ShieldCheck, badgeKey: "review" },
      { label: "Arhivă", path: "/documente/arhiva", Icon: Archive },
    ],
  },
  {
    label: "Contabilitate",
    Icon: CalendarRange,
    items: [
      { label: "Perioade", path: "/contabilitate/perioade", Icon: CalendarRange },
      { label: "Documente lipsă", path: "/contabilitate/lipsa", Icon: FileQuestionMark },
    ],
  },
  {
    label: "Comunicare",
    Icon: MessageSquare,
    items: [
      { label: "Mesaje", path: "/comunicare/mesaje", Icon: MessageSquare },
      { label: "Șabloane", path: "/comunicare/sabloane", Icon: ScrollText },
      { label: "Remindere", path: "/comunicare/remindere", Icon: Bell },
    ],
  },
  {
    label: "Rapoarte",
    Icon: ChartColumn,
    items: [{ label: "Rapoarte", path: "/rapoarte", Icon: ChartColumn }],
  },
  {
    label: "Administrare",
    Icon: Settings,
    items: [
      { label: "Utilizatori", path: "/administrare/utilizatori", Icon: Users },
      { label: "Roluri", path: "/administrare/roluri", Icon: KeyRound },
      { label: "Setări", path: "/administrare/setari", Icon: Settings },
      { label: "Jurnal audit", path: "/administrare/audit", Icon: ScrollText },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = [NAV_ROOT, ...NAV_GROUPS.flatMap((g) => g.items)];
