"""Raportul, ca fișier care se deschide în Excel.

Numerele se vedeau pe ecran și nu puteau ieși din aplicație. Un cabinet care
trebuie să pună situația lunii într-un raport intern, sau s-o trimită cuiva, o
retasta.

**Se agregă tot în SQL, prin același serviciu ca ecranul.** Aici nu se calculează
nimic — se aplatizează ce s-a calculat deja. Două căi de calcul ar fi ajuns,
într-o zi, la două numere diferite pentru aceeași întrebare.

Trei detalii care par mărunte și fără de care fișierul nu se poate folosi în
România:

- **separatorul este `;`**, nu virgulă: cu virgulă, Excel în setările românești
  pune totul într-o singură coloană;
- **BOM la început**: fără el, Excel citește UTF-8 ca ANSI și „Rată" devine
  „RatÄƒ";
- **sfârșit de linie CRLF**, pentru că Windows este destinația.

Valorile trec prin `csv.writer`, care scapă singur ghilimelele și separatorii din
interiorul lor: un client care are `;` în denumire nu are voie să rupă coloanele.
"""

from __future__ import annotations

import csv
import io
from typing import Final

from app.services.report_service import ReportSummary

#: Separatorul așteptat de Excel în setările românești.
DELIMITER: Final = ";"

#: Fără el, Excel citește fișierul ca ANSI și diacriticele se strică.
BOM: Final = "﻿"

#: Windows este destinația.
LINE_ENDING: Final = "\r\n"

HEADER: Final = ("Sectiune", "Cheie", "Eticheta", "Numar")


def rows_for(summary: ReportSummary) -> list[list[str]]:
    """Raportul, aplatizat într-un singur tabel.

    O coloană „secțiune" în loc de patru fișiere separate: patru ar fi cerut o
    arhivă, iar cine vrea numerele într-o foaie de calcul are nevoie de opusul.
    """
    rows: list[list[str]] = [list(HEADER)]

    for label, value in (
        ("Documente în interval", summary.total),
        ("Procesate", summary.processed),
        ("Eșuate", summary.failed),
        ("Duplicate", summary.duplicates),
        ("Clienți", summary.client_count),
    ):
        rows.append(["Total", "", label, str(value)])

    # Gol, nu zero: `null` înseamnă „nu s-a terminat încă nimic", iar zero s-ar
    # citi ca „totul a eșuat". Aceeași distincție ca pe ecran.
    rate = "" if summary.success_rate is None else f"{summary.success_rate:.4f}"
    rows.append(["Total", "", "Rată de succes", rate])

    for section, buckets in (
        ("Status", summary.by_status),
        ("Luna", summary.by_month),
        ("Tip", summary.by_type),
        ("Client", summary.by_client),
    ):
        for bucket in buckets:
            # `key` și `label` sunt amândouă `None` când gruparea este „nimic" —
            # document fără client, fără tip, fără lună. Rămân goale: numele
            # absenței îl dă interfața, nu exportul.
            rows.append([section, bucket.key or "", bucket.label or "", str(bucket.count)])

    return rows


def to_csv(summary: ReportSummary) -> str:
    """Fișierul întreg, gata de trimis ca răspuns."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator=LINE_ENDING)
    writer.writerows(rows_for(summary))
    return BOM + buffer.getvalue()


def filename(from_month: str | None, to_month: str | None) -> str:
    """Numele sub care ajunge fișierul pe disc.

    Poartă intervalul, ca două exporturi succesive să nu se suprascrie în
    „Descărcări" și ca peste o lună să se știe ce conține.
    """
    if not from_month and not to_month:
        return "raport-documente.csv"
    return f"raport-documente-{from_month or 'inceput'}_{to_month or 'azi'}.csv"


__all__ = ["BOM", "DELIMITER", "LINE_ENDING", "filename", "rows_for", "to_csv"]
