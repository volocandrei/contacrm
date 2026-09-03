"""Ce IP ajunge în jurnalul de audit.

Auditul răspunde la „cine, ce, când, de unde". Ultima parte are două moduri de a
minti, și amândouă sunt tăcute: în spatele unui proxy, adresa TCP este a
proxy-ului, deci toate intrările arată identic; iar dacă `X-Forwarded-For` se
citește fără să știm cine l-a scris, oricare client își alege ce IP vrea să
apară în jurnal.
"""

from __future__ import annotations

import pytest

from app.core.net import resolve_client_ip

PEER = "10.0.0.7"


class TestExposedDirectly:
    """Implicit: aplicația vede clientul, deci antetul nu are ce să adauge."""

    def test_the_connection_address_is_used(self) -> None:
        assert resolve_client_ip(PEER, None, trusted_proxies=0) == PEER

    def test_the_header_is_ignored_entirely(self) -> None:
        """Fără un proxy în față, antetul e scris chiar de client."""
        assert resolve_client_ip(PEER, "203.0.113.9", trusted_proxies=0) == PEER

    def test_without_a_connection_we_say_nothing(self) -> None:
        """Un `None` cinstit; nu ghicim din antet ca să umplem coloana."""
        assert resolve_client_ip(None, "203.0.113.9", trusted_proxies=0) is None


class TestBehindOneProxy:
    """Cazul Vercel, nginx, un load balancer."""

    def test_the_client_is_read_from_the_header(self) -> None:
        assert resolve_client_ip(PEER, "203.0.113.9", trusted_proxies=1) == "203.0.113.9"

    def test_a_forged_prefix_cannot_win(self) -> None:
        """Clientul a trimis el însuși un antet; proxy-ul a adăugat adresa reală.

        Se numără de la dreapta exact pentru asta: partea din dreapta e scrisă de
        infrastructura noastră, partea din stânga poate fi orice.
        """
        forged = "1.2.3.4, 5.6.7.8"
        assert resolve_client_ip(PEER, f"{forged}, 203.0.113.9", trusted_proxies=1) == "203.0.113.9"

    def test_a_missing_header_falls_back_to_the_connection(self) -> None:
        """Cererea nu a venit pe drumul declarat — sau configurarea e greșită."""
        assert resolve_client_ip(PEER, None, trusted_proxies=1) == PEER
        assert resolve_client_ip(PEER, "   ", trusted_proxies=1) == PEER

    def test_spacing_does_not_matter(self) -> None:
        assert resolve_client_ip(PEER, "1.2.3.4,203.0.113.9", trusted_proxies=1) == "203.0.113.9"


class TestBehindTwoProxies:
    """Fiecare proxy adaugă la coadă adresa de la care a primit."""

    def test_the_client_is_two_hops_from_the_right(self) -> None:
        chain = "203.0.113.9, 198.51.100.1"
        assert resolve_client_ip(PEER, chain, trusted_proxies=2) == "203.0.113.9"

    def test_a_chain_shorter_than_declared_is_not_trusted(self) -> None:
        """Un singur hop unde se așteptau două: adresa ar fi scrisă de client."""
        assert resolve_client_ip(PEER, "203.0.113.9", trusted_proxies=2) == PEER


class TestPortsAndIPv6:
    """Antetul e definit ca listă de adrese, dar unele proxy-uri adaugă portul."""

    def test_a_port_is_dropped(self) -> None:
        assert resolve_client_ip(PEER, "203.0.113.9:54321", trusted_proxies=1) == "203.0.113.9"

    @pytest.mark.parametrize(
        ("hop", "expected"),
        [
            ("2001:db8::1", "2001:db8::1"),
            ("[2001:db8::1]:443", "2001:db8::1"),
            ("::1", "::1"),
        ],
    )
    def test_ipv6_survives_intact(self, hop: str, expected: str) -> None:
        """Un IPv6 are el însuși două puncte: tăierea la primul l-ar distruge."""
        assert resolve_client_ip(PEER, hop, trusted_proxies=1) == expected
