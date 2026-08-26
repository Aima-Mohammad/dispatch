"""Domain vocabulary. No I/O, no framework, no database.

Every business rule agreed during design is expressible with these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

type Level = int  # 1 junior, 2 intermediate, 3 expert

REFERENCE_DAY_MINUTES = 420  # 35 h / 5
REFERENCE_DAY_POINTS = 100


@dataclass(frozen=True, slots=True)
class ActType:
    """Reference data. `cadence` is the daily norm from the bonus scheme;
    the reference handling time derives from it."""

    code: str
    label: str
    points: float
    cadence: int
    sla_days: int
    levels: tuple[Level, ...]

    @property
    def base_minutes(self) -> float:
        return REFERENCE_DAY_MINUTES / self.cadence


@dataclass(frozen=True, slots=True)
class Caseworker:
    id: str
    display_name: str
    level: Level
    trusted: bool = False


class HoldReason(StrEnum):
    MISSING_DOCUMENT = "piece_manquante"
    MEMBER_FOLLOW_UP = "relance_adherent"
    MEDICAL_OPINION = "avis_medical"
    THIRD_PARTY = "attente_tiers"


@dataclass(slots=True)
class WorkItem:
    """A case. Indivisible unit from the engine's point of view.

    `due_on` is set on arrival from the act type's SLA. Slack derives from it,
    and slack alone drives priority — handling time never does.
    """

    id: str
    reference: str
    type_code: str
    due_on: date
    assigned_to: str | None = None
    held_reason: HoldReason | None = None
    pushed: bool = False


@dataclass(slots=True)
class Allocation:
    """Time allocated to this perimeter for one caseworker, one day.

    Zero means working elsewhere — never "absent". The points target is
    prorated on this value.
    """

    caseworker_id: str
    on_date: date
    minutes: int = REFERENCE_DAY_MINUTES

    @property
    def target_points(self) -> float:
        return REFERENCE_DAY_POINTS * self.minutes / REFERENCE_DAY_MINUTES


@dataclass(slots=True)
class LotRequest:
    """Input for one lot draw."""

    caseworker: Caseworker
    allocation: Allocation
    minutes_worked: float
    points_earned: float
    queue: list[WorkItem] = field(default_factory=list)
