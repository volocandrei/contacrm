"""Ce factură a plătit banii aceștia (§13, §14, §17).

**De ce testele astea contează mai mult decât par.** O potrivire greșită nu produce
nicio eroare: produce bani puși pe factura altcuiva. Se descoperă la închiderea
anului, când nimeni nu-și mai amintește ce a fost în martie — sau nu se descoperă
deloc, fiindcă totalurile ies.

De aceea aproape toate testele de mai jos verifică **ce NU se propune**. Un sistem
care propune mult și greșit este mai rău decât unul care tace: contabilul îi
verifică primele zece propuneri, găsește trei greșite, și nu mai deschide ecranul.

Ordinea este a gravității:

1. **Direcția.** O plată nu poate închide o factură emisă. Niciodată.
2. **Un singur semnal slab nu propune nimic** — data plus suma rotundă este exact
   tiparul care leagă factura greșită.
3. **Numărul facturii se caută pe cuvânt întreg**, altfel `7001` se potrivește în
   orice cod de tranzacție.
4. **Motivele sunt obligatorii**: o propunere fără explicație nu se poate verifica.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.domain.bank_matching import (
    MAX_DAYS_APART,
    STRONG_THRESHOLD,
    SUGGEST_THRESHOLD,
    Candidate,
    Movement,
    normalise,
    normalise_tax_id,
    score,
    suggest,
)

WHEN = date(2026, 8, 20)


def payment(**overrides: object) -> Movement:
    """Bani ieșiți: plata unei facturi de la furnizor."""
    values: dict[str, object] = {
        "amount": Decimal("-1190.00"),
        "booking_date": WHEN,
        "description": "Plata factura",
        "counterparty_name": "TERT FURNIZOR SRL",
        "counterparty_iban": "RO49AAAA1B31007593840000",
        "reference": "FCT 7001",
    }
    values.update(overrides)
    return Movement(**values)  # type: ignore[arg-type]


def collection(**overrides: object) -> Movement:
    """Bani intrați: încasarea unei facturi emise."""
    return payment(amount=Decimal("1190.00"), **overrides)


def invoice(**overrides: object) -> Candidate:
    values: dict[str, object] = {
        "document_id": "doc-1",
        "total": Decimal("1190.00"),
        "document_date": date(2026, 8, 14),
        "series": "FCT",
        "number": "7001",
        "partner_name": "Terț Furnizor SRL",
        "partner_tax_id": "RO99887766",
        "is_incoming": True,
    }
    values.update(overrides)
    return Candidate(**values)  # type: ignore[arg-type]


class TestTheDirection:
    def test_a_payment_never_matches_an_issued_invoice(self) -> None:
        """Prima regulă, și cea care nu se discută.

        Bani ieșiți din cont nu pot închide o factură pe care cabinetul a emis-o.
        Fără regula asta, o plată și o încasare de aceeași valoare — lucru banal
        între firme care își facturează reciproc — s-ar lega una de alta.
        """
        assert score(payment(), invoice(is_incoming=False)) is None

    def test_a_collection_never_matches_a_supplier_invoice(self) -> None:
        assert score(collection(), invoice(is_incoming=True)) is None

    def test_the_right_direction_does_match(self) -> None:
        assert score(payment(), invoice(is_incoming=True)) is not None
        assert score(collection(), invoice(is_incoming=False)) is not None


class TestWhatIsNotProposed:
    def test_a_close_date_and_a_round_amount_are_not_enough(self) -> None:
        """Tiparul care leagă factura greșită, și de ce este oprit.

        Două abonamente lunare de aceeași valoare, plătite în aceeași săptămână,
        arată identic. Fără numărul facturii sau fără un al doilea semnal
        independent, sistemul nu are ce să propună — și trebuie să tacă.
        """
        vague = payment(reference=None, description="Plata", counterparty_name=None)

        assert score(vague, invoice(partner_name=None, partner_tax_id=None)) is None

    def test_only_the_name_is_not_enough_either(self) -> None:
        """Un furnizor de la care vin zece facturi pe lună."""
        vague = payment(reference=None, description="Plata catre Tert Furnizor SRL")

        assert score(vague, invoice(total=None, number=None, partner_tax_id=None)) is None

    def test_an_invoice_paid_in_full_is_no_longer_a_candidate(self) -> None:
        """Altfel a doua plată către același furnizor s-ar lega tot de ea."""
        closed = invoice(already_matched=Decimal("1190.00"))

        assert score(payment(), closed) is None

    def test_a_payment_too_far_from_the_invoice_is_not_proposed(self) -> None:
        """O lună și jumătate acoperă termenele obișnuite. Peste, nu mai înseamnă."""
        old = invoice(document_date=date(2026, 1, 5))

        assert score(payment(), old) is None

    def test_the_last_day_inside_the_window_still_counts(self) -> None:
        """Marginea se verifică, nu se presupune."""
        edge = invoice(document_date=WHEN - timedelta(days=MAX_DAYS_APART))

        assert score(payment(), edge) is not None


class TestTheInvoiceNumber:
    def test_the_number_in_the_reference_is_the_strongest_signal(self) -> None:
        """Cine plătește scrie numărul tocmai ca să se știe ce plătește."""
        result = score(payment(), invoice())

        assert result is not None
        assert "numărul facturii apare în plată" in result.reasons
        assert result.is_strong

    def test_a_number_inside_a_longer_number_does_not_count(self) -> None:
        """`7001` nu are voie să se potrivească în `270015`.

        Extrasele sunt pline de coduri lungi — de tranzacție, de terminal, de
        autorizare. Căutarea pe subșir ar fi legat plăți la întâmplare.
        """
        noisy = payment(reference="TRANZACTIE 270015", description=None)

        result = score(noisy, invoice(total=None))

        reasons = result.reasons if result else ()
        assert not any("numărul facturii" in reason for reason in reasons)

    def test_the_series_glued_to_the_number_is_recognised(self) -> None:
        """Băncile scapă spațiile: `FCT7001` este același lucru cu `FCT 7001`."""
        glued = payment(reference="PLATA FCT7001", description=None)
        result = score(glued, invoice())

        assert result is not None
        assert "numărul facturii apare în plată" in result.reasons


class TestTheAmount:
    def test_an_exact_amount_is_a_reason_by_name(self) -> None:
        result = score(payment(), invoice())

        assert result is not None
        assert "sumă exactă" in result.reasons

    def test_a_partial_payment_that_covers_the_rest_is_recognised(self) -> None:
        """A doua tranșă: 690 din 1190, după ce s-au plătit 500.

        Este cazul pe care un model unu-la-unu nu îl poate scrie deloc.
        """
        second = payment(amount=Decimal("-690.00"))
        partial = invoice(already_matched=Decimal("500.00"))

        result = score(second, partial)

        assert result is not None
        assert "acoperă exact restul de plată" in result.reasons

    def test_an_invoice_without_a_total_can_still_match_on_the_number(self) -> None:
        """Suma necitită nu este un semnal negativ — este absența unui semnal."""
        result = score(payment(), invoice(total=None))

        assert result is not None
        assert "sumă exactă" not in result.reasons


class TestTheTaxIdAndTheName:
    def test_the_tax_id_in_the_description_counts(self) -> None:
        with_code = payment(reference=None, description="Plata catre RO 99887766")
        result = score(with_code, invoice())

        assert result is not None
        assert "CUI identic" in result.reasons

    def test_a_short_number_is_not_a_tax_id(self) -> None:
        """Sub șase cifre este un număr oarecare din descriere, nu un CUI."""
        result = score(payment(), invoice(partner_tax_id="12345"))

        assert result is not None
        assert "CUI identic" not in result.reasons

    def test_the_name_matches_across_diacritics_and_legal_form(self) -> None:
        """„Șerbănescu Distribuție S.R.L." și „SERBANESCU DISTRIBUTIE SRL"."""
        movement = payment(counterparty_name="SERBANESCU DISTRIBUTIE SRL")
        candidate = invoice(partner_name="Șerbănescu Distribuție S.R.L.")

        result = score(movement, candidate)

        assert result is not None
        assert "numele partenerului se potrivește" in result.reasons

    def test_one_word_of_the_name_is_not_the_name(self) -> None:
        """„Distribuție" singur ar lega douăzeci de furnizori."""
        movement = payment(
            reference=None, description="Plata Distributie", counterparty_name="Alta Firma SRL"
        )
        candidate = invoice(
            total=None, number=None, partner_name="Șerbănescu Distribuție SRL", partner_tax_id=None
        )

        assert score(movement, candidate) is None


