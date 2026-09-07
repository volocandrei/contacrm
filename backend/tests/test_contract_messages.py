"""Ce scrie ecranul că trimite aplicația, și ce trimite ea de fapt.

**De ce există.** Ecranul „Șabloane de notificare" arăta trei mesaje inventate —
o confirmare de primire, una pe WhatsApp, un reminder — dintre care niciunul nu
exista în backend. Cine le citea credea că le poate aștepta. Ecranul le arată
acum pe cele două reale, dar o previzualizare scrisă de mână se desparte de
original la prima reformulare, iar despărțirea nu se vede: ecranul continuă să
arate corect, doar că altceva.

Testul leagă cele două. Nu compară mesajul întreg — previzualizarea este
prescurtată deliberat — ci **frazele care poartă înțelesul**: dacă una dintre ele
se schimbă în backend, previzualizarea trebuie schimbată odată cu ea, altfel
testul cade.

Aceeași idee ca la enumerările partajate cu frontend-ul (`test_contract_enums`):
autoritatea este backendul, copia este a frontendului, iar despărțirea lor este
un eșec, nu o surpriză.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREEN = REPO_ROOT / "frontend" / "src" / "features" / "communication" / "communication-pages.tsx"

#: Frazele solicitării de documente, cu sursa lor.
REQUEST_PHRASES = (
    "Pentru evidența contabilă a lunii",
    "mai avem nevoie de următoarele documente:",
    "ca declarațiile să poată fi depuse la timp.",
    "Cel mai simplu este să le încărcați direct aici, fără cont și fără parolă:",
)

#: Frazele reamintirii. Deschiderea ei este singura parte care o deosebește de
#: prima solicitare — restul mesajului este același, deliberat: clientul trebuie
#: să vadă aceeași listă, nu una rescrisă.
REMINDER_PHRASES = ("V-am scris pe", "reamintim ce mai așteptăm:")

#: Frazele rezumatului zilnic.
DIGEST_PHRASES = ("Bună dimineața,", "declarații nedepuse")


@pytest.fixture(scope="module")
def screen_source() -> str:
    return SCREEN.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def request_source() -> str:
    return (REPO_ROOT / "backend" / "app" / "services" / "document_request.py").read_text(
        encoding="utf-8"
    )


@pytest.fixture(scope="module")
def digest_source() -> str:
    return (REPO_ROOT / "backend" / "app" / "services" / "daily_digest.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("phrase", REQUEST_PHRASES)
def test_the_request_preview_quotes_the_real_message(
    phrase: str, screen_source: str, request_source: str
) -> None:
    assert phrase in request_source, f"fraza nu mai există în backend: {phrase}"
    assert phrase in screen_source, f"previzualizarea de pe ecran a rămas în urmă: {phrase}"


@pytest.mark.parametrize("phrase", REMINDER_PHRASES)
def test_the_reminder_preview_quotes_the_real_message(
    phrase: str, screen_source: str, request_source: str
) -> None:
    """Al treilea mesaj este singurul care pleacă fără ca cineva să apese.

    Cu atât mai mult trebuie să scrie pe ecran exact ce primește clientul: pe
    celelalte două le vede cineva înainte să apese, pe ăsta nu-l vede nimeni.
    """
    assert phrase in request_source, f"fraza nu mai există în backend: {phrase}"
    assert phrase in screen_source, f"previzualizarea de pe ecran a rămas în urmă: {phrase}"


@pytest.mark.parametrize("phrase", DIGEST_PHRASES)
def test_the_digest_preview_quotes_the_real_message(
    phrase: str, screen_source: str, digest_source: str
) -> None:
    assert phrase in digest_source, f"fraza nu mai există în backend: {phrase}"
    assert phrase in screen_source, f"previzualizarea de pe ecran a rămas în urmă: {phrase}"


def test_the_screen_does_not_advertise_channels_the_application_cannot_use(
    screen_source: str,
) -> None:
    """WhatsApp a fost odată pe ecran ca un canal de trimitere.

    Aplicația nu trimite nimic pe WhatsApp și nu are cum: butoanele **deschid**
    conversația cu mesajul scris, iar ce pleacă hotărăște omul. Poate și **primi**
    documente de acolo — `DocumentSource.WHATSAPP` este exact acea recepție.
    Niciuna dintre cele două nu este un șablon trimis de aplicație, de aceea
    testul se uită la lista de șabloane, nu la tot fișierul: WhatsApp are voie să
    apară oriunde altundeva pe ecran, dar nu ca un mesaj care pleacă singur.
    """
    start = screen_source.index("const TEMPLATES")
    end = screen_source.index("export function TemplatesPage")
    assert "WhatsApp" not in screen_source[start:end]


def test_the_screen_no_longer_calls_sending_a_future_phase(screen_source: str) -> None:
    """Solicitarea chiar pleacă din aplicație de la M17.

    Un ecran care subestimează ce poate produsul ascunde exact funcția pe care
    cabinetul o caută — și e la fel de fals ca unul care promite prea mult.

    Se caută doar în **ce se afișează**: comentariile au voie să povestească ce
    scria înainte, altfel istoria s-ar putea scrie doar în afara codului.
    """
    assert "Faza 2" not in _without_comments(screen_source)


def _without_comments(source: str) -> str:
    """Fișierul fără comentariile de bloc și de linie."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_blocks, flags=re.MULTILINE)
