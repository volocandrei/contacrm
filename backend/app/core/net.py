"""Cine a făcut cererea, când între el și noi stă un proxy.

Jurnalul de audit notează un IP la fiecare acțiune. În spatele unui proxy —
Vercel, un load balancer, nginx — adresa conexiunii TCP este a proxy-ului, deci
toate intrările ar arăta același IP și auditul nu ar mai răspunde la „de unde".

Antetul `X-Forwarded-For` conține adresa reală, dar oricine poate scrie în el.
De aceea nu se citește niciodată „pentru că există", ci doar când se știe **câte**
proxy-uri de încredere stau în față, și se numără de la dreapta: partea din
dreapta este scrisă de infrastructura noastră, partea din stânga poate fi
inventată de client.
"""

from __future__ import annotations

FORWARDED_FOR = "X-Forwarded-For"


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    *,
    trusted_proxies: int,
) -> str | None:
    """Adresa clientului, sau `None` dacă nu se poate ști.

    `peer` este adresa conexiunii TCP — singura care nu se poate falsifica.
    `trusted_proxies` este numărul de proxy-uri prin care trece **obligatoriu**
    orice cerere (1 pentru Vercel). Zero înseamnă „aplicația este expusă direct":
    antetul se ignoră complet.

    Fiecare proxy adaugă la coadă adresa de la care a primit, deci cu N proxy-uri
    de încredere clientul se află pe poziția a N-a de la dreapta.
    """
    if trusted_proxies <= 0:
        return peer

    hops = [hop.strip() for hop in (forwarded_for or "").split(",") if hop.strip()]
    if len(hops) < trusted_proxies:
        # Lanțul este mai scurt decât cel declarat: cererea nu a venit pe drumul
        # așteptat (sau configurarea este greșită). Într-un caz și în celălalt,
        # adresa conexiunii este singurul lucru pe care îl știm sigur.
        return peer

    return _strip_port(hops[-trusted_proxies])


def _strip_port(hop: str) -> str:
    """`192.0.2.1:54321` → `192.0.2.1`; un IPv6 rămâne întreg.

    Antetul e definit ca listă de adrese, dar unele proxy-uri adaugă și portul.
    Formele IPv6 (`::1`, `[::1]:443`) au ele însele două puncte, deci nu se poate
    tăia la primul: se taie doar când există exact unul.
    """
    if hop.startswith("["):
        host, _, _ = hop.partition("]")
        return host.removeprefix("[")
    return hop.rsplit(":", 1)[0] if hop.count(":") == 1 else hop
