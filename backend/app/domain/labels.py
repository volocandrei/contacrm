"""Cum se numesc stările în românește (§53).

**De ce pe server.** Etichetele au trăit până acum doar în `frontend/src/lib/labels.ts`,
și era în regulă: singurul care le arăta era ecranul. Din momentul în care
**asistentul** vorbește despre un document — „este la verificare", „nu i s-a
identificat clientul" —, textul trebuie compus aici; altfel serverul ar rosti
`REVIEW_REQUIRED`, iar omul ar citi pe ecran „Necesită verificare" și s-ar întreba
dacă vorbesc despre același lucru.

**Ce împiedică divergența.** `test_contract_enums.py` compară perechile de aici cu
cele din `labels.ts`. Două formulări pentru aceeași stare sunt mai rele decât una
imperfectă: cea de-a doua nu se caută în ecran.
"""

from __future__ import annotations

from app.domain.enums import DocumentStatus

#: Starea unui document, spusă cum o citește un contabil pe ecran.
DOCUMENT_STATUS_LABEL: dict[DocumentStatus, str] = {
    DocumentStatus.RECEIVED: "Recepționat",
    DocumentStatus.PROCESSING: "În procesare",
    DocumentStatus.REVIEW_REQUIRED: "Necesită verificare",
    DocumentStatus.APPROVED: "Aprobat",
    DocumentStatus.ARCHIVED: "Arhivat",
    DocumentStatus.ERROR: "Eroare",
    DocumentStatus.DUPLICATE: "Duplicat",
    DocumentStatus.REJECTED: "Respins",
    # Nu „Neatribuit": ecranul spune de ce, nu doar că. Documentul a sosit
    # întreg; ce lipsește este legătura cu un client.
    DocumentStatus.UNMATCHED: "Client neidentificat",
}


def status_label(status: DocumentStatus) -> str:
    return DOCUMENT_STATUS_LABEL.get(status, status.value)


__all__ = ["DOCUMENT_STATUS_LABEL", "status_label"]
