"""Arhiva unei perioade: documentele și registrul, într-un singur fișier.

**Golul pe care îl umple.** Documentele se puteau descărca doar unul câte unul.
Un client care pleacă, o predare de an, o cerere de la un control — toate cer
teancul întreg, iar teancul întreg însemna sute de clicuri.

**Ce conține.** Aceleași documente ca registrul lunii, cu registrul însuși pus la
rădăcină. Cine deschide arhiva peste doi ani găsește și fișierele, și lista care
spune ce sunt: fără ea, un dosar cu patru sute de PDF-uri este o grămadă, nu o
arhivă.

**Cum sunt aranjate.** `Client/YYYY-MM/nume`, fiindcă așa le caută un om — după
firmă, apoi după lună. Numele fișierului este cel standardizat, dacă documentul a
ajuns în arhivă; altfel cel original. Un nume inventat aici ar fi al treilea, iar
al treilea nume pentru același document este cum se pierde un document.

**Ce nu face.** Nu ascunde nimic tăcut. Dacă un fișier lipsește din stocare, în
arhivă intră o linie despre el în `LIPSESC.txt`, nu o absență pe care nimeni n-o
observă până la un control.

**De ce are limite.** Un an întreg al unui cabinet cu treizeci de clienți poate
însemna zeci de mii de fișiere și câțiva gigaocteți. Arhiva se compune pe disc,
nu în memorie, dar tot trebuie compusă înainte de a pleca: peste praguri, ruta
refuză cu un mesaj care spune ce interval să ceară, în loc să blocheze serverul.
"""

from __future__ import annotations

import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from tempfile import SpooledTemporaryFile
from typing import IO

from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.domain.filenames import sanitize_path_label
from app.models.document import Document
from app.services import document_register
from app.services.document_delivery import safe_filename
from app.services.document_register import RegisterService
from app.services.storage import ObjectNotFoundError, StorageProvider

logger = get_logger(__name__)

#: Câte documente încap într-o arhivă cerută dintr-o dată.
#:
#: Peste atât, aproape sigur cineva a cerut un an în loc de o lună. Refuzul spune
#: asta; o arhivă de zece mii de fișiere ar fi fost compusă zece minute și n-ar fi
#: ajuns nicăieri.
MAX_DOCUMENTS = 2_000

#: Cât poate cântări, în octeți. Peste, același refuz.
MAX_TOTAL_BYTES = 500 * 1024 * 1024

#: Cât ține în memorie înainte de a trece pe disc.
_SPOOL_BYTES = 16 * 1024 * 1024

#: Numele registrului din arhivă. Fără el, dosarul este o grămadă de fișiere.
REGISTER_NAME = "registru.csv"

#: Unde se scriu documentele al căror fișier lipsește din stocare.
MISSING_NAME = "LIPSESC.txt"


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """Un document și locul lui în arhivă."""

    path: str
    document: Document


def _folder(client_name: str | None, reference_month: str | None) -> str:
    """`Client/YYYY-MM`, cu numele curățat de ce nu are voie într-o cale.

    Documentele fără client sau fără lună nu se pierd: merg în dosare numite
    explicit, nu la rădăcină, unde s-ar amesteca cu registrul.
    """
    client = sanitize_path_label(client_name) if client_name else "Fără client"
    month = reference_month or "Fără lună"
    return f"{client or 'Fără client'}/{month}"


def _unique(path: str, taken: set[str]) -> str:
    """Același nume de două ori ar suprascrie tăcut primul fișier în arhivă."""
    if path not in taken:
        taken.add(path)
        return path
    stem, _, suffix = path.rpartition(".")
    for index in range(2, 1000):
        candidate = f"{stem} ({index}).{suffix}" if stem else f"{path} ({index})"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise ValidationError(
        "Prea multe fișiere cu același nume.", {"clientId": ["Restrânge cererea."]}
    )


