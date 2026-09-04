import { useEffect, useState } from "react";
import { FileCode2, FileText, ImageOff, LoaderCircle, TriangleAlert } from "lucide-react";
import { apiMode, fetchFile } from "@/api/client";
import { ApiError } from "@/api/types";
import { formatDate, formatMoney } from "@/lib/format";
import type { DocumentDetail } from "@/types/domain";

/**
 * Previzualizarea documentului.
 *
 * Fișierele nu sunt niciodată expuse public (§51): în modul `http` conținutul vine
 * de la un endpoint autorizat, nu de la o cale de filesystem.
 * În modul `mock` nu există fișiere reale, așa că randăm un facsimil generat din
 * datele extrase — util pentru testarea fluxului de verificare, marcat explicit ca simulare.
 */
export function DocumentPreview({ document }: { document: DocumentDetail }) {
  if (apiMode() === "http") {
    // `key` pe id: la schimbarea documentului vrem o instanță nouă, nu una care
    // mai ține pentru o clipă `blob:` URL-ul celui precedent.
    return <StoredDocument key={document.id} document={document} />;
  }
  return <SimulatedDocument document={document} />;
}

/** O factură electronică este XML: structurată, dar fără nimic de privit. */
const STRUCTURED_MIME_TYPES = new Set(["application/xml", "text/xml"]);

/**
 * Conținutul real, citit autentificat.
 *
 * Nu punem calea direct în `src`: un `<img>` sau `<object>` nu trimite antetul
 * `Authorization`, iar un token în query string ar ajunge în logurile serverului, în
 * istoricul browserului și în `Referer` (§27). Citim cu `fetch` — care duce
 * cookie-ul și antetul — și dăm elementului un `blob:` URL, valabil doar în fila
 * curentă.
 */
function StoredDocument({ document }: { document: DocumentDetail }) {
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const structured = STRUCTURED_MIME_TYPES.has(document.mimeType);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;

    void fetchFile(`/documents/${document.id}/preview`, controller.signal)
      .then(async (file) => {
        if (controller.signal.aborted) return;
        // Un XML nu se dă unui `<object>`: browserul l-ar arăta ca arbore, ceea
        // ce nu ajută pe nimeni. Se citește ca text și se randează dedesubt.
        if (structured) {
          setText(await file.blob.text());
          return;
        }
        objectUrl = URL.createObjectURL(file.blob);
        setUrl(objectUrl);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Conținutul documentului nu a putut fi încărcat.",
        );
      });

    return () => {
      controller.abort();
      // Fără asta, fiecare document deschis rămâne în memoria filei.
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document.id, structured]);

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-slate-500 dark:text-slate-400">
        <TriangleAlert className="h-8 w-8" aria-hidden="true" />
        <p className="text-sm font-medium">{error}</p>
        <p className="text-xs">Datele extrase rămân disponibile în panoul din dreapta.</p>
      </div>
    );
  }

  if (!url && text === null) {
    return (
      <div
        role="status"
        className="flex h-full items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400"
      >
        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
        Se încarcă documentul…
      </div>
    );
  }

  if (structured) {
    return <StructuredInvoice document={document} source={text ?? ""} />;
  }

  if (document.mimeType.startsWith("image/")) {
    return (
      <img
        src={url!}
        alt={`Previzualizare ${document.originalFilename}`}
        className="max-h-full w-full object-contain"
      />
    );
  }

  return (
    <object data={url!} type={document.mimeType} className="h-full w-full">
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-slate-500">
        <FileText className="h-8 w-8" aria-hidden="true" />
        Previzualizarea nu poate fi afișată în această fereastră. Folosește butonul
        „Descarcă”.
      </div>
    </object>
  );
}

/**
 * O factură electronică, așa cum ar citi-o un om.
 *
 * XML-ul nu are facsimil — nu există hârtie în spatele lui. Ce vede operatorul
 * este aceeași factură, redată din câmpurile ei, plus documentul original la un
 * clic distanță. Banda de sus spune limpede care este care: redarea este a
 * noastră, originalul este ce s-a depus la ANAF, iar el rămâne neatins (§16).
 */
