"""Fictional data, deterministic for a fixed seed.

Nothing here may leak into `dispatch.domain`: the engine knows inputs, never
where they came from. Figures follow the MGC bonus scheme — `cadence` is the
daily norm, and the reference handling time derives from it.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from dispatch.domain.models import ActType, Caseworker, WorkItem

ACT_TYPES: dict[str, ActType] = {
    a.code: a
    for a in (
        ActType("PRE", "Prestations adhérents MGC", 1.1, 90, 4, (1, 2, 3)),
        ActType("REP", "Réponse écrite à une demande adhérent", 2, 42, 3, (1, 2, 3)),
        ActType("MAJ", "Mise à jour MGC", 2, 55, 5, (1, 2, 3)),
        ActType("COT", "Cotisation MGC", 2, 50, 5, (1, 2, 3)),
        ActType("ADH", "Adhésion MGC", 3, 37, 3, (1, 2, 3)),
        ActType("RAD", "Radiation MGC", 1.5, 70, 5, (1, 2, 3)),
        ActType("CGR", "Prestations Contrat Groupe JM", 1.4, 70, 4, (2, 3)),
        ActType("NCF", "Réponse à une non-conformité", 4, 25, 3, (2, 3)),
        ActType("RECL", "Réponse écrite à une réclamation", 5, 20, 10, (2, 3)),
        ActType("DEC", "Décès MGC", 3.6, 28, 3, (3,)),
    )
}

DAILY_ARRIVALS: dict[str, int] = {
    "PRE": 24,
    "REP": 36,
    "MAJ": 24,
    "COT": 20,
    "ADH": 27,
    "RAD": 15,
    "CGR": 13,
    "NCF": 22,
    "RECL": 16,
    "DEC": 9,
}

CASEWORKERS: tuple[Caseworker, ...] = (
    Caseworker("g-lea", "Léa M.", 1),
    Caseworker("g-yanis", "Yanis B.", 1),
    Caseworker("g-chloe", "Chloé D.", 1),
    Caseworker("g-karim", "Karim H.", 2, trusted=True),
    Caseworker("g-sophie", "Sophie R.", 2, trusted=True),
    Caseworker("g-thomas", "Thomas G.", 2),
    Caseworker("g-amina", "Amina S.", 2),
    Caseworker("g-julien", "Julien P.", 2),
    Caseworker("g-nadia", "Nadia C.", 3, trusted=True),
    Caseworker("g-marc", "Marc L.", 3),
)


def _add_business_days(start: date, days: int) -> date:
    cursor = start
    step = 1 if days >= 0 else -1
    left = abs(days)
    while left > 0:
        cursor += timedelta(days=step)
        if cursor.weekday() < 5:
            left -= 1
    return cursor


def make_backlog(today: date, seed: int = 42, overdue_share: float = 0.12) -> list[WorkItem]:
    """A plausible backlog: cases that arrived on previous days, whose due date
    derives from the SLA of their type. A share is already past due."""
    rng = random.Random(seed)
    items: list[WorkItem] = []
    counter = 0
    for act in ACT_TYPES.values():
        volume = DAILY_ARRIVALS[act.code]
        for back in range(act.sla_days + 1):
            count = round(volume * (0.9 + rng.random() * 0.4) / (act.sla_days + 1))
            for _ in range(count):
                late = rng.random() < overdue_share
                offset = act.sla_days - back - (rng.randint(2, 4) if late else 0)
                items.append(
                    WorkItem(
                        id=f"w{counter}",
                        reference=f"SUDE-26-{40000 + counter * 7 % 59999:05d}",
                        type_code=act.code,
                        due_on=_add_business_days(today, max(-6, offset)),
                    )
                )
                counter += 1
    rng.shuffle(items)
    return items