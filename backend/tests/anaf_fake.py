"""Un SPV fals, în memorie.

**Nu putem chema ANAF din niciun test.** Autorizarea cere un certificat digital
calificat prezentat fizic de browser, iar mediul de test al ANAF îl cere la fel.
Tot ce contează trebuie deci să poată fi exercitat prin protocolul din
`app/services/anaf/base.py`, iar acesta este partenerul de dialog.

Falsul este deliberat **strict**: refuză un token greșit, refuză un CUI fără
împuternicire, numără descărcările. Un fals permisiv ar face testele să treacă și
integrarea să cadă la prima cerere reală.

Toate facturile sunt sintetice (§70): nicio factură reală nu intră în depozit.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.enums import EFacturaMessageKind
from app.services.anaf.base import (
    AnafAuthError,
    AnafError,
    AnafMandateError,
    AnafTokens,
    SpvMessage,
    SpvPage,
)

VALID_REFRESH = "anaf-refresh-token-valid"
VALID_CODE = "cod-de-autorizare-anaf"

UBL = (
    'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
    'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
    'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
)

#: Un PDF minimal, valid pentru verificarea pe octeți din client și storage.
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def invoice_xml(
    *,
    number: str = "FCT 7001",
    supplier: str = "Tert Furnizor SRL",
    supplier_tax_id: str = "RO99887766",
    customer: str = "Alfa Conta SRL",
    customer_tax_id: str = "RO10000101",
    issue_date: str = "2026-08-14",
    total: str = "1190.00",
) -> bytes:
    """O factură electronică sintetică, în forma pe care o dă ANAF."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice {UBL}>
  <cbc:ID>{number}</cbc:ID>
  <cbc:IssueDate>{issue_date}</cbc:IssueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>RON</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyLegalEntity>
      <cbc:RegistrationName>{supplier}</cbc:RegistrationName>
      <cbc:CompanyID>{supplier_tax_id}</cbc:CompanyID>
    </cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyLegalEntity>
      <cbc:RegistrationName>{customer}</cbc:RegistrationName>
      <cbc:CompanyID>{customer_tax_id}</cbc:CompanyID>
    </cac:PartyLegalEntity>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="RON">190.00</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:TaxExclusiveAmount currencyID="RON">1000.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="RON">{total}</cbc:TaxInclusiveAmount>
  </cac:LegalMonetaryTotal>
</Invoice>""".encode()


def signature_xml(message_id: str) -> bytes:
    """Sigiliul ANAF. Forma exactă nu contează aici — contează că nu e o factură."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">'
        f"<SignatureValue>semnatura-{message_id}</SignatureValue></Signature>"
    ).encode()


def anaf_zip(
    message_id: str = "3001",
    *,
    invoice: bytes | None = None,
    with_signature: bool = True,
    extra: dict[str, bytes] | None = None,
) -> bytes:
    """Arhiva pe care o întoarce `descarcare`, cu numele pe care le folosește ANAF."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if invoice is not None:
            archive.writestr(f"{message_id}.xml", invoice)
        if with_signature:
            archive.writestr(f"semnatura_{message_id}.xml", signature_xml(message_id))
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def message(
    message_id: str,
    *,
    kind: EFacturaMessageKind = EFacturaMessageKind.RECEIVED,
    tax_id: str = "10000101",
    created_at: datetime | None = None,
) -> SpvMessage:
    return SpvMessage(
        id=message_id,
        kind=kind,
        tax_id=tax_id,
        created_at=created_at or datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
        detail=f"Factura cu id_incarcare={message_id}",
    )


@dataclass
class FakeAnafClient:
    """Implementarea de test a protocolului SPV."""

    #: CUI → mesajele pe care le are ANAF pentru el.
    messages: dict[str, list[SpvMessage]] = field(default_factory=dict)
    #: `id_descarcare` → arhiva ZIP.
    archives: dict[str, bytes] = field(default_factory=dict)
    #: CUI-urile pentru care **nu** avem împuternicire.
    without_mandate: set[str] = field(default_factory=set)
    #: Ce s-a descărcat, în ordine. Testele verifică **ce nu** s-a descărcat.
    downloaded: list[str] = field(default_factory=list)
    #: Câte conversii XML→PDF s-au cerut.
    rendered: int = 0
    #: Se pune pe `True` ca să simulăm certificatul retras.
    revoked: bool = False
    #: Se pune pe `True` ca să simulăm convertorul public indisponibil.
    converter_down: bool = False
    #: Se pune pe `True` ca să simulăm ANAF picat la listare.
    listing_fails: bool = False
    #: Mai are pagini în fereastră.
    has_more: bool = False

    # ── Pregătire ───────────────────────────────────────────────────────────

    def put_invoice(
        self,
        message_id: str,
        *,
        tax_id: str = "10000101",
        kind: EFacturaMessageKind = EFacturaMessageKind.RECEIVED,
        invoice: bytes | None = None,
        archive: bytes | None = None,
        created_at: datetime | None = None,
    ) -> SpvMessage:
        """O factură completă: mesajul în listă și arhiva la descărcare."""
        entry = message(message_id, kind=kind, tax_id=tax_id, created_at=created_at)
        self.messages.setdefault(tax_id, []).append(entry)
        self.archives[message_id] = archive or anaf_zip(
            message_id, invoice=invoice or invoice_xml()
        )
        return entry

    def put_message(self, entry: SpvMessage, *, archive: bytes | None = None) -> None:
        self.messages.setdefault(entry.tax_id, []).append(entry)
        if archive is not None:
            self.archives[entry.id] = archive

    # ── Protocol ────────────────────────────────────────────────────────────

    def _check(self, refresh_token: str) -> None:
        if self.revoked:
            raise AnafAuthError("Certificatul nu mai autorizează. Autorizează din nou.")
        if refresh_token != VALID_REFRESH:
            raise AnafAuthError("Token invalid. Autorizează din nou.")

    def exchange_code(self, code: str, redirect_uri: str) -> AnafTokens:
        if code != VALID_CODE:
            raise AnafAuthError("ANAF a refuzat autorizarea: cod invalid.")
        return AnafTokens(
            access_token="anaf-access-token",
            refresh_token=VALID_REFRESH,
            refresh_expires_in=365 * 24 * 3600,
        )

    def list_messages(
        self,
        refresh_token: str,
        *,
        tax_id: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> SpvPage:
        self._check(refresh_token)
        if self.listing_fails:
            raise AnafError("ANAF a răspuns 503.", retryable=True)
        if tax_id in self.without_mandate:
            raise AnafMandateError(tax_id)

        window = [
            entry
            for entry in self.messages.get(tax_id, [])
            if entry.created_at is None or start <= entry.created_at <= end
        ]
        return SpvPage(messages=tuple(window[:limit]), has_more=self.has_more)

    def download(self, refresh_token: str, *, message_id: str) -> bytes:
        self._check(refresh_token)
        self.downloaded.append(message_id)
        archive = self.archives.get(message_id)
        if archive is None:
            raise AnafError("ANAF nu a dat arhiva: mesaj inexistent.", retryable=False)
        return archive

    def render_pdf(self, invoice_xml: bytes) -> bytes:
        if self.converter_down:
            raise AnafError("Convertorul ANAF nu a răspuns.", retryable=True)
        self.rendered += 1
        return PDF