function StructuredInvoice({
  document,
  source,
}: {
  document: DocumentDetail;
  source: string;
}) {
  return (
    <div className="flex h-full flex-col">
      <p className="flex items-center justify-center gap-1.5 border-b border-dashed border-blue-300 bg-blue-50 px-3 py-1.5 text-center text-xs text-blue-800 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-200">
        <FileCode2 className="h-3.5 w-3.5" aria-hidden="true" />
        Factură electronică — redare din câmpurile documentului. Originalul este XML.
      </p>

      <div className="flex-1 overflow-auto bg-slate-100 p-6 dark:bg-slate-950">
        <InvoiceFacsimile document={document} />
      </div>

      <details className="border-t border-slate-200 bg-white px-4 py-2 text-xs dark:border-slate-800 dark:bg-slate-900">
        <summary className="cursor-pointer font-medium text-slate-600 dark:text-slate-400">
          Documentul original (XML)
        </summary>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-slate-500 dark:text-slate-400">
          {source}
        </pre>
      </details>
    </div>
  );
}

/** Factura desenată din câmpurile ei — aceeași pentru XML și pentru demonstrație. */
function InvoiceFacsimile({ document }: { document: DocumentDetail }) {
  const { fields } = document;
  const currency = fields.currency.value ?? "RON";

  return (
    <div className="mx-auto max-w-lg rounded-sm bg-white p-8 shadow-lg dark:bg-slate-100">
      <div className="mb-6 flex items-start justify-between gap-4 border-b border-slate-300 pb-4">
        <div>
          <p className="text-[10px] tracking-widest text-slate-500 uppercase">Furnizor</p>
          <p className="text-sm font-bold text-slate-900">{fields.supplierName.value ?? "—"}</p>
          <p className="text-xs text-slate-600">{fields.supplierTaxId.value ?? ""}</p>
        </div>
        <FileText className="h-8 w-8 text-slate-300" aria-hidden="true" />
      </div>

      <h4 className="mb-1 text-center text-base font-bold tracking-wide text-slate-900 uppercase">
        {document.documentTypeLabel ?? "Document"}
      </h4>
      <p className="mb-6 text-center text-xs text-slate-600">
        Seria {fields.series.value ?? "—"} nr. {fields.documentNumber.value ?? "—"} ·{" "}
        {fields.documentDate.value ? formatDate(fields.documentDate.value) : "fără dată"}
      </p>

      <div className="mb-6">
        <p className="text-[10px] tracking-widest text-slate-500 uppercase">Cumpărător</p>
        <p className="text-sm font-semibold text-slate-900">{fields.customerName.value ?? "—"}</p>
        <p className="text-xs text-slate-600">{fields.customerTaxId.value ?? ""}</p>
      </div>

      <table className="w-full border-t border-slate-300 text-xs">
        <tbody className="divide-y divide-slate-200">
          <tr>
            <td className="py-2 text-slate-600">Subtotal</td>
            <td className="py-2 text-right font-medium text-slate-900">
              {fields.subtotal.value ? formatMoney(fields.subtotal.value, currency) : "—"}
            </td>
          </tr>
          <tr>
            <td className="py-2 text-slate-600">TVA</td>
            <td className="py-2 text-right font-medium text-slate-900">
              {fields.vatAmount.value ? formatMoney(fields.vatAmount.value, currency) : "—"}
            </td>
          </tr>
          <tr>
            <td className="py-2 text-sm font-bold text-slate-900">Total</td>
            <td className="py-2 text-right text-sm font-bold text-slate-900">
              {fields.totalAmount.value ? formatMoney(fields.totalAmount.value, currency) : "—"}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function SimulatedDocument({ document }: { document: DocumentDetail }) {
  const failed = document.status === "ERROR";

  return (
    <div className="flex h-full flex-col">
      <p className="border-b border-dashed border-amber-300 bg-amber-50 px-3 py-1.5 text-center text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
        Previzualizare simulată — în modul mock nu există fișiere reale
      </p>

      <div className="flex-1 overflow-auto bg-slate-100 p-6 dark:bg-slate-950">
        {failed ? (
          <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-3 text-center text-slate-500 dark:text-slate-400">
            <ImageOff className="h-10 w-10" aria-hidden="true" />
            <p className="text-sm font-medium">Documentul nu a putut fi citit</p>
            <p className="text-xs">
              OCR-ul a eșuat pentru {document.originalFilename}. Reîncarcă documentul sau
              completează manual datele.
            </p>
          </div>
        ) : (
          <InvoiceFacsimile document={document} />
        )}
      </div>

      {document.ocr.textPreview && (
        <details className="border-t border-slate-200 bg-white px-4 py-2 text-xs dark:border-slate-800 dark:bg-slate-900">
          <summary className="cursor-pointer font-medium text-slate-600 dark:text-slate-400">
            Text OCR ({document.ocr.provider})
          </summary>
          <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap text-slate-500 dark:text-slate-400">
            {document.ocr.textPreview}
          </pre>
        </details>
      )}
    </div>
  );
}
