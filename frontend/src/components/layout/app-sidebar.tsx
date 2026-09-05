import { useState } from "react";
import { NavLink } from "react-router-dom";
import { ChevronDown, ChevronsRight } from "lucide-react";
import { divider, pillClass, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import { NAV_GROUPS, NAV_ROOT, type BadgeKey, type NavItem } from "@/lib/navigation";
import { usePermissionCheck } from "@/features/auth/use-auth";

export type SidebarBadges = Partial<Record<BadgeKey, number>>;

type AppSidebarProps = {
  open: boolean;
  onToggle: () => void;
  badges?: SidebarBadges;
};

export function AppSidebar({ open, onToggle, badges = {} }: AppSidebarProps) {
  const has = usePermissionCheck();

  // Meniul arată doar ce se poate deschide. Înainte, un OPERATOR vedea
  // „Utilizatori", „Roluri" și „Setări" — trei uși încuiate, care îl trimiteau
  // într-un 403 și îl lăsau să creadă că aplicația e stricată. Refuzul adevărat
  // rămâne al serverului, la fiecare cerere; asta este doar ergonomie.
  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.permission || has(item.permission)),
    // Un grup rămas fără intrări nu mai are ce să deschidă.
  })).filter((group) => group.items.length > 0);

  return (
    <nav
      aria-label="Navigație principală"
      className={cn(
        "sticky top-0 h-screen shrink-0 border-r p-2 transition-[width] duration-300 ease-in-out",
        "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
        open ? "w-64" : "w-16",
      )}
    >
      <BrandSection open={open} />

      <div className="h-[calc(100vh-9.5rem)] space-y-1 overflow-y-auto pb-2">
        <SidebarLink item={NAV_ROOT} open={open} />

        {groups.map((group) =>
          group.items.length === 1 && group.items[0] ? (
            <SidebarLink key={group.label} item={group.items[0]} open={open} badges={badges} />
          ) : (
            <SidebarGroup
              key={group.label}
              label={group.label}
              open={open}
              pending={pendingIn(group.items, badges)}
            >
              {group.items.map((item) => (
                <SidebarLink key={item.path} item={item} open={open} badges={badges} nested />
              ))}
            </SidebarGroup>
          ),
        )}
      </div>

      <ToggleClose open={open} onToggle={onToggle} />
    </nav>
  );
}

/**
 * Câtă muncă așteaptă în intrările unui grup.
 *
 * Se adună pentru antetul grupului: un grup **închis** ascundea până acum, fără
 * să spună nimic, unsprezece documente neatribuite. Meniul devenea mai curat și
 * mai mincinos în același timp.
 */
function pendingIn(items: NavItem[], badges: SidebarBadges): number {
  return items.reduce((total, item) => total + (item.badgeKey ? (badges[item.badgeKey] ?? 0) : 0), 0);
}

/** Cheia sub care se ține minte ce grupuri sunt strânse. */
const COLLAPSED_KEY = "contacrm.sidebar.collapsed";

function readCollapsed(): string[] {
  // `localStorage` poate lipsi sau arunca: fereastră privată, date de sit
  // blocate, randare fără browser. Meniul trebuie să meargă oricum.
  try {
    const raw = window.localStorage.getItem(COLLAPSED_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

function SidebarGroup({
  label,
  open,
  pending,
  children,
}: {
  label: string;
  open: boolean;
  pending: number;
  children: React.ReactNode;
}) {
  // Strâns sau nu, ținut minte între sesiuni: cine lucrează numai în documente
  // strângea aceleași patru grupuri la fiecare reîncărcare.
  const [expanded, setExpanded] = useState(() => !readCollapsed().includes(label));

  function toggle() {
    const next = !expanded;
    setExpanded(next);
    try {
      const collapsed = new Set(readCollapsed());
      if (next) collapsed.delete(label);
      else collapsed.add(label);
      window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed]));
    } catch {
      // Preferința nu se poate păstra. Meniul funcționează la fel; doar uită.
    }
  }

  // În modul restrâns rămân vizibile doar iconurile, fără antetul grupului.
  if (!open) {
    return <div className="space-y-1 border-t border-slate-100 pt-1 dark:border-slate-800">{children}</div>;
  }

  return (
    <div className="pt-2">
      <button
        onClick={toggle}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-1.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase transition-colors hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300"
      >
        <span className="truncate">{label}</span>
        <span className="flex shrink-0 items-center gap-1.5">
          {/* Numai când grupul e strâns: deschis, cifrele stau pe rândurile lor,
              iar totalul de aici ar fi doar zgomot. */}
          {!expanded && pending > 0 && (
            <span className={pillClass("blue")} title={`${pending} în așteptare`}>
              {pending}
            </span>
          )}
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 transition-transform duration-200",
              !expanded && "-rotate-90",
            )}
            aria-hidden="true"
          />
        </span>
      </button>
      {expanded && <div className="space-y-1">{children}</div>}
    </div>
  );
}

