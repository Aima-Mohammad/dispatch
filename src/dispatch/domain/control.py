"""Quality control sampling.

Pure domain code: it decides which handled cases go to quality control, and
does it so that the draw can be replayed. Nothing here reads or writes files —
the caller owns the export and its labels.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from random import Random

from dispatch.domain.models import WorkItem

# Indicative only. Whether a ceiling on the control rate should block the
# manager or merely warn is still an open business question, so nothing in
# this module enforces it.
DEFAULT_CONTROL_RATE = 0.03


@dataclass(frozen=True, slots=True)
class ControlLine:
    """One case drawn for control, with the seed that produced the draw.

    The seed travels with the line because a control that cannot be replayed
    is contestable: anyone holding the seed and the same parameters gets the
    same cases back.
    """

    item_id: str
    reference: str
    type_code: str
    handled_by: str | None
    seed: int


def sample_controls(
    items: Iterable[WorkItem],
    rates: dict[str, float],
    seed: int,
    minimum_one: bool = True,
) -> list[ControlLine]:
    """Draw the cases to control, activity by activity.

    ``rates`` maps an activity code to a fraction between 0 and 1; an activity
    absent from it, or set to zero, is not controlled at all. ``minimum_one``
    guarantees one case per controlled activity that would otherwise round
    down to none.
    """
    by_type: dict[str, list[WorkItem]] = {}
    for item in items:
        if item.type_code in rates:
            by_type.setdefault(item.type_code, []).append(item)

    lines: list[ControlLine] = []
    for type_code, group in sorted(by_type.items()):
        rate = rates[type_code]
        if rate <= 0:
            continue

        # One generator per activity, derived from the seed and the code.
        # A single shared generator would make every activity's draw depend
        # on the rates of the others: raising one rate would reshuffle the
        # rest, and last month's control could no longer be replayed.
        rng = Random(f"{seed}:{type_code}")

        # Sorted before drawing: the caller's ordering must never influence
        # the result, otherwise the same seed stops meaning the same cases.
        ordered = sorted(group, key=lambda item: item.reference)

        # Rounded down rather than up: rounding up would systematically
        # over-control small volumes, which is exactly where the rate is
        # already the least meaningful.
        count = math.floor(len(ordered) * rate)
        if minimum_one and count == 0:
            count = 1
        count = min(count, len(ordered))

        lines.extend(
            ControlLine(
                item_id=item.id,
                reference=item.reference,
                type_code=item.type_code,
                handled_by=item.assigned_to,
                seed=seed,
            )
            for item in rng.sample(ordered, count)
        )

    return sorted(lines, key=lambda line: (line.type_code, line.reference))


def pick_caseworker(worker_ids: list[str], seed: int) -> str:
    """Draw one caseworker, reproducibly.

    Sorted first for the same reason as the cases: the order in which the
    caller happens to hold the identifiers must not change who comes out.
    """
    if not worker_ids:
        raise ValueError("no caseworker to pick from")
    return Random(seed).choice(sorted(worker_ids))