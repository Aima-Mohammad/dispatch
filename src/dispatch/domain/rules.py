"""Pure business rules. No state, no I/O — only computations on domain values.

Everything negotiable with the business lives in `Policy`, never hard-coded
in the scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from dispatch.domain.models import (
    REFERENCE_DAY_MINUTES,
    REFERENCE_DAY_POINTS,
    ActType,
    Caseworker,
    Level,
)


@dataclass(frozen=True, slots=True)
class Policy:
    """Tunable parameters. Changing these must never require touching code."""

    level_coefficient: dict[Level, float]
    lot_share_of_remaining: float = 0.25
    lot_min_minutes: int = 15
    lot_max_minutes: int = 120
    refill_ratio: float = 0.6
    slack_tolerance_days: int = 1
    # ASSUMPTION — the MH scheme has not been provided. Seven minutes is a
    # working figure so the simulation holds together; it is the single
    # number to correct once the real cadence is known. It drives how much
    # of the day is left for SUDE, so it is not a cosmetic default.
    mh_minutes: float = 7.0


DEFAULT_POLICY = Policy(level_coefficient={1: 1.30, 2: 1.00, 3: 0.85})


def effective_minutes(act: ActType, level: Level, policy: Policy = DEFAULT_POLICY) -> float:
    """Handling time for one case at a given level."""
    return act.base_minutes * policy.level_coefficient[level]


def points_per_hour(act: ActType, level: Level, policy: Policy = DEFAULT_POLICY) -> float:
    """Yield in points per hour. Drives the mix, never the priority."""
    return act.points * 60 / effective_minutes(act, level, policy)


def is_cleared(act: ActType, level: Level) -> bool:
    return level in act.levels


def business_days_between(start: date, end: date) -> int:
    """Signed business days. Negative when `end` precedes `start`."""
    step = 1 if end >= start else -1
    low, high = (start, end) if step > 0 else (end, start)
    count = 0
    cursor = low
    while cursor < high:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            count += 1
    return count * step


def slack(today: date, due_on: date) -> int:
    """Business days left before the due date.

    Zero means due today, negative means past due. This is the ONLY quantity
    driving priority — handling time never enters the ordering.
    """
    return business_days_between(today, due_on)


def target_points(allocated_minutes: int) -> float:
    """100 points for a 7-hour day, prorated on time allocated.

    Callers pass the SUDE time, not the whole day: MH earn no points, so
    counting their minutes here would put a mobilised caseworker below
    trajectory for doing exactly what was asked (decision 3.16).
    """
    return REFERENCE_DAY_POINTS * allocated_minutes / REFERENCE_DAY_MINUTES


def required_points(allocated_minutes: int, minutes_worked: float) -> float:
    """Points needed at this point of the day to stay on trajectory."""
    if allocated_minutes <= 0:
        return 0.0
    share = min(1.0, minutes_worked / allocated_minutes)
    return target_points(allocated_minutes) * share


def split_quota(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Share a collective daily volume out in proportion to allocated time.

    Whole units only, summing exactly to `total`: the remainder goes to those
    with the largest fractional part, so a half-day never carries a full
    day's load. Ties break on the identifier, which keeps the split
    reproducible — two runs with the same input give the same shares.
    """
    eligible = {k: w for k, w in weights.items() if w > 0}
    pool = sum(eligible.values())
    if total <= 0 or pool <= 0:
        return dict.fromkeys(weights, 0)

    exact = {k: total * w / pool for k, w in eligible.items()}
    out = dict.fromkeys(weights, 0)
    for key, value in exact.items():
        out[key] = int(value)

    left = total - sum(out.values())
    order = sorted(exact, key=lambda k: (-(exact[k] - int(exact[k])), -eligible[k], k))
    for key in order[:left]:
        out[key] += 1
    return out


def lot_size(
    allocated_minutes: int, minutes_worked: float, policy: Policy = DEFAULT_POLICY
) -> float:
    """Work-in-hand target: a share of the remaining day, bounded.

    It shrinks on its own as the day ends, so nothing is handed out that would
    have to be returned to the backlog at closing time.
    """
    remaining = max(0.0, allocated_minutes - minutes_worked)
    if remaining <= 0:
        return 0.0
    share = remaining * policy.lot_share_of_remaining
    return min(policy.lot_max_minutes, max(policy.lot_min_minutes, share), remaining)


def can_be_trusted_with_urgency(worker: Caseworker) -> bool:
    return worker.trusted