class TestWhatTheAccountantReads:
    def test_every_suggestion_says_why(self) -> None:
        """O propunere fără explicație nu se poate verifica, deci nu se poate folosi."""
        result = score(payment(), invoice())

        assert result is not None
        assert result.reasons
        assert all(reason and not reason.endswith(".") for reason in result.reasons)

    def test_the_reasons_are_ordered_by_weight(self) -> None:
        """Numărul facturii înaintea datei: omul citește primul motiv, nu al treilea."""
        result = score(payment(), invoice())

        assert result is not None
        assert result.reasons[0] == "numărul facturii apare în plată"

    def test_a_strong_match_is_marked_as_such(self) -> None:
        result = score(payment(), invoice())

        assert result is not None
        assert result.is_strong
        # Pragul „aproape sigur" este deasupra celui de propunere, nu lângă el.
        assert STRONG_THRESHOLD > SUGGEST_THRESHOLD


class TestChoosingBetweenCandidates:
    def test_the_invoice_named_in_the_payment_wins_over_the_one_with_the_same_amount(
        self,
    ) -> None:
        """Cazul care justifică ponderile.

        Două facturi de la același furnizor, aceeași sumă, aceeași săptămână. Una
        are numărul scris în ordinul de plată. Aceea este.
        """
        named = invoice(document_id="doc-numit", number="7001")
        other = invoice(document_id="doc-altul", number="7002", document_date=date(2026, 8, 18))

        found = suggest(payment(), [other, named])

        assert found[0].document_id == "doc-numit"

    def test_at_most_five_are_returned(self) -> None:
        """O listă de douăzeci de candidați nu se citește, deci nu ajută."""
        many = [invoice(document_id=f"doc-{index}") for index in range(12)]

        assert len(suggest(payment(), many)) == 5

    def test_nothing_is_returned_when_nothing_fits(self) -> None:
        """Tăcerea este un răspuns, și cel corect mai des decât pare."""
        assert suggest(payment(), [invoice(is_incoming=False)]) == []


class TestNormalisation:
    def test_diacritics_and_legal_forms_disappear(self) -> None:
        assert normalise("Șerbănescu Distribuție S.R.L.") == "serbanescu distributie"
        assert normalise("ALFA CONTA SRL") == "alfa conta"

    def test_an_empty_value_is_an_empty_string_not_a_crash(self) -> None:
        assert normalise(None) == ""
        assert normalise("") == ""
        assert normalise_tax_id(None) == ""

    def test_a_tax_id_is_compared_as_digits(self) -> None:
        assert normalise_tax_id("RO 99887766") == normalise_tax_id("ro99887766") == "99887766"
