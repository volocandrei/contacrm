"""Despachetarea arhivei primite de la ANAF.

`descarcare` întoarce un ZIP, nu o factură. Înăuntru stau, de regulă, două
fișiere XML: factura propriu-zisă și `semnatura_….xml` — sigiliul electronic al
ANAF, adică **dovada că factura a fost acceptată**. Amândouă se păstrează: XML-ul
este documentul, arhiva întreagă este dovada.

**Arhiva nu se rescrie niciodată.** Fișierul ZIP se stochează exact cum a venit,
octet cu octet. Despachetarea de aici doar *citește* din el, ca să scoatem
XML-ul pe care îl citește extracția. Un ZIP recompus de noi ar avea alt hash și
ar înceta să mai fie o dovadă.

**Un ZIP din afară este cod ostil până la proba contrară.** Nu scriem niciun
membru pe disc, deci traversarea de cale nu are unde să ajungă; dar o arhivă
mică se poate desface în gigabaiți, așa că se citește cu limită și se refuză
peste ea. Ca la `defusedxml` în `domain/efactura.py`: refuzăm, nu curățăm.

**Nu orice descărcare este o factură.** Pentru o factură respinsă, ANAF pune în
arhivă un raport de erori, nu un document. Cazul acela iese de aici ca eroare
explicită, cu textul raportului — nu ca „XML invalid", care ar trimite pe cineva
să caute un defect la noi.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Final

from app.domain import efactura

#: Câte fișiere are voie să conțină o arhivă ANAF. În realitate sunt două; zece
#: lasă loc de schimbări fără să lase loc unei arhive cu zece mii de intrări.
MAX_MEMBERS: Final = 10

#: Cât are voie să ocupe un membru desfăcut, și cât toată arhiva. O factură
#: electronică are zeci de kiloocteți; pragurile sunt cu trei ordine de mărime
#: peste, deci nu resping niciun caz real.
MAX_MEMBER_BYTES: Final = 8 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 16 * 1024 * 1024

#: Prefixul cu care ANAF numește sigiliul. Este o convenție, nu un contract, deci
#: nu ne bazăm doar pe el: alegerea finală o dă parsarea.
SIGNATURE_PREFIX: Final = "semnatura"


class AnafArchiveError(Exception):
    """Arhiva nu conține o factură electronică pe care o putem citi."""


@dataclass(frozen=True, slots=True)
class AnafArchive:
    """Ce am scos din arhivă. Arhiva însăși rămâne separat, nemodificată."""

    #: Factura, în UBL 2.1. Octeții din arhivă, nu o reserializare.
    invoice_xml: bytes
    invoice_name: str
    #: Sigiliul ANAF. Lipsește la o factură care încă nu a fost sigilată — se
    #: notează, nu se refuză: documentul există și trebuie văzut de contabil.
    signature_name: str | None = None
    #: Factura citită, ca să nu fie parsată a doua oară de apelant.
    invoice: efactura.EInvoice | None = None


def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos:
        raise AnafArchiveError("Arhiva primită de la ANAF este goală.")
    if len(infos) > MAX_MEMBERS:
        raise AnafArchiveError(f"Arhiva are {len(infos)} fișiere, peste limita de {MAX_MEMBERS}.")

    total = sum(info.file_size for info in infos)
    if total > MAX_TOTAL_BYTES:
        raise AnafArchiveError("Arhiva se desface în prea mulți octeți pentru o factură.")
    return infos


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Citește un membru, cu limita aplicată la **citire**, nu la antet.

    Mărimea declarată în antetul ZIP este o afirmație a celui care a scris
    arhiva. Se citește un octet peste limită și se refuză dacă a venit: așa
    limita ține și când antetul minte.
    """
    with archive.open(info) as handle:
        payload = handle.read(MAX_MEMBER_BYTES + 1)
    if len(payload) > MAX_MEMBER_BYTES:
        raise AnafArchiveError(f"Fișierul {info.filename!r} din arhivă depășește limita.")
    return payload


def _is_signature(name: str) -> bool:
    return name.rsplit("/", 1)[-1].lower().startswith(SIGNATURE_PREFIX)


def unpack(payload: bytes) -> AnafArchive:
    """Scoate factura din arhiva ANAF. Aruncă `AnafArchiveError` dacă nu e una."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise AnafArchiveError(f"Răspunsul ANAF nu este o arhivă ZIP validă: {exc}") from exc

    with archive:
        infos = _members(archive)

        # Sigiliul se recunoaște după nume; factura, după conținut. Ordinea
        # contează: dacă ANAF ar schimba convenția de numire, factura tot ar fi
        # găsită, pentru că singurul criteriu care decide este parsarea.
        signature = next((info for info in infos if _is_signature(info.filename)), None)
        candidates = [info for info in infos if info is not signature]

        problems: list[str] = []
        for info in candidates:
            content = _read(archive, info)
            if not efactura.looks_like_xml(content[:64]):
                problems.append(f"{info.filename}: nu este XML")
                continue
            try:
                invoice = efactura.parse(content)
            except efactura.EFacturaError as exc:
                problems.append(f"{info.filename}: {exc}")
                continue
            return AnafArchive(
                invoice_xml=content,
                invoice_name=info.filename.rsplit("/", 1)[-1][:512],
                signature_name=(
                    signature.filename.rsplit("/", 1)[-1][:512] if signature is not None else None
                ),
                invoice=invoice,
            )

    raise AnafArchiveError(
        "Arhiva ANAF nu conține o factură electronică. "
        + ("; ".join(problems) if problems else "Nu are niciun fișier XML.")
    )


__all__ = ["AnafArchive", "AnafArchiveError", "unpack"]
