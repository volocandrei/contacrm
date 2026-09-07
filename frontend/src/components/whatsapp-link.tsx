/**
 * Un număr de WhatsApp care se poate apăsa.
 *
 * **De ce o componentă și nu un `<a>` scris de fiecare dată.** Regula care
 * decide dacă numărul poate deveni link (`whatsappHref`) trebuie aplicată la fel
 * peste tot: un ecran care afișează linkul și altul care afișează text pentru
 * același contact ar face pe cineva să creadă că datele diferă.
 *
 * **Trei stări, nu două.** Fără număr — o liniuță, ca la orice câmp gol. Cu un
 * număr care nu poate fi un telefon — numărul ca text, fiindcă el este ce a
 * scris omul acolo și nu avem dreptul să-l ascundem. Cu un număr bun — linkul.
 * Ce nu există este a patra stare, cea în care un link stricat se deschide într-o
 * pagină de eroare.
 */
import { MessageCircle } from "lucide-react";
import { whatsappHref } from "@/lib/whatsapp";

export function WhatsAppLink({ number }: { number: string | null | undefined }) {
  const href = whatsappHref(number);
  if (!number) return <>—</>;
  if (!href) return <>{number}</>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      title="Deschide conversația pe WhatsApp"
      className="inline-flex items-center gap-1 text-emerald-700 hover:underline dark:text-emerald-400"
    >
      <MessageCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      {number}
    </a>
  );
}
