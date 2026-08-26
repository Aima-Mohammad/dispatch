from datetime import date

from dispatch.domain.lot import DrawContext, draw_lot
from dispatch.domain.models import REFERENCE_DAY_MINUTES, ActType, WorkItem

TODAY = date(2026, 8, 25)
TYPES = {
    "RECL": ActType("RECL", "Réclamation", 5, 20, 10, (2, 3)),
    "ADH": ActType("ADH", "Adhésion", 3, 37, 3, (1, 2, 3)),
    "MAJ": ActType("MAJ", "Mise à jour", 2, 55, 5, (1, 2, 3)),
}


def item(id_: str, type_code: str, due: date, *, pushed: bool = False) -> WorkItem:
    return WorkItem(id_, f"SUDE-{id_}", type_code, due, pushed=pushed)


def ctx(level: int = 2, worked: float = 0.0, points: float = 0.0) -> DrawContext:
    return DrawContext("g-1", level, REFERENCE_DAY_MINUTES, worked, points)


def test_overdue_comes_first_whatever_the_duration() -> None:
    backlog = [
        item("a", "MAJ", date(2026, 9, 10)),
        item("b", "RECL", date(2026, 8, 21)),
    ]
    draw = draw_lot(ctx(), backlog, TYPES, TODAY)
    assert draw.items[0].id == "b"


def test_pushed_urgency_wins_over_everything() -> None:
    backlog = [
        item("a", "RECL", date(2026, 8, 20)),
        item("b", "MAJ", date(2026, 9, 10), pushed=True),
    ]
    draw = draw_lot(ctx(), backlog, TYPES, TODAY)
    assert draw.items[0].id == "b"


def test_clearance_is_respected() -> None:
    backlog = [item("a", "RECL", date(2026, 8, 21))]
    draw = draw_lot(ctx(level=1), backlog, TYPES, TODAY)
    assert draw.items == []


def test_lot_never_exceeds_remaining_time() -> None:
    backlog = [item(str(n), "MAJ", date(2026, 9, 1)) for n in range(200)]
    draw = draw_lot(ctx(worked=REFERENCE_DAY_MINUTES - 10), backlog, TYPES, TODAY)
    assert draw.minutes <= 10


def test_hold_replacement_forces_a_top_up() -> None:
    backlog = [item(str(n), "MAJ", date(2026, 9, 1)) for n in range(50)]
    c = ctx()
    draw_lot(c, backlog, TYPES, TODAY)
    c.queue = [i for i in backlog if i.assigned_to == "g-1"]
    freed = 20.0
    top_up = draw_lot(c, backlog, TYPES, TODAY, minimum_minutes=freed, reason="replacement")
    assert top_up.minutes > 0