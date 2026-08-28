import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Filtrele stau în URL, ca o listă filtrată să poată fi salvată sau trimisă unui coleg.
 * Orice schimbare de filtru readuce paginarea la prima pagină.
 */
export function useFilterParams<T extends Record<string, string>>(defaults: T) {
  const [searchParams, setSearchParams] = useSearchParams();

  const values = useMemo(() => {
    const result = { ...defaults };
    for (const key of Object.keys(defaults) as Array<keyof T>) {
      const fromUrl = searchParams.get(String(key));
      if (fromUrl !== null) result[key] = fromUrl as T[keyof T];
    }
    return result;
  }, [defaults, searchParams]);

  const setValue = useCallback(
    (key: keyof T, value: string) => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (value) next.set(String(key), value);
          else next.delete(String(key));
          if (key !== "page") next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const reset = useCallback(() => {
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [setSearchParams]);

  const activeCount = useMemo(
    () =>
      (Object.keys(defaults) as Array<keyof T>).filter(
        (key) => key !== "page" && values[key] !== defaults[key],
      ).length,
    [defaults, values],
  );

  return { values, setValue, reset, activeCount };
}