/** Punctul din meniul restrâns, în aceleași culori ca insigna din cel deschis. */
const DOT_TONE: Record<Tone, string> = {
  blue: "bg-blue-500 dark:bg-blue-400",
  red: "bg-red-500 dark:bg-red-400",
  amber: "bg-amber-500 dark:bg-amber-400",
  green: "bg-emerald-500 dark:bg-emerald-400",
  purple: "bg-violet-500 dark:bg-violet-400",
  slate: "bg-slate-400 dark:bg-slate-500",
};

function SidebarLink({
  item,
  open,
  badges = {},
  nested = false,
}: {
  item: NavItem;
  open: boolean;
  badges?: SidebarBadges;
  nested?: boolean;
}) {
  const { Icon, label, path, badgeKey, badgeTone = "blue" } = item;
  const count = badgeKey ? badges[badgeKey] : undefined;

  return (
    <NavLink
      to={path}
      end={path === "/"}
      title={open ? undefined : label}
      className={({ isActive }) =>
        cn(
          "group relative flex h-10 w-full items-center rounded-lg transition-colors duration-200",
          "focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none",
          isActive
            // Accentul stă într-un pseudo-element lipit de margine, nu într-un
            // `border-l`: chenarul împingea iconul cu doi pixeli, iar rândul activ
            // nu se mai alinia cu celelalte.
            ? "bg-blue-50 font-medium text-blue-700 before:absolute before:top-1.5 before:bottom-1.5 before:-left-2 before:w-1 before:rounded-r-full before:bg-blue-500 dark:bg-blue-500/15 dark:text-blue-300 dark:before:bg-blue-400"
            : "text-slate-600 hover:bg-slate-100/70 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200",
        )
      }
    >
      <div className={cn("grid h-full place-content-center", open && nested ? "w-10" : "w-12")}>
        <Icon className="h-4 w-4" aria-hidden="true" />
      </div>

      {open ? (
        <span className="truncate text-sm font-medium">{label}</span>
      ) : (
        <span className="sr-only">{label}</span>
      )}

      {count !== undefined && count > 0 && open && (
        <span className={cn("absolute right-2.5", pillClass(badgeTone))}>{count}</span>
      )}
      {count !== undefined && count > 0 && !open && (
        <span
          className={cn("absolute top-1.5 right-2 h-2 w-2 rounded-full", DOT_TONE[badgeTone])}
          aria-hidden="true"
        />
      )}
    </NavLink>
  );
}

function BrandSection({ open }: { open: boolean }) {
  return (
    <div className="mb-4 border-b border-slate-200 pb-3 dark:border-slate-800">
      <div className="flex items-center gap-3 rounded-md p-2">
        <Logo />
        {open && (
          <div className="min-w-0">
            <span className="block truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              ContaCRM
            </span>
            <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
              Cabinet contabil
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function Logo() {
  return (
    <div className="grid size-10 shrink-0 place-content-center rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 shadow-sm">
      <svg
        width="20"
        viewBox="0 0 50 39"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="fill-white"
        aria-hidden="true"
      >
        <path d="M16.4992 2H37.5808L22.0816 24.9729H1L16.4992 2Z" />
        <path d="M17.4224 27.102L11.4192 36H33.5008L49 13.0271H32.7024L23.2064 27.102H17.4224Z" />
      </svg>
    </div>
  );
}

function ToggleClose({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-expanded={open}
      aria-label={open ? "Restrânge meniul" : "Extinde meniul"}
      className={cn(
        "absolute right-0 bottom-0 left-0 border-t transition-colors hover:bg-slate-100/70 dark:hover:bg-slate-800",
        divider,
      )}
    >
      <div className="flex items-center p-3">
        <div className="grid size-10 place-content-center">
          <ChevronsRight
            className={cn(
              "h-4 w-4 text-slate-500 transition-transform duration-300 dark:text-slate-400",
              open && "rotate-180",
            )}
            aria-hidden="true"
          />
        </div>
        {open && (
          <span className="text-sm font-medium text-slate-600 dark:text-slate-300">Restrânge</span>
        )}
      </div>
    </button>
  );
}