class MonthArchiveService:
    def __init__(
        self, session: Session, storage: StorageProvider, organization_id: uuid.UUID
    ) -> None:
        self.session = session
        self.storage = storage
        self.organization_id = organization_id

    def plan(
        self,
        *,
        from_month: str | None,
        to_month: str | None,
        client_id: uuid.UUID | None,
    ) -> tuple[list[ArchiveEntry], list[document_register.RegisterRow]]:
        """Ce intră în arhivă, verificat înainte de a citi vreun octet.

        Se decide întâi **ce**, apoi se citește. Invers, un refuz pentru mărime ar
        veni după ce jumătate din fișiere au fost deja copiate degeaba.
        """
        service = RegisterService(self.session, self.organization_id)
        rows = service.rows(from_month=from_month, to_month=to_month, client_id=client_id)
        documents = service.documents(from_month=from_month, to_month=to_month, client_id=client_id)

        if not documents:
            raise ValidationError(
                "Nu există documente în intervalul cerut.",
                {"fromMonth": ["Alege alt interval."]},
            )
        if len(documents) > MAX_DOCUMENTS:
            raise ValidationError(
                f"Prea multe documente pentru o singură arhivă ({len(documents)}). "
                f"Cere cel mult {MAX_DOCUMENTS} — de obicei o lună, sau un singur client.",
                {"fromMonth": ["Restrânge intervalul."]},
            )

        total = sum(document.file_size for _, document in documents)
        if total > MAX_TOTAL_BYTES:
            raise ValidationError(
                f"Arhiva ar depăși {MAX_TOTAL_BYTES // (1024 * 1024)} MB. "
                "Cere un interval mai scurt sau un singur client.",
                {"fromMonth": ["Restrânge intervalul."]},
            )

        # `safe_filename`, nu `stored_filename or original_filename`: numele venit
        # de la cel care a incarcat fisierul nu are voie sa devina o cale.
        # Un document trimis prin portal cu numele `../../../ceva.pdf` ar fi
        # ajuns intrare de ZIP cu tot cu `..`, iar la dezarhivare un program care
        # nu curata caile l-ar fi scris in afara dosarului ales (zip slip).
        #
        # Este aceeasi functie cu cea de la descarcare, si asta era gaura: aceeasi
        # expresie era pazita pe un drum si luata bruta pe celalalt. Ca efect
        # secundar bun, fisierul din arhiva se numeste acum exact ca cel descarcat
        # separat — al treilea nume pentru acelasi document nu mai exista.
        taken: set[str] = set()
        entries = [
            ArchiveEntry(
                path=_unique(
                    f"{_folder(client_name, document.reference_month)}/{safe_filename(document)}",
                    taken,
                ),
                document=document,
            )
            for client_name, document in documents
        ]
        return entries, rows

    def build(
        self, entries: list[ArchiveEntry], rows: list[document_register.RegisterRow]
    ) -> IO[bytes]:
        """Compune arhiva și o întoarce deschisă la început.

        **Pe disc, nu în memorie.** `SpooledTemporaryFile` ține în RAM doar cât
        încape; peste atât trece singur pe disc. O arhivă de câteva sute de
        megaocteți ținută întreagă în memorie ar fi doborât procesul exact când
        cineva cere ce are nevoie.
        """
        # Fără context manager, deliberat: fișierul supraviețuiește funcției și se
        # închide în `chunks`, după ce ultimul octet a plecat spre client. Închis
        # aici, răspunsul ar fi rămas fără conținut.
        buffer = SpooledTemporaryFile(max_size=_SPOOL_BYTES)  # noqa: SIM115
        missing: list[str] = []

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(REGISTER_NAME, document_register.to_csv(rows))
            for entry in entries:
                key = entry.document.archive_key or entry.document.storage_key
                try:
                    with archive.open(entry.path, "w") as target:
                        for chunk in self.storage.iter_chunks(key):
                            target.write(chunk)
                except ObjectNotFoundError:
                    # Nu se ascunde: o absență tăcută se descoperă la un control.
                    # Calea de stocare nu ajunge în fișier (§73).
                    logger.error("archive_file_missing", document_id=str(entry.document.id))
                    missing.append(entry.path)

            if missing:
                archive.writestr(
                    MISSING_NAME,
                    "Documentele de mai jos există în evidență, dar fișierul lor "
                    "nu a putut fi citit din stocare:\r\n\r\n" + "\r\n".join(missing) + "\r\n",
                )

        buffer.seek(0)
        return buffer


def chunks(source: IO[bytes], size: int = 64 * 1024) -> Iterator[bytes]:
    """Arhiva, în bucăți, ca răspunsul să nu treacă întreg prin memorie."""
    try:
        while True:
            block = source.read(size)
            if not block:
                return
            yield block
    finally:
        source.close()


def filename(from_month: str | None, to_month: str | None) -> str:
    if not from_month and not to_month:
        return "arhiva-documente.zip"
    if from_month == to_month:
        return f"arhiva-documente-{from_month}.zip"
    return f"arhiva-documente-{from_month or 'inceput'}_{to_month or 'azi'}.zip"


__all__ = [
    "MAX_DOCUMENTS",
    "MAX_TOTAL_BYTES",
    "MISSING_NAME",
    "REGISTER_NAME",
    "ArchiveEntry",
    "MonthArchiveService",
    "chunks",
    "filename",
]
