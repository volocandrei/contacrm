import { useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Bell, LogOut, Moon, Search, Sun, User } from "lucide-react";
import { CommandPalette } from "@/components/command-palette";
import { useSidebarCounts } from "@/api/hooks";
import { apiMode } from "@/api/client";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { useAuth } from "@/features/auth/use-auth";
import { useTheme } from "@/hooks/use-theme";
import { ROLE_LABEL } from "@/lib/labels";
import { ALL_NAV_ITEMS, NAV_GROUPS } from "@/lib/navigation";
import { divider, focusRing, iconButton, pageBackground } from "@/lib/ui";
import { cn } from "@/lib/utils";

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
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Grupul din care face parte ecranul curent. Antetul spunea doar numele
  // ecranului — „Setări", „Roluri" —, iar în aplicații cu multe ecrane numele
  // singur nu spune unde ești.
  const section = NAV_GROUPS.find((group) =>
    group.items.some((item) => pathname === item.path || pathname.startsWith(`${item.path}/`)),
  )?.label;

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

  /**
   * Ctrl+K deschide paleta de oriunde.
   *
   * `preventDefault` este obligatoriu: în unele browsere combinația mută cursorul
   * în bara de adrese, iar paleta s-ar deschide fără să poată primi ce se scrie.
   */
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className={cn("flex min-h-screen w-full", pageBackground)}>
      <AppSidebar
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((value) => !value)}
        badges={counts}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className={cn(
            "sticky top-0 z-10 flex h-16 items-center justify-between gap-4 border-b px-6",
            // Translucid plus `backdrop-blur`: conținutul care trece pe sub antet
            // rămâne sugerat, nu tăiat brusc.
            "bg-white/80 backdrop-blur-md dark:bg-slate-900/80",
            divider,
          )}
        >
          <div className="min-w-0">
            {section && (
              <p className="text-[11px] font-medium tracking-wide text-slate-400 uppercase dark:text-slate-500">
                {section}
              </p>
            )}
            <h1 className="truncate text-base font-semibold tracking-tight text-slate-900 dark:text-slate-100">
              {current?.label ?? "ContaCRM"}
            </h1>
          </div>

          <div className="flex items-center gap-3">
            {/* Un buton, nu un câmp: câmpul promitea o căutare pe loc, dar orice
                s-ar fi scris în el ducea în inboxul de documente — un client căutat
                după CUI nu avea cum să apară. Scurtătura stă scrisă pe buton,
                fiindcă o scurtătură pe care n-o știe nimeni nu există. */}
            <button
              type="button"
              onClick={() => setPaletteOpen(true)}
              className={cn(
                "hidden h-10 w-72 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm text-slate-500 transition-colors hover:bg-slate-100 md:flex dark:border-slate-800 dark:bg-slate-950 dark:text-slate-400 dark:hover:bg-slate-800",
                focusRing,
              )}
            >
              <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="flex-1 text-left">Caută client, CUI, document…</span>
              <kbd className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] dark:border-slate-700">
                Ctrl K
              </kbd>
            </button>

            <button
              type="button"
              aria-label={`Notificări${counts ? `: ${counts.review} de verificat` : ""}`}
              onClick={() => navigate("/documente/verificare")}
              className={cn(iconButton, "relative")}
            >
              <Bell className="h-4 w-4" aria-hidden="true" />
              {(counts?.review ?? 0) > 0 && (
                <span className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-white dark:ring-slate-900" />
              )}
            </button>

            <button
              type="button"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Comută pe tema deschisă" : "Comută pe tema închisă"}
              className={iconButton}
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

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}

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
        className={iconButton}
      >
        <User className="h-4 w-4" aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-2 w-60 rounded-lg border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="border-b border-slate-100 px-3 py-2 dark:border-slate-800">
            <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
              {user?.fullName}
            </p>
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">{user?.email}</p>
            <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
              {user ? (ROLE_LABEL[user.role] ?? user.role) : ""} · {user?.organizationName}
            </p>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => void logout()}
            className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            Deconectare
          </button>
        </div>
      )}
    </div>
  );
}
