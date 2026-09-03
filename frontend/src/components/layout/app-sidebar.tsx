import { useState } from "react";
import { NavLink } from "react-router-dom";
import { ChevronDown, ChevronsRight } from "lucide-react";
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
        "sticky top-0 h-screen shrink-0 border-r p-2 shadow-sm transition-[width] duration-300 ease-in-out",
        "border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900",
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
            <SidebarGroup key={group.label} label={group.label} open={open}>
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

function SidebarGroup({
  label,
  open,
  children,
}: {
  label: string;
  open: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(true);

  // În modul restrâns rămân vizibile doar iconurile, fără antetul grupului.
  if (!open) {
    return <div className="space-y-1 border-t border-gray-100 pt-1 dark:border-gray-800">{children}</div>;
  }

  return (
    <div className="pt-2">
      <button
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between rounded-md px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 transition-colors hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
      >
        {label}
        <ChevronDown
          className={cn("h-3.5 w-3.5 transition-transform duration-200", !expanded && "-rotate-90")}
          aria-hidden="true"
        />
      </button>
      {expanded && <div className="space-y-1">{children}</div>}
    </div>
  );
}

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
  const { Icon, label, path, badgeKey } = item;
  const count = badgeKey ? badges[badgeKey] : undefined;

  return (
    <NavLink
      to={path}
      end={path === "/"}
      title={open ? undefined : label}
      className={({ isActive }) =>
        cn(
          "relative flex h-10 w-full items-center rounded-md transition-colors duration-200",
          "focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none",
          isActive
            ? "border-l-2 border-blue-500 bg-blue-50 text-blue-700 shadow-sm dark:bg-blue-900/40 dark:text-blue-300"
            : "text-gray-600 hover:bg-gray-50 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200",
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
        <span className="absolute right-3 flex h-5 min-w-5 items-center justify-center rounded-full bg-blue-500 px-1.5 text-xs font-medium text-white dark:bg-blue-600">
          {count}
        </span>
      )}
      {count !== undefined && count > 0 && !open && (
        <span
          className="absolute top-1.5 right-2 h-2 w-2 rounded-full bg-blue-500 dark:bg-blue-400"
          aria-hidden="true"
        />
      )}
    </NavLink>
  );
}

function BrandSection({ open }: { open: boolean }) {
  return (
    <div className="mb-4 border-b border-gray-200 pb-3 dark:border-gray-800">
      <div className="flex items-center gap-3 rounded-md p-2">
        <Logo />
        {open && (
          <div className="min-w-0">
            <span className="block truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
              ContaCRM
            </span>
            <span className="block truncate text-xs text-gray-500 dark:text-gray-400">
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
      className="absolute right-0 bottom-0 left-0 border-t border-gray-200 transition-colors hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-800"
    >
      <div className="flex items-center p-3">
        <div className="grid size-10 place-content-center">
          <ChevronsRight
            className={cn(
              "h-4 w-4 text-gray-500 transition-transform duration-300 dark:text-gray-400",
              open && "rotate-180",
            )}
            aria-hidden="true"
          />
        </div>
        {open && (
          <span className="text-sm font-medium text-gray-600 dark:text-gray-300">Restrânge</span>
        )}
      </div>
    </button>
  );
}
