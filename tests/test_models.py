from datetime import date

from dispatch.domain.models import REFERENCE_DAY_MINUTES, ActType, Allocation


def test_base_minutes_derives_from_cadence() -> None:
    claim = ActType("RECL", "Réclamation", 5, 20, 10, (2, 3))
    assert claim.base_minutes == 21


def test_target_points_are_prorated() -> None:
    half = Allocation("g-1", date(2026, 8, 25), REFERENCE_DAY_MINUTES // 2)
    assert half.target_points == 50