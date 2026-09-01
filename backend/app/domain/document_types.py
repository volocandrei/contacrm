"""Tipurile de document implicite (§6).

Tipurile trăiesc în tabelul `document_types` și se administrează de acolo — lista
de aici este doar **conținutul inițial**, încărcat la crearea unei organizații,
la fel cum `permissions.py` alimentează tabelele de roluri.

Câmpurile obligatorii sunt cele fără de care documentul nu poate fi aprobat (§17).
Sunt deliberat puține: un bon fiscal nu are furnizor cu CUI, iar un contract nu are
total. A cere totul peste tot ar transforma verificarea într-un obstacol.

TODO — BUSINESS RULE REQUIRES ACCOUNTING VALIDATION: lista de câmpuri obligatorii
per tip trebuie confirmată de un contabil.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DocumentTypeSeed:
    code: str
    label: str
    required_fields: tuple[str, ...] = field(default=())


# Ordinea este cea în care apar în interfață.
DEFAULT_DOCUMENT_TYPES: tuple[DocumentTypeSeed, ...] = (
    DocumentTypeSeed(
        "FACTURA_INTRARE",
        "Factură intrare",
        ("documentDate", "documentNumber", "supplierName", "totalAmount"),
    ),
    DocumentTypeSeed(
        "FACTURA_IESIRE",
        "Factură ieșire",
        ("documentDate", "documentNumber", "customerName", "totalAmount"),
    ),
    DocumentTypeSeed("EXTRAS_CONT", "Extras cont", ("documentDate", "supplierName")),
    DocumentTypeSeed("BON_FISCAL", "Bon fiscal", ("documentDate", "totalAmount")),
    DocumentTypeSeed("CHITANTA", "Chitanță", ("documentDate", "totalAmount")),
    DocumentTypeSeed("CONTRACT", "Contract", ("documentDate",)),
    DocumentTypeSeed("OP", "Ordin de plată", ("documentDate",)),
    DocumentTypeSeed("NOTA_CONTABILA", "Notă contabilă", ("documentDate",)),
    DocumentTypeSeed("DOCUMENT_BANCAR", "Document bancar", ("documentDate",)),
    # Tipul de refugiu: nu cere nimic, ca un document neclasificabil să poată totuși
    # fi arhivat în loc să blocheze fluxul.
    DocumentTypeSeed("ALTE_DOCUMENTE", "Alte documente", ()),
)

DEFAULT_DOCUMENT_TYPE_CODES: frozenset[str] = frozenset(t.code for t in DEFAULT_DOCUMENT_TYPES)

# Tipul folosit când clasificarea nu poate decide.
FALLBACK_DOCUMENT_TYPE_CODE = "ALTE_DOCUMENTE"
