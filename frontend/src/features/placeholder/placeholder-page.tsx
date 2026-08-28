import { Construction } from "lucide-react";

/**
 * Ecran temporar pentru modulele care urmează în milestone-urile 3–8.
 * Există ca shell-ul să fie navigabil integral din prima zi.
 */
export function PlaceholderPage({ title, milestone }: { title: string; milestone: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="max-w-md rounded-xl border border-dashed border-gray-300 bg-white p-10 text-center shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <div className="mx-auto mb-4 grid h-12 w-12 place-content-center rounded-lg bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400">
          <Construction className="h-6 w-6" aria-hidden="true" />
        </div>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h2>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Modulul este planificat pentru {milestone}. Structura de navigație și layout-ul sunt deja
          în funcțiune.
        </p>
      </div>
    </div>
  );
}
