from datetime import date

from dispatch.domain.models import REFERENCE_DAY_MINUTES, ActType
from dispatch.domain.rules import (
    business_days_between,
    effective_minutes,
    lot_size,
    required_points,
    slack,
    target_points,
)

CLAIM = ActType("RECL", "Réclamation", 5, 20, 10, (2, 3))


def test_weekends_are_skipped() -> None:
    friday, monday = date(2026, 8, 21), date(2026, 8, 24)
    assert business_days_between(friday, monday) == 1


def test_slack_is_negative_when_past_due() -> None:
    assert slack(date(2026, 8, 25), date(2026, 8, 21)) == -2


def test_junior_takes_longer_than_expert() -> None:
    assert effective_minutes(CLAIM, 1) > effective_minutes(CLAIM, 3)


def test_target_is_prorated() -> None:
    assert target_points(REFERENCE_DAY_MINUTES) == 100
    assert target_points(REFERENCE_DAY_MINUTES // 2) == 50


def test_required_points_follow_the_day() -> None:
    assert required_points(REFERENCE_DAY_MINUTES, 0) == 0
    assert required_points(REFERENCE_DAY_MINUTES, 210) == 50


def test_lot_shrinks_as_the_day_ends() -> None:
    early = lot_size(REFERENCE_DAY_MINUTES, 0)
    late = lot_size(REFERENCE_DAY_MINUTES, 400)
    assert early > late
    assert late <= REFERENCE_DAY_MINUTES - 400