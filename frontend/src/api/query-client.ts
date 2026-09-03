/**
 * Configurarea cache-ului, într-un singur loc.
 *
 * Stătea în `main.tsx`, iar testele își făceau propriul `QueryClient`, cu alte
 * valori. Asta însemna că întreaga clasă de defecte legate de cache — o valoare
 * veche rămasă pe ecran, o interogare care nu se reia, un `setQueryData` care
 * ascunde starea adevărată — era invizibilă pentru suita de teste **prin
 * construcție**: testele nu rulau niciodată configurarea aplicației.
 */
import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/types";

/**
 * Cât timp un răspuns este considerat proaspăt.
 *
 * Datele unui cabinet se schimbă în minute, nu în milisecunde; jumătate de minut
 * scutește zeci de cereri la fiecare navigare între ecrane. Documentele în lucru
 * nu depind de asta: `useDocument` cere singur, la interval, cât timp procesarea
 * nu s-a terminat.
 */
export const STALE_TIME_MS = 30_000;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_TIME_MS,
        refetchOnWindowFocus: false,
        // Erorile de autorizare sau de validare nu se rezolvă prin reîncercare.
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status < 500) return false;
          return failureCount < 2;
        },
      },
    },
  });
}
