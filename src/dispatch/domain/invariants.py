"""The rules agreed during design, in executable form.

They serve three purposes: unit tests on reference scenarios, property tests
on random draws, and a guard on real draws before release. A rule that is not
here is not a rule: it is an intention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from dispatch.domain.lot import Draw, DrawContext
from dispatch.domain.models import ActType, WorkItem
from dispatch.domain.rules import (
    DEFAULT_POLICY,
    Policy,
    effective_minutes,
    is_cleared,
    lot_size,
    slack,
)


@dataclass(frozen=True, slots=True)
class Violation:
    rule: str
    detail: str


def check_draw(
    ctx: DrawContext,
    draw: Draw,
    backlog: list[WorkItem],
    types: dict[str, ActType],
    today: date,
    policy: Policy = DEFAULT_POLICY,
) -> list[Violation]:
    v: list[Violation] = []

    # R1 - Clearance. Nobody handles a case above their level.
    for item in draw.items:
        if not is_cleared(types[item.type_code], ctx.level):
            v.append(Violation("R1_CLEARANCE", f"{item.reference} is above level {ctx.level}"))

    # R2 - Slack priority. No unpicked case may be more urgent than a picked
    # one, when it would have fitted. Duration plays no part here.
    if draw.items:
        worst = max(slack(today, i.due_on) for i in draw.items if not i.pushed) if any(
            not i.pushed for i in draw.items
        ) else None
        if worst is not None:
            for item in backlog:
                if item.assigned_to is not None or item.held_reason is not None:
                    continue
                if not is_cleared(types[item.type_code], ctx.level):
                    continue
                if slack(today, item.due_on) >= worst:
                    continue
                fits = effective_minutes(types[item.type_code], ctx.level, policy)
                if draw.minutes + fits <= _budget(ctx, types, policy) + 1e-6:
                    v.append(
                        Violation(
                            "R2_SLACK_PRIORITY",
                            f"{item.reference} is more urgent than picked work and would fit",
                        )
                    )

    # R3 - Work in hand never exceeds the remaining allocated time.
    held = sum(effective_minutes(types[i.type_code], ctx.level, policy) for i in ctx.queue)
    remaining = max(0.0, ctx.allocated_minutes - ctx.minutes_worked)
    if held + draw.minutes > remaining + 1e-6:
        v.append(
            Violation(
                "R3_CAPACITY",
                f"{held + draw.minutes:.0f} min in hand for {remaining:.0f} min left",
            )
        )

    # R4 - A case is picked once and only once.
    seen: set[str] = set()
    for item in draw.items:
        if item.id in seen:
            v.append(Violation("R4_UNIQUENESS", f"{item.reference} picked twice"))
        seen.add(item.id)

    # R5 - Held cases never enter a lot.
    for item in draw.items:
        if item.held_reason is not None:
            v.append(Violation("R5_HELD_STAYS_OUT", f"{item.reference} is on hold"))

    return v


def _budget(ctx: DrawContext, types: dict[str, ActType], policy: Policy) -> float:
    held = sum(effective_minutes(types[i.type_code], ctx.level, policy) for i in ctx.queue)
    return lot_size(ctx.allocated_minutes, ctx.minutes_worked, policy) - held