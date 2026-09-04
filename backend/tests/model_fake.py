"""Un model de limbaj fals, în memorie.

**Nu putem chema un model din niciun test.** Cere o cheie, rețea și bani, iar
răspunsul nu este determinist — trei motive pentru care o suită de teste nu are
ce căuta acolo. Ca la ANAF și Microsoft Graph, partea care vorbește cu exteriorul
este subțire, iar dialogul se exercită prin protocolul HTTP, cu transportul ăsta.

Falsul este deliberat **strict**: verifică antetele obligatorii, verifică că i se
trimit unelte, și returnează exact ce ar returna API-ul — inclusiv forma blocului
`tool_use`. Un fals permisiv ar face testele să treacă și integrarea să cadă la
prima cerere reală.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class FakeModel:
    """Răspunsuri programate, în ordinea în care vor fi cerute.

    Fiecare intrare este corpul unui răspuns al API-ului. Testul le pune la rând:
    întâi cel care cere o unealtă, apoi cel care dă răspunsul final.
    """

    replies: list[dict[str, Any]] = field(default_factory=list)
    #: Ce a primit modelul, ca testul să poată verifica ce i s-a trimis.
    requests: list[dict[str, Any]] = field(default_factory=list)
    #: Când e pus, orice cerere primește codul ăsta în loc de răspuns.
    status: int = 200
    #: Când e adevărat, transportul aruncă — ca o pană de rețea.
    offline: bool = False

    def transport(self) -> httpx.BaseTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("rețea căzută", request=request)

        # Antetele fără de care API-ul refuză. Le verificăm aici, ca o lipsă să
        # cadă în teste, nu în producție.
        assert request.headers.get("x-api-key"), "cheia nu a fost trimisă"
        assert request.headers.get("anthropic-version"), "versiunea nu a fost trimisă"

        body = json.loads(request.content)
        assert body["tools"], "modelul a fost chemat fără unelte"
        assert body["system"], "modelul a fost chemat fără instrucțiuni"
        self.requests.append(body)

        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "nu acum"}})

        reply = self.replies.pop(0) if self.replies else text_reply("Nu mai am ce spune.")
        return httpx.Response(200, json=reply)


def text_reply(text: str) -> dict[str, Any]:
    """Un răspuns obișnuit, fără unelte."""
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
    }


def tool_reply(name: str, argument: str = "", *, call_id: str = "toolu_fake") -> dict[str, Any]:
    """Un răspuns care cere o unealtă."""
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": call_id,
                "name": name,
                "input": {"argument": argument} if argument else {},
            }
        ],
    }
