"""Solicitarea de documente, ca text gata de trimis.

**De ce stă pe server.** Textul spune numele cabinetului, listează ce lipsește și
dă termenul lunii: este conținut de business, nu formatare de ecran. A stat o
vreme în frontend, unde îl folosea butonul „Copiază solicitarea" de pe ecranul
„Documente lipsă". Din momentul în care îl cere și asistentul, două implementări
ar însemna că doi clienți primesc, în aceeași zi, două mesaje diferite de la
același cabinet.

**Ce nu face.** Nu trimite. Trimiterea cere un provider de email sau WhatsApp și
rămâne în Faza 2. Până atunci, textul iese gata scris și pleacă din clientul de
email al contabilului, cu semnătura lui — ceea ce este, până la Faza 2, chiar mai
onest: niciun mesaj nu pleacă în numele cabinetului fără ca cineva să îl fi citit.

**De ce poartă și linkul de trimitere (M14).** O listă de ce lipsește îi spune
clientului *ce* să caute, dar îl lasă singur cu *cum* trimite: scanează, atașează,
se lovește de limita de mărime a emailului, amână. Cererea și drumul pe care
sosește răspunsul pleacă împreună, într-un singur mesaj — altfel omul primește
sarcina fără unealtă.

Blocul este opțional pentru că nu oricine îl poate compune: linkul se **deschide**,
iar deschiderea cere `documents:write`. Cine doar citește primește tot textul, mai
puțin rândul pe care n-are dreptul să-l creeze.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.domain.periods import ChecklistEntry

#: Numele lunilor, la genitiv-dativ cum cere fraza „pentru luna …".
MONTHS = (
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
)


def month_in_words(reference_month: str) -> str:
    """„2026-08" → „august 2026". Un client nu citește luni numerotate."""
    year, month = reference_month.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def _line(entry: ChecklistEntry) -> str:
    """Câte bucăți mai lipsesc dintr-un tip, nu doar că lipsește.

    „Facturi de achiziție" nu spune nimic unui client care crede că le-a trimis;
    „mai așteptăm 2 (am primit 3 din 5)" spune exact ce are de căutat.
    """
    left = entry.expected_min_count - entry.received_count
    if entry.received_count > 0:
        seen = f"{entry.received_count} din {entry.expected_min_count}"
        detail = f" — mai așteptăm {left} (am primit {seen})"
    else:
        piece = "bucată" if entry.expected_min_count == 1 else "bucăți"
        detail = f" — {entry.expected_min_count} {piece}"
    return f"• {entry.document_type_label}{detail}"


def _upload_block(url: str, expires_on: date | None) -> list[str]:
    """Cum se trimite, imediat după ce s-a spus ce și până când.

    Data expirării se scrie în mesaj pentru că altfel n-o știe nimeni: clientul
    care deschide linkul peste patru luni nu află de ce nu mai merge, iar
    contabilul care i l-a trimis nu-și amintește când l-a deschis.
    """
    lines = [
        "",
        "Cel mai simplu este să le încărcați direct aici, fără cont și fără parolă:",
        url,
    ]
    if expires_on is not None:
        lines.append(f"Linkul este valabil până la {expires_on.strftime('%d.%m.%Y')}.")
    return lines


def build_request_message(
    *,
    client_name: str,
    reference_month: str,
    deadline: date,
    missing: Sequence[ChecklistEntry],
    organization_name: str,
    upload_url: str | None = None,
    upload_expires_on: date | None = None,
) -> str:
    del client_name  # se adresează firmei, nu o numește: mesajul îi este trimis ei
    return "\n".join(
        [
            "Bună ziua,",
            "",
            f"Pentru evidența contabilă a lunii {month_in_words(reference_month)} "
            "mai avem nevoie de următoarele documente:",
            "",
            *[_line(entry) for entry in missing],
            "",
            f"Vă rugăm să ni le transmiteți până la {deadline.strftime('%d.%m.%Y')}, "
            "ca declarațiile să poată fi depuse la timp.",
            *(_upload_block(upload_url, upload_expires_on) if upload_url else []),
            "",
            "Vă mulțumim,",
            organization_name,
        ]
    )
