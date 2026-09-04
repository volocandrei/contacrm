"""Dialogul cu modelul de limbaj, fără model.

**NEVERIFICAT CU UN MODEL REAL — CERE O CREDENȚIALĂ EXTERNĂ.** Ce se verifică
aici este protocolul: ce i se trimite modelului, ce se face cu ce cere el, și ce
se întâmplă când nu răspunde. Prima cerere adevărată rămâne de făcut o singură
dată, manual, la instalare.

Ce apără testele, în ordinea gravității:

1. **Modelul nu primește date peste rolul omului.** Uneltele declarate sunt cele
   permise, iar refuzul unei unelte ajunge la model ca text, nu ca ocolire.
2. **Linkurile sunt ale noastre.** Ce apare ca drum vine din uneltele executate,
   nu din textul modelului — altfel un model ar putea trimite omul oriunde.
3. **Nu se rotește la nesfârșit.** Un model care cere unelte fără să răspundă
   costă bani la fiecare rundă.
4. **Când modelul cade, chatul nu cade.**
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.permissions import Permission, RoleCode, permissions_for
from app.services.assistant.base import AssistantContext, AssistantError
from app.services.assistant.language_model import LanguageModelAssistant
from tests.model_fake import FakeModel, text_reply, tool_reply


def context(role: RoleCode = RoleCode.ADMIN) -> AssistantContext:
    return AssistantContext(
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        user_name="Cine Întreabă",
        permissions=frozenset(permissions_for(role)),
    )


def assistant(fake: FakeModel, *, rounds: int = 3) -> LanguageModelAssistant:
    # Sesiunea rămâne `None`, deci testele de aici folosesc `deadline` — singura
    # unealtă care nu atinge baza. Ce fac celelalte se verifică în
    # `test_assistant_api.py`, pe o bază adevărată.
    return LanguageModelAssistant(
        None,  # type: ignore[arg-type]
        api_key="cheie-de-test",
        model="claude-sonnet-5",
        max_rounds=rounds,
        transport=fake.transport(),
    )


class TestWhatTheModelIsGiven:
    def test_it_only_sees_tools_the_role_can_use(self) -> None:
        """Un rol restrâns nu primește nici măcar descrierea uneltelor interzise."""
        fake = FakeModel(replies=[text_reply("gata")])
        limited = AssistantContext(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            user_name="Doar Sarcini",
            permissions=frozenset({Permission.TASKS_READ}),
        )

        assistant(fake).answer("ce am de făcut?", limited)

        declared = {tool["name"] for tool in fake.requests[0]["tools"]}
        assert declared == {"my_tasks"}

    def test_every_tool_declares_a_schema(self) -> None:
        fake = FakeModel(replies=[text_reply("gata")])

        assistant(fake).answer("salut", context())

        for tool in fake.requests[0]["tools"]:
            assert tool["input_schema"]["type"] == "object"
            assert tool["description"]

    def test_the_rules_travel_with_every_question(self) -> None:
        """Instrucțiunile nu se pun o dată, la începutul unei conversații."""
        fake = FakeModel(replies=[text_reply("gata")])

        assistant(fake).answer("salut", context())

        system = fake.requests[0]["system"]
        assert "DOAR pe baza rezultatelor uneltelor" in system
        assert "nu poți executa nicio acțiune care schimbă date" in system.lower()


class TestTheToolLoop:
    def test_a_tool_call_is_executed_and_returned(self) -> None:
        fake = FakeModel(
            replies=[
                tool_reply("deadline", "2026-08"),
                text_reply("Termenul este pe 25 septembrie."),
            ]
        )

        reply = assistant(fake).answer("când e termenul?", context())

        assert reply.text == "Termenul este pe 25 septembrie."
        assert reply.used == ("deadline",)
        # A doua cerere poartă rezultatul uneltei, ca `tool_result`.
        second = fake.requests[1]["messages"][-1]["content"][0]
        assert second["type"] == "tool_result"
        assert second["tool_use_id"] == "toolu_fake"

    def test_the_links_come_from_the_tools_not_from_the_text(self) -> None:
        """Un model nu are cum să trimită omul la o adresă inventată.

        Este singura garanție care contează aici: textul poate fi orice, dar
        butoanele pe care le vede omul vin din uneltele care chiar au rulat.
        """
        fake = FakeModel(
            replies=[
                tool_reply("deadline", "2026-08"),
                text_reply("Vezi la /administrare/setari sau http://exemplu.ro."),
            ]
        )

        reply = assistant(fake).answer("când e termenul?", context())

        assert [link.path for link in reply.links] == ["/contabilitate/perioade"]

    def test_a_refused_tool_reaches_the_model_as_text(self) -> None:
        """Refuzul se explică, nu se ocolește.

        Modelul află de ce nu poate răspunde și o poate spune omului — în loc să
        încerce altă unealtă până nimerește una permisă.
        """
        fake = FakeModel(replies=[tool_reply("find_client", "Alfa"), text_reply("Nu ai dreptul.")])
        without_clients = AssistantContext(
            organization_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            user_name="Fără Clienți",
            permissions=frozenset({Permission.TASKS_READ}),
        )

        assistant(fake).answer("deschide Alfa", without_clients)

        sent = fake.requests[1]["messages"][-1]["content"][0]["content"]
        assert "clients:read" in sent

    def test_an_invented_tool_is_answered_with_an_error(self) -> None:
        """Un model care cere `sterge_tot` nu găsește nimic de apăsat."""
        fake = FakeModel(replies=[tool_reply("sterge_tot"), text_reply("Nu pot face asta.")])

        reply = assistant(fake).answer("șterge tot", context())

        sent = fake.requests[1]["messages"][-1]["content"][0]
        assert sent["is_error"] is True
        assert reply.used == ()

    def test_it_stops_asking_for_tools_eventually(self) -> None:
        """Altfel, un model încăpățânat costă la fiecare rundă."""
        fake = FakeModel(replies=[tool_reply("deadline") for _ in range(10)])

        with pytest.raises(AssistantError):
            assistant(fake, rounds=2).answer("când e termenul?", context())

        assert len(fake.requests) == 2


class TestWhenTheModelFails:
    def test_a_network_failure_is_an_error_not_an_answer(self) -> None:
        """Niciodată un răspuns inventat în locul unuia care n-a venit."""
        fake = FakeModel(offline=True)

        with pytest.raises(AssistantError):
            assistant(fake).answer("când e termenul?", context())

    @pytest.mark.parametrize("status", [401, 429, 500])
    def test_a_refusal_is_reported_without_the_body(self, status: int) -> None:
        """Corpul erorii poate purta cheia într-un mesaj prost formulat."""
        fake = FakeModel(status=status)

        with pytest.raises(AssistantError) as caught:
            assistant(fake).answer("când e termenul?", context())

        assert str(status) in str(caught.value)
        assert "cheie-de-test" not in str(caught.value)
