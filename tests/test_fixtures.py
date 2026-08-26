from datetime import date

from dispatch.sim.fixtures import ACT_TYPES, CASEWORKERS, make_backlog

from dispatch.domain.rules import slack

TODAY = date(2026, 8, 25)


def test_backlog_is_deterministic() -> None:
    a = make_backlog(TODAY, seed=7)
    b = make_backlog(TODAY, seed=7)
    assert [i.id for i in a] == [i.id for i in b]
    assert [i.due_on for i in a] == [i.due_on for i in b]


def test_backlog_holds_overdue_and_comfortable_work() -> None:
    backlog = make_backlog(TODAY)
    slacks = [slack(TODAY, i.due_on) for i in backlog]
    assert min(slacks) < 0
    assert max(slacks) > 2


def test_every_type_is_cleared_for_at_least_one_caseworker() -> None:
    levels = {c.level for c in CASEWORKERS}
    for act in ACT_TYPES.values():
        assert levels & set(act.levels)