import { useCallback, useState } from "react";
import { apiMode, fetchFile } from "@/api/client";
import { ApiError } from "@/api/types";
import { buildDocumentFilename } from "@/lib/filename";
import type { DocumentDetail, DocumentFile } from "@/types/domain";

/**
 * Descărcarea unui document.
 *
 * Nu este un simplu `<a href>`: ruta cere autentificare, iar un token în URL este
 * interzis (§27). Citim conținutul cu `fetch` și îl salvăm dintr-un `blob:` URL.
 *
 * Numele îl propune serverul, în `Content-Disposition` — el este cel care
 * standardizează denumirea (§29). Îl recalculăm local doar dacă antetul lipsește.
 */
export function useDownloadDocument() {
  const [isPending, setPending] = useState(false);

  const download = useCallback(async (document: DocumentDetail) => {
    if (apiMode() === "mock") {
      throw new ApiError(
        "NOT_FOUND",
        "În modul simulat nu există fișiere reale de descărcat.",
        404,
      );
    }

    setPending(true);
    try {
      const file = await fetchFile(`/documents/${document.id}/download`);
      const url = URL.createObjectURL(file.blob);
      try {
        const anchor = window.document.createElement("a");
        anchor.href = url;
        anchor.download = file.filename ?? fallbackName(document);
        window.document.body.append(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        // Revocarea imediată ar putea prinde salvarea înainte să pornească.
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } finally {
      setPending(false);
    }
  }, []);

  /**
   * Un fișier care însoțește documentul — arhiva ANAF, PDF-ul oficial.
   *
   * Contează cel mai mult pentru arhiva cu sigiliul ANAF: la un control, ea este
   * dovada că factura a fost acceptată, iar spre deosebire de PDF nu se poate
   * reface din nimic. Numele îl propune tot serverul, ca la document.
   */
  const downloadFile = useCallback(async (document: DocumentDetail, file: DocumentFile) => {
    if (apiMode() === "mock") {
      throw new ApiError(
        "NOT_FOUND",
        "În modul simulat nu există fișiere reale de descărcat.",
        404,
      );
    }

    setPending(true);
    try {
      const fetched = await fetchFile(`/documents/${document.id}/files/${file.id}`);
      const url = URL.createObjectURL(fetched.blob);
      try {
        const anchor = window.document.createElement("a");
        anchor.href = url;
        anchor.download = fetched.filename ?? `${document.id}-${file.kind}`;
        window.document.body.append(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } finally {
      setPending(false);
    }
  }, []);

  return { download, downloadFile, isPending };
}

function fallbackName(document: DocumentDetail): string {
  if (document.storedFilename) return document.storedFilename;
  const fields = document.fields;
  return buildDocumentFilename({
    documentDate: fields.documentDate.value,
    documentTypeLabel: document.documentTypeLabel,
    clientName: document.clientName,
    series: fields.series.value,
    documentNumber: fields.documentNumber.value,
    originalFilename: document.originalFilename,
    mimeType: document.mimeType,
  });
}
