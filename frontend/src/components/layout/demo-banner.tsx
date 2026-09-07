import { apiMode } from "@/api/client";

/**
 * Banda din capul demonstrației: ce se pierde și ce nu se introduce (§24).
 *
 * **De ce are fișier propriu.** Nu ca să fie ordine, ci ca să se poată randa
 * într-un test. Cât timp stătea în `AppShell`, singurul mod de a-i verifica
 * textul era să construiești tot antetul — router, sesiune, cozi de cereri —
 * pentru trei rânduri de HTML, așa că nimeni nu l-a verificat, iar textul greșit
 * a stat acolo până l-a găsit un om.
 *
 * **Ce scria înainte:** „Mod development — date sintetice, backend simulat în
 * browser". Adevărat, dar descrie **seed-ul**. Cine citește înțelege „datele de
 * pe ecran sunt inventate" și adaugă liniștit un client al lui. Reîncarcă pagina,
 * iar clientul nu mai este acolo: backendul simulat trăiește în memoria filei și
 * moare odată cu ea.
 *
 * Exact asta s-a reclamat — „nu îmi apare în această listă clientul adăugat de
 * mine mai devreme". Aplicația nu pierduse nimic; nu avusese niciodată unde să
 * pună. Banda trebuie să spună **consecința**, nu categoria.
 *
 * Al doilea motiv, mai serios decât primul: cine crede că demonstrația păstrează
 * date poate introduce în ea datele fiscale reale ale unei firme — într-o pagină
 * publică, fără backend și fără nicio obligație de păstrare.
 */
export function DemoBanner() {
  if (apiMode() !== "mock") return null;

  return (
    <p
      role="status"
      className="border-b border-amber-300 bg-amber-100 px-6 py-2 text-center text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-100"
    >
      <strong className="font-semibold">Demonstrație</strong> — backend simulat în browser.{" "}
      <strong className="font-semibold">Ce adaugi aici se pierde la reîncărcarea paginii.</strong>{" "}
      Nu introduce date reale de client.
    </p>
  );
}
