"""Lot drawing. The heart of the system.

Nothing is planned for the whole day: a caseworker holds a small amount of
work and is topped up as it runs down. Each draw reads the backlog as it
stands, so a case that arrived an hour ago enters the next lot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from dispatch.domain.models import ActType, WorkItem
from dispatch.domain.rules import (
    DEFAULT_POLICY,
    Policy,
    effective_minutes,
    is_cleared,
    lot_size,
    points_per_hour,
    required_points,
    slack,
)


@dataclass(slots=True)
class DrawContext:
    """Everything the engine needs to serve one caseworker, at one moment."""

    caseworker_id: str
    level: int
    allocated_minutes: int
    minutes_worked: float
    points_earned: float
    queue: list[WorkItem] = field(default_factory=list)


@dataclass(slots=True)
class Draw:
    items: list[WorkItem]
    minutes: float
    reason: str


def _queue_minutes(ctx: DrawContext, types: dict[str, ActType], policy: Policy) -> float:
    return sum(effective_minutes(types[i.type_code], ctx.level, policy) for i in ctx.queue)


def draw_lot(
    ctx: DrawContext,
    backlog: list[WorkItem],
    types: dict[str, ActType],
    today: date,
    policy: Policy = DEFAULT_POLICY,
    minimum_minutes: float = 0.0,
    reason: str = "lot",
) -> Draw:
    """Pick the next slice of work.

    Ordering, in this order and no other:
      1. manager-pushed urgencies, outside the work-in-hand budget;
      2. ascending slack — the most overdue first;
      3. at equal slack, a type already in the lot, so runs are not broken;
      4. at equal slack, yield according to the points trajectory: someone
         behind gets the better-scoring cases, someone ahead the others.

    `minimum_minutes` forces a top-up of at least that much, used when a case
    put on hold frees a slot that must be filled straight away.
    """
    held = _queue_minutes(ctx, types, policy)
    budget = lot_size(ctx.allocated_minutes, ctx.minutes_worked, policy) - held
    remaining = ctx.allocated_minutes - ctx.minutes_worked - held
    if minimum_minutes:
        budget = max(budget, minimum_minutes)
    budget = min(budget, remaining)
    if budget <= 2:
        return Draw([], 0.0, reason)

    behind = ctx.points_earned < required_points(ctx.allocated_minutes, ctx.minutes_worked)
    in_lot = {i.type_code for i in ctx.queue}
    picked: list[WorkItem] = []
    used = 0.0

    def sort_key(item: WorkItem) -> tuple[int, int, int, float]:
        act = types[item.type_code]
        yield_ = points_per_hour(act, ctx.level, policy)
        return (
            0 if item.pushed else 1,
            slack(today, item.due_on),
            0 if item.type_code in in_lot else 1,
            -yield_ if behind else yield_,
        )

    while used < budget - 2:
        available = [
            i
            for i in backlog
            if i.assigned_to is None
            and i.held_reason is None
            and is_cleared(types[i.type_code], ctx.level)
            and used + effective_minutes(types[i.type_code], ctx.level, policy) <= budget + 1e-6
        ]
        if not available:
            break
        chosen = min(available, key=sort_key)
        chosen.assigned_to = ctx.caseworker_id
        picked.append(chosen)
        in_lot.add(chosen.type_code)
        used += effective_minutes(types[chosen.type_code], ctx.level, policy)

    return Draw(picked, used, reason)