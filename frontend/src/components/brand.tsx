/**
 * Semnul aplicației, într-un singur loc.
 *
 * Trăia în `app-sidebar.tsx`, unde era singurul care îl folosea. Din momentul în
 * care îl poartă și butonul asistentului, două copii ale aceluiași `<path>` ar fi
 * început să se despartă: una s-ar fi schimbat, cealaltă nu, iar diferența s-ar
 * fi văzut abia pe ecran.
 */
import { cn } from "@/lib/utils";

/** Doar semnul. Culoarea o dă `className` (`fill-white`, `fill-blue-600`, …). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 50 39"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("fill-current", className)}
      aria-hidden="true"
    >
      <path d="M16.4992 2H37.5808L22.0816 24.9729H1L16.4992 2Z" />
      <path d="M17.4224 27.102L11.4192 36H33.5008L49 13.0271H32.7024L23.2064 27.102H17.4224Z" />
    </svg>
  );
}

/** Semnul pe pastila lui albastră, cum apare în meniu și pe butonul asistentului. */
export function Logo({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "grid size-10 shrink-0 place-content-center rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 shadow-sm",
        className,
      )}
    >
      <LogoMark className="w-5 text-white" />
    </div>
  );
}
