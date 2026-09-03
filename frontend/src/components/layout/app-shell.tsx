import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Bell, LogOut, Moon, Search, Sun, User } from "lucide-react";
import { useSidebarCounts } from "@/api/hooks";
import { apiMode } from "@/api/client";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { useAuth } from "@/features/auth/use-auth";
import { useTheme } from "@/hooks/use-theme";
import { ALL_NAV_ITEMS } from "@/lib/navigation";

/**
 * Sub această lățime, bara laterală deschisă (256px) nu mai încape.
 *
 * Măsurat pe un ecran de 390px: pagina depășea cu 50px, iar titlul din antet se
 * strângea la lățime zero — adică dispărea. Aplicația este un instrument de birou
 * și desktopul rămâne prioritar, dar un ecran care se rupe nu are nicio scuză.
 */
const NARROW_SCREEN_PX = 900;

function fitsAnOpenSidebar(): boolean {
  // `typeof window` — componenta trebuie să poată fi randată și fără DOM.
  return typeof window === "undefined" || window.innerWidth >= NARROW_SCREEN_PX;
}

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(fitsAnOpenSidebar);
  const { theme, toggleTheme } = useTheme();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { data: counts } = useSidebarCounts();
  const [search, setSearch] = useState("");

  const current =
    ALL_NAV_ITEMS.find((item) => item.path === pathname) ??
    ALL_NAV_ITEMS.filter((item) => item.path !== "/").find((item) =>
      pathname.startsWith(item.path),
    );

  // Rotirea unei tablete sau micșorarea ferestrei nu trebuie să lase bara deschisă
  // peste conținut. Nu forțăm și invers: cine a închis-o pe un ecran lat a închis-o
  // pentru că a vrut.
  useEffect(() => {
    function onResize() {
      if (!fitsAnOpenSidebar()) setSidebarOpen(false);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  function handleSearch(event: React.FormEvent) {
    event.preventDefault();
    if (!search.trim()) return;
    navigate(`/documente/inbox?q=${encodeURIComponent(search.trim())}`);
  }

  return (
    <div className="flex min-h-screen w-full bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      <AppSidebar
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((value) => !value)}
        badges={counts}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between gap-4 border-b border-gray-200 bg-white/90 px-6 backdrop-blur dark:border-gray-800 dark:bg-gray-900/90">
          <h1 className="truncate text-lg font-semibold text-gray-900 dark:text-gray-100">
            {current?.label ?? "ContaCRM"}
          </h1>

          <div className="flex items-center gap-3">
            <form onSubmit={handleSearch} className="relative hidden md:block">
              <label htmlFor="global-search" className="sr-only">
                Caută clienți, documente, CUI
              </label>
              <Search
                className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-gray-400"
                aria-hidden="true"
              />
              <input
                id="global-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Caută client, CUI, număr document…"
                className="h-10 w-72 rounded-lg border border-gray-200 bg-gray-50 pr-3 pl-9 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:bg-white focus:ring-2 focus:ring-blue-500/30 focus:outline-none dark:border-gray-800 dark:bg-gray-950 dark:text-gray-100"
              />
            </form>

            <button
              type="button"
              aria-label={`Notificări${counts ? `: ${counts.review} de verificat` : ""}`}
              onClick={() => navigate("/documente/verificare")}
              className="relative flex h-10 w-10 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-600 transition-colors hover:text-gray-900 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
            >
              <Bell className="h-4 w-4" aria-hidden="true" />
              {(counts?.review ?? 0) > 0 && (
                <span className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-red-500" />
              )}
            </button>

            <button
              type="button"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Comută pe tema deschisă" : "Comută pe tema închisă"}
              className="flex h-10 w-10 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-600 transition-colors hover:bg-gray-50 hover:text-gray-900 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" aria-hidden="true" />
              ) : (
                <Moon className="h-4 w-4" aria-hidden="true" />
              )}
            </button>

            <UserMenu />
          </div>
        </header>

        {apiMode() === "mock" && (
          <p className="border-b border-amber-200 bg-amber-50 px-6 py-1.5 text-center text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-900/20 dark:text-amber-200">
            Mod development — date sintetice, backend simulat în browser
          </p>
        )}

        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = {
  SUPER_ADMIN: "Super administrator",
  ADMIN: "Administrator",
  ACCOUNTANT: "Contabil",
  OPERATOR: "Operator",
  REVIEWER: "Verificator",
  VIEWER: "Vizitator",
};

function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Meniu cont"
        className="flex h-10 w-10 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-600 transition-colors hover:text-gray-900 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
      >
        <User className="h-4 w-4" aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-2 w-60 rounded-lg border border-gray-200 bg-white p-1 shadow-lg dark:border-gray-800 dark:bg-gray-900"
        >
          <div className="border-b border-gray-100 px-3 py-2 dark:border-gray-800">
            <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
              {user?.fullName}
            </p>
            <p className="truncate text-xs text-gray-500 dark:text-gray-400">{user?.email}</p>
            <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
              {user ? (ROLE_LABEL[user.role] ?? user.role) : ""} · {user?.organizationName}
            </p>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => void logout()}
            className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            Deconectare
          </button>
        </div>
      )}
    </div>
  );
}
