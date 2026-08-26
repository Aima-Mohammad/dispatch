import random
from datetime import date, timedelta

from dispatch.domain.invariants import check_draw
from dispatch.domain.lot import DrawContext, draw_lot
from dispatch.domain.models import REFERENCE_DAY_MINUTES, ActType, WorkItem

TODAY = date(2026, 8, 25)
TYPES = {
    "PRE": ActType("PRE", "Prestations", 1.1, 90, 4, (1, 2, 3)),
    "REP": ActType("REP", "Réponse écrite", 2, 42, 3, (1, 2, 3)),
    "RECL": ActType("RECL", "Réclamation", 5, 20, 10, (2, 3)),
    "DEC": ActType("DEC", "Décès", 3.6, 28, 3, (3,)),
}


def make_backlog(rng: random.Random, size: int) -> list[WorkItem]:
    codes = list(TYPES)
    return [
        WorkItem(
            f"w{n}",
            f"SUDE-{n}",
            rng.choice(codes),
            TODAY + timedelta(days=rng.randint(-5, 12)),
        )
        for n in range(size)
    ]


def test_no_violation_over_random_draws() -> None:
    """Whatever the seed, the level or the time allocated, the rules hold.

    This is what guards against regressions the day the business changes a rule.
    """
    for seed in range(60):
        rng = random.Random(seed)
        backlog = make_backlog(rng, 200)
        allocated = rng.choice([REFERENCE_DAY_MINUTES, 336, 252, 126])
        ctx = DrawContext(
            "g-1",
            rng.choice([1, 2, 3]),
            allocated,
            rng.uniform(0, allocated),
            rng.uniform(0, 60),
        )
        draw = draw_lot(ctx, backlog, TYPES, TODAY)
        violations = check_draw(ctx, draw, backlog, TYPES, TODAY)
        assert violations == [], f"seed {seed}: {violations}"