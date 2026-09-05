"""Motorul implicit: potrivire de intenție, fără niciun serviciu extern.

**De ce există, când există modele de limbaj.** Trei motive, în ordinea
importanței:

1. **Funcționează în ziua zero.** Un cabinet care instalează aplicația nu are
   cheie de API și nu vrea să deschidă cont nicăieri. Un chat care spune „nu
   sunt configurat" la prima întrebare nu se mai deschide a doua oară.
2. **Nu poate greși cifra.** Întrebările care se pun de zeci de ori pe zi —
   „câte așteaptă verificare?", „ce lipsește la X?", „când e termenul?" — au
   răspunsuri exacte, luate din bază. Un model care aproximează numărul de
   facturi lipsă produce un email greșit către client.
3. **Nu trimite nimic afară.** Datele contabile ale clienților nu pleacă din
   rețeaua cabinetului cât timp răspunde motorul ăsta.

**Ce nu face.** Nu înțelege formulări libere („fă-mi un rezumat al lunii în
stilul unui raport"). Pentru acelea intră un model de limbaj, prin același seam
și cu aceleași unelte — vezi `base.py`.

Potrivirea este pe cuvinte-cheie fără diacritice, deliberat: oamenii scriu
repede și fără diacritice într-un chat.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.assistant.base import AssistantContext, AssistantReply
from app.services.assistant.tools import allowed_tools, previous_month, run_tool

#: Formatul lunii, așa cum îl scrie un om: „2026-08" sau „august".
_MONTH_PATTERN = re.compile(r"\b(20\d{2})[-/](0[1-9]|1[0-2])\b")

_MONTH_NAMES = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}


def normalise(text: str) -> str:
    """Fără diacritice, litere mici. Aceeași regulă ca la căutarea din aplicație."""
    stripped = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in stripped if not unicodedata.combining(ch)).lower()


@dataclass(frozen=True)
class Intent:
    tool: str
    #: Cuvinte care, împreună, arată intenția. Grupul întreg trebuie găsit.
    triggers: tuple[tuple[str, ...], ...]
    #: Ce ia unealta ca argument: luna, restul propoziției, sau nimic.
    argument: str = "none"


#: Ordinea contează: prima potrivire câștigă, deci intențiile stau de la cea mai
#: îngustă la cea mai largă. „ce lipsește la Alfa" este o întrebare despre un
#: client, nu raportul general de lipsuri — deși conține cuvântul „lipsește".
#:
#: Un grup este o **conjuncție**: toate cuvintele din el trebuie să apară.
INTENTS: tuple[Intent, ...] = (
    Intent(
        tool="draft_request",
        triggers=(("scrie", "solicitare"), ("cere", "documente"), ("mesaj", "client")),
        argument="client",
    ),
    Intent(
        tool="propose_task",
        triggers=(("noteaza",), ("adauga sarcina",), ("sarcina noua",), ("aminteste",)),
        argument="raw",
    ),
    Intent(
        tool="propose_assignment",
        triggers=(("atribuie",), ("neatribuit",), ("fara client",)),
        argument="client",
    ),
    Intent(
        tool="client_month",
        triggers=(("lipseste", "la"), ("cum sta",), ("situatia", "la"), ("stadiu",)),
        argument="client",
    ),
    Intent(
        tool="missing_documents",
        triggers=(("lipse",), ("nu au trimis",), ("incomplet",), ("nu a venit",)),
        argument="month",
    ),
    Intent(
        tool="deadline",
        triggers=(("termen",), ("scadent",), ("deadline",)),
        argument="month",
    ),
    Intent(
        tool="my_tasks",
        triggers=(("sarcin",), ("task",)),
    ),
    Intent(
        tool="workload",
        triggers=(("cate",), ("cat", "lucru"), ("astept",), ("coada",), ("verificare",)),
    ),
    Intent(
        tool="find_client",
        triggers=(("client",), ("firma",), ("cui",), ("caut",), ("deschide",)),
        argument="client",
    ),
)

#: Ce se poate întreba, arătat înainte de prima întrebare — fiecare legată de
#: unealta care îi răspunde, ca să nu se propună ce rolul nu poate cere. Un chat
#: gol, fără exemple, primește „salut" și apoi nimic.
STARTERS: tuple[tuple[str, str], ...] = (
    ("cât e de lucru?", "workload"),
    ("când e termenul?", "deadline"),
    ("ce documente lipsesc?", "missing_documents"),
    ("sarcinile mele", "my_tasks"),
)


def extract_month(text: str) -> str:
    """Luna din întrebare, dacă e scrisă; altfel cea care se depune acum."""
    match = _MONTH_PATTERN.search(text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    normalised = normalise(text)
    for name, number in _MONTH_NAMES.items():
        if name in normalised:
            year = _MONTH_PATTERN.search(text)
            season = int(year.group(1)) if year else int(previous_month()[:4])
            return f"{season:04d}-{number:02d}"
    return ""


def extract_client(text: str) -> str:
    """Ce a rămas după cuvintele de comandă: numele firmei, cel mai probabil.

    Nu încearcă să fie deșteaptă. Dacă rămâne prea puțin, unealta întreabă.
    """
    normalised = normalise(text)
    # Ordinea contează: se ia prima expresie găsită, deci cele lungi stau
    # înaintea celor scurte. „atribuie documentele lui X" trebuie să lase „X",
    # nu „documentele lui X".
    for phrase in (
        "scrie solicitarea pentru",
        "solicitarea pentru",
        "cere documente de la",
        "cere documentele de la",
        "atribuie documentele lui",
        "atribuie documentele catre",
        "atribuie lui",
        "atribuie",
        "ce lipseste la",
        "cum sta",
        "situatia la",
        "stadiu",
        "clientul",
        "client",
        "firma",
        "deschide",
        "caut",
        "cui",
    ):
        index = normalised.find(phrase)
        if index >= 0:
            return text[index + len(phrase) :].strip(" ?.,:;")
    return text.strip(" ?.,:;")


#: Cuvintele de comandă care nu fac parte din ce se cere. „notează să sun la
#: Alfa" trebuie să devină sarcina „să sun la Alfa", nu „notează să sun la Alfa".
_COMMAND_WORDS = ("noteaza", "adauga sarcina", "sarcina noua", "aminteste-mi", "aminteste")


def extract_raw(text: str) -> str:
    """Ce a cerut omul, fără cuvântul de comandă din față."""
    normalised = normalise(text)
    for phrase in _COMMAND_WORDS:
        index = normalised.find(phrase)
        if index >= 0:
            return text[index + len(phrase) :].strip(" ?.,:;-")
    return text.strip(" ?.,:;")


class RuleAssistant:
    """Răspunde din unelte, după intenția recunoscută în text."""

    name = "rules"

    def __init__(self, session: Session) -> None:
        self.session = session

    def answer(self, message: str, context: AssistantContext) -> AssistantReply:
        text = message.strip()
        if not text:
            return self._help(context, "Întreabă-mă ceva despre documentele sau clienții tăi.")

        normalised = normalise(text)
        for intent in INTENTS:
            if not any(all(word in normalised for word in group) for group in intent.triggers):
                continue

            argument = ""
            if intent.argument == "month":
                argument = extract_month(text)
            elif intent.argument == "client":
                argument = extract_client(text)
            elif intent.argument == "raw":
                argument = extract_raw(text)

            result = run_tool(intent.tool, self.session, context, argument)
            return AssistantReply(
                text=result.text,
                links=tuple(result.links),
                actions=tuple(result.actions),
                suggestions=tuple(result.suggestions) or self._suggestions(context),
                used=(intent.tool,),
            )

        return self._help(context, "N-am înțeles întrebarea.")

    def _help(self, context: AssistantContext, lead: str) -> AssistantReply:
        """Când nu înțelege, spune **ce** poate — nu repetă că nu a înțeles.

        Lista se filtrează pe permisiuni: un rol fără `clients:read` nu are de ce
        să vadă propus „caută un client".
        """
        tools = allowed_tools(context)
        listed = "\n".join(f"• {tool.description}" for tool in tools)
        return AssistantReply(
            text=f"{lead} Pot răspunde la:\n{listed}",
            suggestions=self._suggestions(context),
        )

    def _suggestions(self, context: AssistantContext) -> tuple[str, ...]:
        names = {tool.name for tool in allowed_tools(context)}
        return tuple(starter for starter, tool in STARTERS if tool in names)
