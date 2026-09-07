"""XML-ul și PDF-ul aceleiași facturi (§16, §17).

**Ce se apără, în ordinea gravității.**

1. **Conflictul nu se ascunde.** Identitate identică, sume diferite: una dintre
   valori este citită greșit. Este cazul care merită cel mai mult atenția și cel
   mai ușor de îngropat sub o potrivire „reușită".
2. **Nu se leagă nimic pe o coincidență.** Fără numărul facturii nu există
   pereche; serii diferite înseamnă facturi diferite.
3. **Se leagă singur numai pe identitatea legală completă** — CUI, serie, număr,
   sumă. Orice lipsă coboară la „probabil", iar acolo decide un om.
4. **Două exemplare de același fel nu sunt o pereche.** Sunt un duplicat, și au
   modulul lor.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.domain.efactura_pairing import (
    MAX_DAYS_APART,
    Identity,
    PairingState,
    compare,
    evaluate,
)

WHEN = date(2026, 8, 14)


def xml(**overrides: object) -> Identity:
    """Factura electronică: valori exacte, citite din elemente cu nume."""
    values: dict[str, object] = {
        "document_id": "xml-1",
        "is_electronic": True,
        "supplier_tax_id": "RO99887766",
        "series": "FCT",
        "number": "7001",
        "total": Decimal("1190.00"),
        "document_date": WHEN,
    }
    values.update(overrides)
    return Identity(**values)  # type: ignore[arg-type]


def pdf(**overrides: object) -> Identity:
    """Exemplarul clasic: aceleași date, citite de pe hârtie."""
    values: dict[str, object] = {"document_id": "pdf-1", "is_electronic": False}
    values.update(overrides)
    return xml(**values)


class TestWhenItPairs:
    def test_the_same_invoice_in_both_forms_is_one_pair(self) -> None:
        """Rostul întreg: XML-ul din SPV și PDF-ul de pe email."""
        result = evaluate(xml(), [pdf()])

        assert result.state is PairingState.MATCHED
        assert result.certain is not None
        assert result.certain.document_id == "pdf-1"

    def test_the_reasons_are_the_legal_identity(self) -> None:
        """Ce se arată omului: după ce anume s-au legat cele două."""
        pairing = compare(xml(), pdf())

        assert pairing is not None
        assert "același număr de factură" in pairing.reasons
        assert "aceeași serie" in pairing.reasons
        assert "CUI furnizor identic" in pairing.reasons
        assert "aceeași sumă" in pairing.reasons

    def test_a_day_of_difference_is_still_the_same_invoice(self) -> None:
        """Un ERP care rotunjește fusul orar scrie altă zi pe PDF."""
        result = evaluate(xml(), [pdf(document_date=date(2026, 8, 15))])

        assert result.state is PairingState.MATCHED

    def test_pairing_works_from_either_side(self) -> None:
        """Ordinea în care sosesc nu contează: XML-ul poate veni al doilea."""
        assert evaluate(pdf(), [xml()]).state is PairingState.MATCHED


class TestWhenItRefuses:
    def test_two_documents_of_the_same_kind_are_never_a_pair(self) -> None:
        """Două XML-uri cu aceeași identitate sunt un duplicat, nu o pereche."""
        assert compare(xml(), xml(document_id="xml-2")) is None
        assert compare(pdf(), pdf(document_id="pdf-2")) is None

    def test_a_different_number_is_a_different_invoice(self) -> None:
        assert compare(xml(), pdf(number="7002")) is None

    def test_a_different_series_is_a_different_invoice(self) -> None:
        """Fiecare furnizor își are seria lui; numerele se repetă între ele."""
        assert compare(xml(), pdf(series="AAA")) is None

    def test_a_different_tax_id_is_a_different_supplier(self) -> None:
        assert compare(xml(), pdf(supplier_tax_id="RO11112222")) is None

    def test_dates_too_far_apart_are_not_the_same_invoice(self) -> None:
        far = pdf(document_date=date(2026, 8, 14 + MAX_DAYS_APART + 1))

        assert compare(xml(), far) is None

    def test_nothing_found_is_not_an_error(self) -> None:
        """Majoritatea documentelor nu au pereche, și este în regulă."""
        result = evaluate(xml(), [pdf(number="9999")])

        assert result.state is PairingState.MISSING
        assert result.candidates == ()


class TestTheConflict:
    def test_the_same_invoice_with_different_amounts_is_shown_not_hidden(self) -> None:
        """Cazul cel mai important din modul.

        Aceeași factură, aceeași serie, același număr, alt total: una dintre
        valori este citită greșit. O potrivire „reușită" ar fi ascuns tocmai
        diferența — iar ea ajunge în decont.
        """
        result = evaluate(xml(), [pdf(total=Decimal("1900.00"))])

        assert result.state is PairingState.CONFLICT
        assert result.certain is None
        assert any("sume diferite" in reason for reason in result.candidates[0].reasons)

    def test_a_conflict_wins_over_a_good_match(self) -> None:
        """Dacă există un exemplar cu altă sumă, aceea este informația."""
        result = evaluate(xml(), [pdf(), pdf(document_id="pdf-2", total=Decimal("1900.00"))])

        assert result.state is PairingState.CONFLICT

    def test_a_penny_of_difference_is_still_a_conflict(self) -> None:
        """Fără toleranță, deliberat: o factură este aceeași sumă, la bănuț."""
        result = evaluate(xml(), [pdf(total=Decimal("1190.01"))])

        assert result.state is PairingState.CONFLICT


class TestWhenAHumanMustDecide:
    def test_a_missing_tax_id_lowers_it_to_probable(self) -> None:
        """Se propune, nu se leagă: lipsește o bucată din identitatea legală."""
        result = evaluate(xml(), [pdf(supplier_tax_id=None)])

        assert result.state is PairingState.PROBABLE
        assert result.certain is None

    def test_a_missing_amount_lowers_it_too(self) -> None:
        result = evaluate(xml(), [pdf(total=None)])

        assert result.state is PairingState.PROBABLE

    def test_two_equally_good_candidates_are_both_shown(self) -> None:
        """A alege unul ar fi o monedă aruncată."""
        result = evaluate(xml(), [pdf(), pdf(document_id="pdf-2")])

        assert result.state is PairingState.MULTIPLE_CANDIDATES
        assert len(result.candidates) == 2
        assert result.certain is None

    def test_every_candidate_says_why(self) -> None:
        """O propunere fără motive nu se poate verifica, deci nu se poate accepta."""
        result = evaluate(xml(), [pdf(supplier_tax_id=None)])

        assert all(item.reasons for item in result.candidates)
