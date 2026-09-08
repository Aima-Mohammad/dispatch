"""Quality control draws must be replayable and mutually independent."""

from __future__ import annotations

from datetime import date

from dispatch.domain.control import pick_caseworker, sample_controls
from dispatch.domain.models import WorkItem
from dispatch.sim.fixtures import ACT_TYPES, make_backlog

TODAY = date(2026, 8, 25)


def _items() -> list[WorkItem]:
    return make_backlog(TODAY)


def test_same_seed_gives_same_draw() -> None:
    rates = dict.fromkeys(ACT_TYPES, 0.03)
    first = sample_controls(_items(), rates, seed=42)
    second = sample_controls(_items(), rates, seed=42)
    assert [line.item_id for line in first] == [line.item_id for line in second]


def test_different_seed_gives_different_draw() -> None:
    rates = dict.fromkeys(ACT_TYPES, 0.03)
    first = sample_controls(_items(), rates, seed=1)
    second = sample_controls(_items(), rates, seed=2)
    assert [line.item_id for line in first] != [line.item_id for line in second]


def test_activities_are_independent() -> None:
    """Raising one activity's rate must not disturb another's selection."""
    base = dict.fromkeys(ACT_TYPES, 0.03)
    raised = {**base, "RECL": 0.5}
    before = sample_controls(_items(), base, seed=7)
    after = sample_controls(_items(), raised, seed=7)
    untouched_before = [ln.item_id for ln in before if ln.type_code != "RECL"]
    untouched_after = [ln.item_id for ln in after if ln.type_code != "RECL"]
    assert untouched_before == untouched_after


def test_zero_rate_is_never_controlled() -> None:
    rates = dict.fromkeys(ACT_TYPES, 0.03) | {"PRE": 0.0}
    lines = sample_controls(_items(), rates, seed=3)
    assert all(line.type_code != "PRE" for line in lines)


def test_minimum_one_can_be_disabled() -> None:
    rates = {"DEC": 0.001}
    with_min = sample_controls(_items(), rates, seed=5, minimum_one=True)
    without = sample_controls(_items(), rates, seed=5, minimum_one=False)
    assert len(with_min) == 1
    assert without == []


def test_pick_caseworker_ignores_input_order() -> None:
    assert pick_caseworker(["c", "a", "b"], seed=9) == pick_caseworker(
        ["a", "b", "c"], seed=9
    )