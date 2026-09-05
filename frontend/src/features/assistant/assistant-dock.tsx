/**
 * Butonul asistentului și fereastra lui, jos-dreapta.
 *
 * **De ce s-a mutat.** Stătea ca o iconiță în antet, între notificări și temă —
 * unde nimeni nu caută un chat. Colțul din dreapta jos este locul în care îl
 * caută oricine a mai folosit o aplicație cu asistent, iar un instrument pe care
 * trebuie să-l descoperi este un instrument nefolosit.
 *
 * **De ce poartă semnul aplicației.** O iconiță de robot spune „aici este un
 * chatbot", ceea ce în 2026 nu mai este o promisiune. Semnul spune al cui este
 * asistentul și că răspunde din datele cabinetului, nu de pe internet.
 *
 * **De ce nu întunecă ecranul.** Întrebarea „ce lipsește la Alfa Conta?" se pune
 * *în timp ce* te uiți la altceva. Fereastra modală de dinainte îți lua exact
 * ecranul de pe care veneai.
 */
import { X } from "lucide-react";
import { LogoMark } from "@/components/brand";
import { AssistantPanel } from "@/features/assistant/assistant-panel";
import { focusRing } from "@/lib/ui";
import { cn } from "@/lib/utils";

export function AssistantDock({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <>
      <AssistantPanel open={open} onClose={() => onOpenChange(false)} />

      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        aria-expanded={open}
        // Eticheta se schimbă cu starea: același buton face două lucruri, iar
        // cine îl aude citit nu vede că fereastra este deja deschisă.
        aria-label={open ? "Închide asistentul (Ctrl J)" : "Deschide asistentul (Ctrl J)"}
        title="Asistent — Ctrl J"
        className={cn(
          "fixed right-4 bottom-4 z-40 grid size-14 place-content-center rounded-full",
          "bg-gradient-to-br from-blue-500 to-blue-600 text-white shadow-lg",
          "transition-transform hover:scale-105 active:scale-95",
          focusRing,
        )}
      >
        {open ? (
          <X className="h-6 w-6" aria-hidden="true" />
        ) : (
          <LogoMark className="w-6" />
        )}
      </button>
    </>
  );
}
