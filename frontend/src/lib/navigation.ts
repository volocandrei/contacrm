import {
  Archive,
  Bell,
  Building2,
  CalendarRange,
  ChartColumn,
  Cloud,
  Landmark,
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
 *
 * Fiecare intrare duce la un ecran real. Comentariul de aici spunea, până acum,
 * că unele sunt placeholdere pentru ca shell-ul să fie navigabil — a fost
 * adevărat la M1 și a rămas scris cu mult după ce ultimul a fost înlocuit.
 * Lista este și sursa paletei de comenzi (Ctrl+K), care caută în ea.
 */
export const NAV_ROOT: NavItem = {
  label: "Panou principal",
  path: "/",
  Icon: LayoutDashboard,
};

/**
 * Grupurile, în ordinea în care se lucrează.
 *
 * **De ce ordinea asta.** Meniul era ordonat după cum s-au construit modulele —
 * CRM, Documente, Contabilitate, … —, nu după cum se folosesc. Într-un cabinet,
 * ziua începe la documente: ce a sosit, ce așteaptă un om, ce se poate închide.
 * Clienții și rapoartele se deschid mai rar, administrarea aproape niciodată.
 * Un meniu ordonat după frecvență scurtează drumul care se face de o sută de
 * ori pe zi și îl lungește pe cel care se face o dată pe lună.
 *
 * **De ce „Integrări" separat de „Administrare".** Sunt două întrebări diferite:
 * „cum adaug un coleg" și „cum conectez OneDrive". Amestecate, ambele se caută
 * prin șase rânduri.
 */
export const NAV_GROUPS: NavGroup[] = [
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
        // Contorul `unmatched` exista de la început, dar nu avea ecran: singurul
        // loc unde apăreau documentele fără client era lista de verificare, unde
        // se amestecau cu o muncă de alt fel. Insigna spunea 7 și lista arăta 11.
        label: "Neatribuite",
        path: "/documente/neatribuite",
        Icon: FileQuestionMark,
        badgeKey: "unmatched",
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
        Icon: ClipboardList,
        permission: "documents:read",
      },
    ],
  },
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
    // Un singur ecran: bara laterală îl arată ca legătură simplă, fără antet de
    // grup. Grupul rămâne aici doar ca formă de date.
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
    label: "Integrări",
    Icon: Cloud,
    items: [
      {
        label: "Surse documente",
        path: "/administrare/surse",
        Icon: Cloud,
        permission: "admin:settings",
      },
      {
        label: "e-Factura",
        path: "/administrare/e-factura",
        Icon: Landmark,
        permission: "admin:settings",
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
