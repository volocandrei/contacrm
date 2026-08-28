import { FileText, ImageOff } from "lucide-react";
import { apiMode } from "@/api/client";
import { formatDate, formatMoney } from "@/lib/format";
import type { DocumentDetail } from "@/types/domain";

/**
 * Previzualizarea documentului.
 *
 * Fișierele nu sunt niciodată expuse public (§23): în modul `http` conținutul vine
 * de la un endpoint autorizat, nu de la o cale de filesystem.
 * În modul `mock` nu există fișiere reale, așa că randăm un facsimil generat din
 * datele extrase — util pentru testarea fluxului de verificare, marcat explicit ca simulare.
 */
export function DocumentPreview({ document }: { document: DocumentDetail }) {
  if (apiMode() === "http") {
    const previewUrl = `/api/v1/documents/${document.id}/preview`;
    return document.mimeType.startsWith("image/") ? (
      <img
        src={previewUrl}
        alt={`Previzualizare ${document.originalFilename}`}
        className="max-h-full w-full object-contain"
      />
    ) : (
      <object data={previewUrl} type={document.mimeType} className="h-full w-full">
        <p className="p-6 text-sm text-gray-500">
          Previzualizarea nu poate fi afișată.{" "}
          <a href={previewUrl} className="text-blue-600 underline">
            Descarcă documentul
          </a>
          .
        </p>
      </object>
    );
  }

  return <SimulatedDocument document={document} />;
}

function SimulatedDocument({ document }: { document: DocumentDetail }) {
  const { fields } = document;
  const failed = document.status === "ERROR";

  return (
    <div className="flex h-full flex-col">
      <p className="border-b border-dashed border-amber-300 bg-amber-50 px-3 py-1.5 text-center text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
        Previzualizare simulată — în modul mock nu există fișiere reale
      </p>

      <div className="flex-1 overflow-auto bg-gray-100 p-6 dark:bg-gray-950">
        {failed ? (
          <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-3 text-center text-gray-500 dark:text-gray-400">
            <ImageOff className="h-10 w-10" aria-hidden="true" />
            <p className="text-sm font-medium">Documentul nu a putut fi citit</p>
            <p className="text-xs">
              OCR-ul a eșuat pentru {document.originalFilename}. Reîncarcă documentul sau
              completează manual datele.
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-lg rounded-sm bg-white p-8 shadow-lg dark:bg-gray-100">
            <div className="mb-6 flex items-start justify-between gap-4 border-b border-gray-300 pb-4">
              <div>
                <p className="text-[10px] tracking-widest text-gray-500 uppercase">Furnizor</p>
                <p className="text-sm font-bold text-gray-900">{fields.supplierName.value ?? "—"}</p>
                <p className="text-xs text-gray-600">{fields.supplierTaxId.value ?? ""}</p>
              </div>
              <FileText className="h-8 w-8 text-gray-300" aria-hidden="true" />
            </div>

            <h4 className="mb-1 text-center text-base font-bold tracking-wide text-gray-900 uppercase">
              {document.documentTypeLabel ?? "Document"}
            </h4>
            <p className="mb-6 text-center text-xs text-gray-600">
              Seria {fields.series.value ?? "—"} nr. {fields.documentNumber.value ?? "—"} ·{" "}
              {fields.documentDate.value ? formatDate(fields.documentDate.value) : "fără dată"}
            </p>

            <div className="mb-6">
              <p className="text-[10px] tracking-widest text-gray-500 uppercase">Cumpărător</p>
              <p className="text-sm font-semibold text-gray-900">{fields.customerName.value ?? "—"}</p>
              <p className="text-xs text-gray-600">{fields.customerTaxId.value ?? ""}</p>
            </div>

            <table className="w-full border-t border-gray-300 text-xs">
              <tbody className="divide-y divide-gray-200">
                <tr>
                  <td className="py-2 text-gray-600">Subtotal</td>
                  <td className="py-2 text-right font-medium text-gray-900">
                    {fields.subtotal.value
                      ? formatMoney(fields.subtotal.value, fields.currency.value ?? "RON")
                      : "—"}
                  </td>
                </tr>
                <tr>
                  <td className="py-2 text-gray-600">TVA</td>
                  <td className="py-2 text-right font-medium text-gray-900">
                    {fields.vatAmount.value
                      ? formatMoney(fields.vatAmount.value, fields.currency.value ?? "RON")
                      : "—"}
                  </td>
                </tr>
                <tr>
                  <td className="py-2 text-sm font-bold text-gray-900">Total</td>
                  <td className="py-2 text-right text-sm font-bold text-gray-900">
                    {fields.totalAmount.value
                      ? formatMoney(fields.totalAmount.value, fields.currency.value ?? "RON")
                      : "—"}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>

      {document.ocr.textPreview && (
        <details className="border-t border-gray-200 bg-white px-4 py-2 text-xs dark:border-gray-800 dark:bg-gray-900">
          <summary className="cursor-pointer font-medium text-gray-600 dark:text-gray-400">
            Text OCR ({document.ocr.provider})
          </summary>
          <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-gray-500 dark:text-gray-400">
            {document.ocr.textPreview}
          </pre>
        </details>
      )}
    </div>
  );
}
