"""Motorul cu model de limbaj, peste **aceleași** unelte.

**De ce arată așa.** Tiparul folosit azi peste tot pentru asistenți în aplicații
de business este același: modelul nu are acces la baza de date, ci la o listă
scurtă de unelte declarate de server; el alege ce cheamă, serverul execută sub
permisiunile utilizatorului, iar modelul primește înapoi doar rezultatul. Nimic
din datele cabinetului nu ajunge la model decât ca răspuns al unei unelte pe care
utilizatorul avea dreptul să o cheme.

**Ce câștigă față de motorul cu reguli.** Formularea liberă: „mi-a trimis Alfa
tot pe august?", „ce am de recuperat săptămâna asta?", „rezumă-mi luna". Motorul
cu reguli acoperă întrebările scurte și frecvente; ăsta acoperă restul.

**Ce nu se schimbă, deliberat:**

- **Uneltele sunt aceleași**, cu aceeași barieră de permisiuni. Un model nu poate
  inventa o unealtă, iar una refuzată întoarce refuzul — pe care modelul îl
  explică, în loc să ocolească.
- **Modelul nu schimbă nimic.** Uneltele care încep cu `propose_` *pregătesc* o
  acțiune și o trimit interfeței ca buton; execuția cere apăsarea unui om și
  trece prin ruta obișnuită, cu permisiunile și jurnalul obișnuite. Modelul nu
  poate nici compune singur o propunere: id-urile din ea vin din unelte.
- **Linkurile sunt ale noastre.** Ce apare ca drum în răspuns vine din uneltele
  executate, nu din textul modelului: un model nu are cum să trimită omul la o
  adresă inventată.

**Ce se poate strica și nu se poate testa aici.** Cererea către model cere o
cheie și rețea. Ca la ANAF și Microsoft Graph, partea care vorbește cu exteriorul
este cât mai subțire și se exercită în teste cu un transport fals; ce nu se poate
verifica fără credențială este marcat ca atare în documentație.
"""

from __future__ import annotations

import json
from typing import Any, Final

import httpx
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.services.assistant.base import (
    Action,
    AssistantContext,
    AssistantError,
    AssistantReply,
    Link,
)
from app.services.assistant.tools import allowed_tools, run_tool

logger = get_logger(__name__)

API_URL: Final = "https://api.anthropic.com/v1/messages"
API_VERSION: Final = "2023-06-01"
TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)

#: Cât poate scrie modelul. Un răspuns de chat, nu un raport.
MAX_TOKENS: Final = 800

SYSTEM_PROMPT: Final = """Ești asistentul unei aplicații de contabilitate românești (ContaCRM), \
folosită de un cabinet care ține evidența mai multor firme.

Reguli, în ordinea importanței:

1. Răspunde DOAR pe baza rezultatelor uneltelor. Nu presupune și nu completa \
cifre din memorie. Dacă uneltele nu îți dau răspunsul, spune limpede că nu știi.
2. Nu poți executa nicio acțiune care schimbă date. Uneltele care încep cu \
`propose_` doar PREGĂTESC ceva: omul apasă un buton ca să se întâmple. Spune \
limpede că ai pregătit, nu că ai făcut. Nu promite că aprobi, respingi, ștergi \
sau trimiți.
3. Scrie în română, scurt, la obiect. Fără formule de politețe lungi. \
Cifrele exacte, așa cum le-au dat uneltele.
4. Dacă o unealtă refuză din lipsă de permisiune, spune omului ce permisiune \
îi lipsește. Nu încerca altă unealtă ca să ocolești refuzul.
5. Luna contabilă se scrie ca „2026-08". Când omul nu spune luna, uneltele \
folosesc luna care se depune acum."""


def _schema(argument_hint: str) -> dict[str, Any]:
    """Forma parametrilor unei unelte, pentru model."""
    if not argument_hint:
        return {"type": "object", "properties": {}}
    return {
        "type": "object",
        "properties": {"argument": {"type": "string", "description": argument_hint}},
    }


class LanguageModelAssistant:
    """Model de limbaj cu tool-calling, peste uneltele aplicației."""

    name = "anthropic"

    def __init__(
        self,
        session: Session,
        *,
        api_key: str,
        model: str,
        max_rounds: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.session = session
        self._api_key = api_key
        self._model = model
        self._max_rounds = max_rounds
        # Injectabil, ca testele să poată pune un transport fals fără rețea.
        self._transport = transport

    # ── Dialogul ────────────────────────────────────────────────────────────

    def answer(self, message: str, context: AssistantContext) -> AssistantReply:
        tools = allowed_tools(context)
        declared = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": _schema(tool.argument_hint),
            }
            for tool in tools
        ]
        conversation: list[dict[str, Any]] = [{"role": "user", "content": message}]

        used: list[str] = []
        links: list[Link] = []
        actions: list[Action] = []

        for _round in range(self._max_rounds):
            response = self._call(conversation, declared)
            blocks = response.get("content", [])
            conversation.append({"role": "assistant", "content": blocks})

            calls = [block for block in blocks if block.get("type") == "tool_use"]
            if not calls:
                return AssistantReply(
                    text=_text_of(blocks) or "Nu am găsit un răspuns.",
                    links=tuple(links),
                    # Propunerile vin din unelte, ca și linkurile: un model nu
                    # poate compune singur o acțiune și nici id-urile din ea.
                    actions=tuple(actions),
                    used=tuple(used),
                )

            results = []
            for call in calls:
                name = str(call.get("name", ""))
                argument = str((call.get("input") or {}).get("argument", ""))
                # Bariera este aceeași ca peste tot: modelul cere, serverul
                # decide. O unealtă necunoscută nu este o eroare de securitate,
                # ci una de model — i-o spunem, ca să nu insiste.
                try:
                    result = run_tool(name, self.session, context, argument)
                except KeyError:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.get("id"),
                            "is_error": True,
                            "content": f"Unealta {name!r} nu există.",
                        }
                    )
                    continue

                used.append(name)
                links.extend(result.links)
                actions.extend(result.actions)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.get("id"),
                        "content": result.text,
                    }
                )

            conversation.append({"role": "user", "content": results})

        # Modelul a cerut unelte la nesfârșit. Mai bine un răspuns cinstit decât
        # un dialog care nu se termină pe cheltuiala cabinetului.
        raise AssistantError("Modelul nu a ajuns la un răspuns în pașii permiși.")

    # ── Partea care vorbește cu exteriorul ──────────────────────────────────

    def _call(
        self, conversation: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": conversation,
            "tools": tools,
        }
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport) as http:
                response = http.post(
                    API_URL,
                    json=payload,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": API_VERSION,
                        "content-type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise AssistantError(f"Modelul nu a răspuns: {exc}") from exc

        if response.status_code >= 400:
            # Corpul poate purta motivul, dar poate purta și cheia într-un mesaj
            # de eroare prost formulat. Logăm codul, nu corpul.
            logger.warning("assistant_model_error", status=response.status_code)
            raise AssistantError(f"Modelul a refuzat cererea (HTTP {response.status_code}).")

        try:
            body: dict[str, Any] = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise AssistantError("Modelul a răspuns cu ceva ce nu este JSON.") from exc
        return body


def _text_of(blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(block.get("text", "")) for block in blocks if block.get("type") == "text"
    ).strip()
