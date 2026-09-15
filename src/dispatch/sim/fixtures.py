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

# Roughly 30 cases per caseworker per day, which is what the team actually
# handles. The mix leans on the shorter acts, as the real flow does.
# Volumes track the headcount below: thirty-five caseworkers, so about 1050
# cases a day. Change one and the other must follow, or the lots run dry.
# Collective daily obligation, all mobilised caseworkers together. Not in the
# bonus scheme: MH consume time and earn no points (decision 3.16).
MH_DAILY_TOTAL = 700

DAILY_ARRIVALS: dict[str, int] = {
    "PRE": 210,
    "REP": 168,
    "MAJ": 140,
    "COT": 120,
    "ADH": 105,
    "RAD": 90,
    "CGR": 70,
    "NCF": 63,
    "RECL": 42,
    "DEC": 28,
}

# Thirty-five caseworkers, the real size of the team. Levels are spread as
# the team is: a quarter junior, half intermediate, a quarter expert. Trust
# is a working habit, not a rank — it only decides who is suggested first.
CASEWORKERS: tuple[Caseworker, ...] = (
    Caseworker("g-lea", "Léa M.", 1),
    Caseworker("g-yanis", "Yanis B.", 1),
    Caseworker("g-chloe", "Chloé D.", 1),
    Caseworker("g-ines", "Inès T.", 1),
    Caseworker("g-lucas", "Lucas F.", 1),
    Caseworker("g-sarah", "Sarah K.", 1),
    Caseworker("g-maxime", "Maxime V.", 1),
    Caseworker("g-jade", "Jade N.", 1),
    Caseworker("g-adam", "Adam Z.", 1),
    Caseworker("g-karim", "Karim H.", 2, trusted=True),
    Caseworker("g-sophie", "Sophie R.", 2, trusted=True),
    Caseworker("g-fatima", "Fatima A.", 2, trusted=True),
    Caseworker("g-celine", "Céline W.", 2, trusted=True),
    Caseworker("g-thomas", "Thomas G.", 2),
    Caseworker("g-amina", "Amina S.", 2),
    Caseworker("g-julien", "Julien P.", 2),
    Caseworker("g-david", "David E.", 2),
    Caseworker("g-emma", "Emma L.", 2),
    Caseworker("g-rachid", "Rachid O.", 2),
    Caseworker("g-claire", "Claire B.", 2),
    Caseworker("g-olivier", "Olivier M.", 2),
    Caseworker("g-samira", "Samira D.", 2),
    Caseworker("g-nicolas", "Nicolas C.", 2),
    Caseworker("g-laure", "Laure J.", 2),
    Caseworker("g-hugo", "Hugo R.", 2),
    Caseworker("g-myriam", "Myriam T.", 2),
    Caseworker("g-antoine", "Antoine F.", 2),
    Caseworker("g-nadia", "Nadia C.", 3, trusted=True),
    Caseworker("g-patricia", "Patricia G.", 3, trusted=True),
    Caseworker("g-valerie", "Valérie S.", 3, trusted=True),
    Caseworker("g-marc", "Marc L.", 3),
    Caseworker("g-bruno", "Bruno P.", 3),
    Caseworker("g-stephane", "Stéphane A.", 3),
    Caseworker("g-isabelle", "Isabelle N.", 3),
    Caseworker("g-gerard", "Gérard V.", 3),
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


def make_backlog(
    today: date, seed: int = 42, overdue_share: float = 0.12
) -> list[WorkItem]:
    """A plausible backlog: several days of arrivals, each with the due date
    its type implies. A share is already past due.

    Volumes are per day, so a case type present in the flow for `sla_days`
    days appears that many times over — otherwise the stock would be thinner
    than a single day of work.
    """
    rng = random.Random(seed)
    items: list[WorkItem] = []
    counter = 0
    for act in ACT_TYPES.values():
        volume = DAILY_ARRIVALS[act.code]
        for back in range(act.sla_days + 1):
            count = round(volume * (0.9 + rng.random() * 0.4))
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