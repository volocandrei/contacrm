"""Asistentul din aplicație — contractul, înaintea implementării.

**Ce este.** Un chat care răspunde la întrebări despre datele cabinetului și
duce omul la ecranul potrivit: „câte facturi așteaptă verificare?", „ce lipsește
la Alfa Conta pe august?", „când e termenul?".

**Trei reguli care nu se negociază.**

1. **Rulează ca utilizatorul, nu lângă el.** Fiecare unealtă primește
   `organization_id`-ul și permisiunile celui care întreabă și execută exact
   aceleași interogări ca rutele obișnuite. Un VIEWER care întreabă „cine are
   acces la audit" primește un refuz, nu răspunsul. Un asistent care vede mai
   mult decât utilizatorul este o breșă cu interfață prietenoasă.

2. **Doar citire.** Asistentul nu aprobă, nu respinge, nu șterge, nu trimite. Nu
   pentru că nu s-ar putea tehnic, ci pentru că o aprobare este un act contabil
   cu nume și oră în jurnal (§33): trebuie să aibă în spate un om care a apăsat,
   nu o propoziție interpretată. Ce poate face este să **propună** — un link,
   un filtru gata pus — pe care omul îl deschide.

3. **Nu inventează.** Fiecare cifră din răspuns vine dintr-o unealtă care a
   interogat baza. Când nu știe, o spune. Un asistent care aproximează numărul
   de facturi lipsă este mai rău decât unul mut, pentru că numărul lui ajunge
   într-un email către client.

**De ce o abstracție.** Implicit răspunde un motor determinist, fără nicio
credențială: acoperă întrebările care se pun de zeci de ori pe zi și nu poate
halucina. Când cabinetul configurează un model de limbaj, acesta preia
formularea liberă — dar tot prin aceleași unelte, cu aceleași limite. Seam-ul
este identic cu cel de la OCR și stocare (ADR-004, ADR-005).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.permissions import Permission


@dataclass(frozen=True)
class AssistantContext:
    """Cine întreabă. Nu există răspuns în afara acestui context."""

    organization_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    permissions: frozenset[Permission]

    def allows(self, permission: Permission) -> bool:
        return permission in self.permissions


@dataclass(frozen=True)
class Link:
    """Un drum către un ecran, cu filtrele deja puse.

    Asistentul nu navighează singur: întoarce unde s-ar duce, iar omul apasă.
    Diferența contează — un salt neașteptat într-un ecran de lucru pierde ce
    aveai pe el.
    """

    label: str
    path: str


@dataclass(frozen=True)
class Action:
    """O acțiune **pregătită**, nu executată.

    Asistentul o compune din date reale — id-uri verificate, nu nume ghicite — și
    o trimite interfeței, care o arată ca buton. Apăsarea cheamă ruta obișnuită,
    cu permisiunile obișnuite și cu aceeași urmă în jurnal ca atunci când omul ar
    fi făcut-o de mână. Nimic nu se execută din chat.

    `label` este ce scrie pe buton, `summary` ce se întâmplă dacă îl apeși —
    scrise pentru cineva care nu a citit conversația.
    """

    kind: str
    label: str
    summary: str
    #: Corpul cererii, exact cum îl așteaptă ruta. Interfața nu îl compune.
    payload: dict[str, str]


@dataclass(frozen=True)
class AssistantReply:
    """Răspunsul: text pentru om, linkuri pentru mâna lui."""

    text: str
    links: tuple[Link, ...] = ()
    #: Ce se poate face, dacă omul confirmă. Gol pentru întrebările de aflat.
    actions: tuple[Action, ...] = ()
    #: Ce ar mai putea întreba. Un chat fără sugestii se folosește o dată.
    suggestions: tuple[str, ...] = ()
    #: Numele uneltelor care au produs cifrele. Cine vrea să verifice, poate.
    used: tuple[str, ...] = ()


@dataclass
class ToolResult:
    """Ce întoarce o unealtă: text pentru răspuns, plus linkuri și propuneri."""

    text: str
    links: list[Link] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)


class AssistantProvider(Protocol):
    """Ce trebuie să știe să facă un motor de răspuns."""

    name: str

    def answer(self, message: str, context: AssistantContext) -> AssistantReply: ...


class AssistantError(Exception):
    """Motorul nu a putut răspunde. Se spune, nu se inventează un răspuns."""
