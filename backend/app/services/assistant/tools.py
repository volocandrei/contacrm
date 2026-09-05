"""Ce poate afla asistentul.

Fiecare unealtă este o funcție care primește contextul celui care întreabă și
interoghează exact ca rutele obișnuite: același repository, același
`organization_id`, aceeași permisiune. Nu există aici nicio interogare scrisă
special pentru asistent — dacă ar exista, ar fi a doua implementare a unei
reguli, iar cele două s-ar despărți la prima modificare.

Toate sunt **de citire**. Motivul stă în `base.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.enums import DocumentStatus, TaskStatus
from app.domain.periods import filing_deadline
from app.domain.permissions import Permission
from app.models.organization import Organization
from app.models.task import Task
from app.repositories.client import ClientRepository
from app.repositories.document import DocumentRepository
from app.schemas.client import ClientFilters
from app.schemas.common import PageParams
from app.schemas.document import DocumentFilters
from app.services.assistant.base import Action, AssistantContext, Link, ToolResult
from app.services.document_request import build_request_message
from app.services.period_service import PeriodService

#: Câte rânduri intră într-un răspuns de chat. Peste atât, răspunsul devine un
#: tabel prost — omul are ecrane pentru asta, iar linkul îl duce acolo.
MAX_ROWS = 5

#: Cât poate avea titlul unei sarcini. Aceeași limită ca în schema rutei: un
#: titlu care ar fi refuzat de server nu are de ce să ajungă până la butonul de
#: confirmare.
MAX_TASK_TITLE = 255


@dataclass(frozen=True)
class Tool:
    name: str
    #: Fără ea, unealta nici nu se execută: refuzul vine înaintea interogării.
    permission: Permission
    description: str
    run: Callable[[Session, AssistantContext, str], ToolResult]
    #: Ce înseamnă argumentul, pentru un model care trebuie să-l compună. Gol =
    #: unealta nu ia argument, iar schema pe care o vede modelul rămâne goală.
    argument_hint: str = ""


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _today() -> datetime:
    return datetime.now(ZoneInfo(settings.default_timezone))


def previous_month() -> str:
    """Luna care se depune acum: cea încheiată, nu cea în curs."""
    now = _today()
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return f"{year:04d}-{month:02d}"


# ── Cât e de lucru ───────────────────────────────────────────────────────────


def workload(session: Session, context: AssistantContext, _argument: str) -> ToolResult:
    """Câte documente așteaptă, pe fiecare fel de așteptare."""
    by_status = DocumentRepository(session).count_by_status(context.organization_id)
    review = by_status.get(DocumentStatus.REVIEW_REQUIRED, 0)
    unmatched = by_status.get(DocumentStatus.UNMATCHED, 0)
    errors = by_status.get(DocumentStatus.ERROR, 0)

    if review == 0 and unmatched == 0 and errors == 0:
        return ToolResult(text="Nu așteaptă niciun document. Coada este goală.")

    parts: list[str] = []
    links: list[Link] = []
    if review:
        parts.append(
            _plural(review, "document așteaptă verificare", "documente așteaptă verificare")
        )
        links.append(Link(label="Deschide verificarea", path="/documente/verificare"))
    if unmatched:
        parts.append(_plural(unmatched, "document e neatribuit", "documente sunt neatribuite"))
        links.append(Link(label="Vezi neatribuitele", path="/documente/neatribuite"))
    if errors:
        parts.append(_plural(errors, "document a eșuat", "documente au eșuat"))

    return ToolResult(text=". ".join(parts) + ".", links=links)


# ── Termenul lunii ───────────────────────────────────────────────────────────


def deadline(session: Session, context: AssistantContext, argument: str) -> ToolResult:
    """Când trebuie depuse declarațiile pentru luna încheiată."""
    del session, context
    month = argument or previous_month()
    day = filing_deadline(month, day=settings.filing_deadline_day)
    left = (day - _today().date()).days

    if left < 0:
        when = f"a trecut de {_plural(abs(left), 'zi', 'zile')}"
    elif left == 0:
        when = "este astăzi"
    else:
        when = f"mai sunt {_plural(left, 'zi', 'zile')}"

    return ToolResult(
        text=f"Termenul pentru luna {month} este {day.strftime('%d.%m.%Y')} — {when}.",
        links=[Link(label="Perioade", path="/contabilitate/perioade")],
    )


# ── Ce lipsește ──────────────────────────────────────────────────────────────


def missing_documents(session: Session, context: AssistantContext, argument: str) -> ToolResult:
    """Cine nu a trimis tot, pentru o lună."""
    month = argument or previous_month()
    entries = PeriodService(session).missing(context.organization_id, month)
    if not entries:
        return ToolResult(text=f"Pentru luna {month}, toți clienții au documentele complete.")

    lines = []
    for view, gaps in entries[:MAX_ROWS]:
        listed = ", ".join(
            f"{gap.document_type_label} ({gap.received_count}/{gap.expected_min_count})"
            for gap in gaps
        )
        lines.append(f"• {view.client_name} — lipsesc: {listed}")

    head = _plural(len(entries), "client are", "clienți au")
    text = f"Pentru luna {month}, {head} documente lipsă:\n" + "\n".join(lines)
    if len(entries) > MAX_ROWS:
        text += f"\n…și încă {len(entries) - MAX_ROWS}."

    return ToolResult(
        text=text,
        links=[Link(label="Documente lipsă", path=f"/contabilitate/lipsa?referenceMonth={month}")],
    )


# ── Clienți ──────────────────────────────────────────────────────────────────


def find_client(session: Session, context: AssistantContext, argument: str) -> ToolResult:
    """Un client după nume sau CUI, cu drumul către fișa lui."""
    if not argument:
        return ToolResult(text="Spune-mi numele firmei sau CUI-ul.")

    clients, total = ClientRepository(session).list(
        context.organization_id,
        ClientFilters(q=argument),
        PageParams(page=1, page_size=MAX_ROWS),
    )
    if not clients:
        return ToolResult(text=f"Nu am găsit niciun client pentru „{argument}”.")

    if len(clients) == 1:
        client = clients[0]
        return ToolResult(
            text=f"{client.name}, CUI {client.tax_id or '—'}.",
            links=[Link(label=f"Deschide {client.name}", path=f"/crm/clienti/{client.id}")],
            suggestions=[f"ce lipsește la {client.name}"],
        )

    listed = "\n".join(f"• {client.name}" for client in clients)
    return ToolResult(
        text=f"{total} clienți se potrivesc cu „{argument}”:\n{listed}",
        links=[
            Link(label=f"Deschide {client.name}", path=f"/crm/clienti/{client.id}")
            for client in clients
        ],
    )


def client_month(session: Session, context: AssistantContext, argument: str) -> ToolResult:
    """Cum stă un client cu luna: cât a trimis din ce se aștepta."""
    if not argument:
        return ToolResult(text="Spune-mi despre care client.")

    clients, _ = ClientRepository(session).list(
        context.organization_id, ClientFilters(q=argument), PageParams(page=1, page_size=2)
    )
    if not clients:
        return ToolResult(text=f"Nu am găsit niciun client pentru „{argument}”.")
    if len(clients) > 1:
        return ToolResult(
            text="Sunt mai mulți clienți cu numele ăsta. Spune-mi CUI-ul sau numele întreg."
        )

    client = clients[0]
    month = previous_month()
    link = Link(label=f"Deschide {client.name}", path=f"/crm/clienti/{client.id}")
    views = PeriodService(session).list_periods(
        context.organization_id, reference_month=month, client_id=client.id
    )
    if not views:
        return ToolResult(
            text=f"Pentru {client.name} nu a sosit niciun document în luna {month}.",
            links=[link],
        )

    view = views[0]
    gaps = [entry for entry in view.checklist if not entry.is_satisfied]
    if not gaps:
        text = (
            f"{client.name} are luna {month} completă: "
            f"{view.satisfied_count}/{view.expected_count}."
        )
    else:
        listed = ", ".join(
            f"{gap.document_type_label} ({gap.received_count}/{gap.expected_min_count})"
            for gap in gaps
        )
        text = (
            f"{client.name}, luna {month}: {view.satisfied_count}/{view.expected_count}. "
            f"Lipsesc: {listed}."
        )

    return ToolResult(text=text, links=[link])


# ── Sarcini ──────────────────────────────────────────────────────────────────


def my_tasks(session: Session, context: AssistantContext, _argument: str) -> ToolResult:
    """Ce am de făcut: sarcinile mele deschise, cele cu termen primele."""
    open_states = (TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)
    rows = list(
        session.scalars(
            select(Task)
            .where(
                Task.organization_id == context.organization_id,
                Task.assigned_to_id == context.user_id,
                Task.status.in_(open_states),
            )
            .order_by(Task.due_date.is_(None), Task.due_date)
            .limit(MAX_ROWS)
        )
    )
    if not rows:
        return ToolResult(text="Nu ai nicio sarcină deschisă.")

    lines = [
        f"• {task.title}"
        + (f" — termen {task.due_date.strftime('%d.%m.%Y')}" if task.due_date else "")
        for task in rows
    ]
    return ToolResult(
        text="Sarcinile tale deschise:\n" + "\n".join(lines),
        links=[Link(label="Toate sarcinile", path="/crm/sarcini")],
    )


# ── Ce pregătește pentru un om ───────────────────────────────────────────────


def draft_request(session: Session, context: AssistantContext, argument: str) -> ToolResult:
    """Scrie solicitarea de documente pentru un client, gata de trimis.

    Textul îl compune `document_request.py`, același de pe ecranul „Documente
    lipsă": o a doua formulare ar însemna că doi clienți primesc, în aceeași zi,
    două mesaje diferite de la același cabinet.
    """
    if not argument:
        return ToolResult(text="Spune-mi pentru care client.")

    clients, _ = ClientRepository(session).list(
        context.organization_id, ClientFilters(q=argument), PageParams(page=1, page_size=2)
    )
    if not clients:
        return ToolResult(text=f"Nu am găsit niciun client pentru „{argument}”.")
    if len(clients) > 1:
        return ToolResult(text="Sunt mai mulți clienți cu numele ăsta. Spune-mi numele întreg.")

    client = clients[0]
    month = previous_month()
    views = PeriodService(session).list_periods(
        context.organization_id, reference_month=month, client_id=client.id
    )
    gaps = [item for item in views[0].checklist if not item.is_satisfied] if views else []
    if not gaps:
        return ToolResult(
            text=f"{client.name} nu are documente lipsă pe {month}. Nu e nimic de cerut."
        )

    message = build_request_message(
        client_name=client.name,
        reference_month=month,
        deadline=filing_deadline(month, day=settings.filing_deadline_day),
        missing=gaps,
        organization_name=_organization_name(session, context),
    )
    return ToolResult(
        text=message,
        links=[
            Link(
                label="Documente lipsă",
                path=f"/contabilitate/lipsa?referenceMonth={month}",
            )
        ],
    )


def propose_task(session: Session, context: AssistantContext, argument: str) -> ToolResult:
    """Pregătește o sarcină, cu titlul cerut. Nu o creează.

    Se atribuie celui care a cerut-o: „notează-mi" înseamnă „mie". Termenul și
    clientul se pun după aceea, din kanban — o sarcină pe care nu o poți nota în
    trei secunde nu se notează deloc.
    """
    title = argument.strip()
    if not title:
        return ToolResult(text="Spune-mi ce să notez.")
    if len(title) > MAX_TASK_TITLE:
        title = title[:MAX_TASK_TITLE].rstrip()

    return ToolResult(
        text=f"Pot nota sarcina „{title}”, pe numele tău.",
        actions=[
            Action(
                kind="create_task",
                label="Notează sarcina",
                summary=f"Se creează sarcina „{title}”, atribuită ție.",
                payload={"title": title, "assignedToId": str(context.user_id)},
            )
        ],
        links=[Link(label="Sarcini", path="/crm/sarcini")],
    )


def propose_assignment(session: Session, context: AssistantContext, argument: str) -> ToolResult:
    """Pregătește atribuirea documentelor neatribuite către un client.

    Documentele fără client identificat sunt munca cea mai ingrată: cineva
    trebuie să se uite la fiecare și să știe firmele. Asistentul găsește
    clientul și pregătește atribuirea; apăsarea rămâne a omului, fiindcă o
    atribuire greșită mută o factură în contabilitatea altei firme.
    """
    if not argument:
        return ToolResult(text="Spune-mi către care client.")

    clients, _ = ClientRepository(session).list(
        context.organization_id, ClientFilters(q=argument), PageParams(page=1, page_size=2)
    )
    if not clients:
        return ToolResult(text=f"Nu am găsit niciun client pentru „{argument}”.")
    if len(clients) > 1:
        return ToolResult(text="Sunt mai mulți clienți cu numele ăsta. Spune-mi numele întreg.")

    client = clients[0]
    unmatched, total = DocumentRepository(session).list(
        context.organization_id,
        DocumentFilters(status=DocumentStatus.UNMATCHED.value),
        PageParams(page=1, page_size=MAX_ROWS),
    )
    if not unmatched:
        return ToolResult(text="Nu există documente neatribuite.")

    listed = "\n".join(f"• {row.document.original_filename}" for row in unmatched)
    more = f" (din {total})" if total > len(unmatched) else ""
    return ToolResult(
        text=(
            f"Sunt {total} documente neatribuite. Primele{more}:\n{listed}\n"
            f"Le pot pregăti pentru {client.name} — verifică-le înainte de a confirma."
        ),
        actions=[
            Action(
                kind="assign_client",
                label=f"Atribuie primul lui {client.name}",
                summary=(
                    f"„{unmatched[0].document.original_filename}” trece la {client.name} "
                    "și intră la verificare."
                ),
                payload={
                    "documentId": str(unmatched[0].document.id),
                    "clientId": str(client.id),
                },
            )
        ],
        links=[Link(label="Neatribuite", path="/documente/neatribuite")],
    )


def _organization_name(session: Session, context: AssistantContext) -> str:
    name = session.scalar(
        select(Organization.name).where(Organization.id == context.organization_id)
    )
    return name or "Cabinetul dumneavoastră"


# ── Registrul ────────────────────────────────────────────────────────────────

TOOLS: tuple[Tool, ...] = (
    Tool(
        name="workload",
        permission=Permission.DOCUMENTS_READ,
        description="Câte documente așteaptă verificare, atribuire sau au eșuat.",
        run=workload,
    ),
    Tool(
        name="deadline",
        permission=Permission.DOCUMENTS_READ,
        description="Termenul de depunere pentru luna încheiată.",
        run=deadline,
        argument_hint="Luna contabilă, ca „2026-08”. Gol = luna care se depune acum.",
    ),
    Tool(
        name="missing_documents",
        permission=Permission.DOCUMENTS_READ,
        description="Ce documente lipsesc, per client, pentru o lună.",
        run=missing_documents,
        argument_hint="Luna contabilă, ca „2026-08”. Gol = luna care se depune acum.",
    ),
    Tool(
        name="find_client",
        permission=Permission.CLIENTS_READ,
        description="Găsește un client după nume sau CUI.",
        run=find_client,
        argument_hint="Numele firmei sau CUI-ul, așa cum l-a scris omul.",
    ),
    Tool(
        name="client_month",
        permission=Permission.CLIENTS_READ,
        description="Cum stă un client cu luna în curs de depunere.",
        run=client_month,
        argument_hint="Numele firmei sau CUI-ul.",
    ),
    Tool(
        name="draft_request",
        permission=Permission.CLIENTS_READ,
        description=(
            "Scrie solicitarea de documente pentru un client, gata de trimis. "
            "Nu trimite nimic — doar compune textul."
        ),
        run=draft_request,
        argument_hint="Numele firmei sau CUI-ul.",
    ),
    Tool(
        name="propose_task",
        permission=Permission.TASKS_WRITE,
        description=("Pregătește o sarcină cu titlul cerut. Nu o creează: omul confirmă."),
        run=propose_task,
        argument_hint="Ce trebuie făcut, ca titlu scurt.",
    ),
    Tool(
        name="propose_assignment",
        permission=Permission.DOCUMENTS_WRITE,
        description=(
            "Pregătește atribuirea unui document neatribuit către un client. "
            "Nu atribuie: omul confirmă."
        ),
        run=propose_assignment,
        argument_hint="Numele firmei căreia îi aparțin documentele.",
    ),
    Tool(
        name="my_tasks",
        permission=Permission.TASKS_READ,
        description="Sarcinile deschise ale utilizatorului curent.",
        run=my_tasks,
    ),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def run_tool(
    name: str, session: Session, context: AssistantContext, argument: str = ""
) -> ToolResult:
    """Execută o unealtă, dacă rolul o permite.

    Verificarea stă aici, nu în fiecare unealtă: o unealtă nouă care ar uita-o ar
    deveni o portiță. Refuzul spune ce permisiune lipsește, ca omul să știe pe
    cine să întrebe — nu pretinde că nu există date.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        raise KeyError(name)
    if not context.allows(tool.permission):
        return ToolResult(
            text=(
                f"Rolul tău nu include permisiunea `{tool.permission.value}`, "
                "deci nu pot răspunde la asta."
            )
        )
    return tool.run(session, context, argument)


def allowed_tools(context: AssistantContext) -> tuple[Tool, ...]:
    return tuple(tool for tool in TOOLS if context.allows(tool.permission))
