from datetime import date

from dispatch.app.session import DaySession, WorkerState
from dispatch.domain.models import REFERENCE_DAY_MINUTES, HoldReason
from dispatch.sim.fixtures import ACT_TYPES, CASEWORKERS, make_backlog

TODAY = date(2026, 8, 25)


def build() -> DaySession:
    workers = {c.id: WorkerState(worker=c) for c in CASEWORKERS}
    session = DaySession(
        today=TODAY, types=ACT_TYPES, backlog=make_backlog(TODAY, seed=3), workers=workers
    )
    for worker_id in workers:
        session.refill(worker_id)
    return session


def busiest(session: DaySession) -> str:
    return max(session.workers, key=lambda w: len(session.workers[w].queue))


def test_holding_frees_a_slot_and_fills_it() -> None:
    """A case put on hold must not leave a hole: the caseworker never waits
    for the next lot."""
    session = build()
    worker_id = busiest(session)
    state = session.workers[worker_id]
    before = session.queue_minutes(state)
    item = state.queue[0]

    replacements = session.hold(worker_id, item.id, HoldReason.MISSING_DOCUMENT)

    assert item in session.held
    assert item not in state.queue
    assert replacements > 0
    assert session.queue_minutes(state) >= before * 0.8


def test_held_case_never_returns_to_a_lot() -> None:
    session = build()
    worker_id = busiest(session)
    item = session.workers[worker_id].queue[0]
    session.hold(worker_id, item.id, HoldReason.MEDICAL_OPINION)

    for _ in range(5):
        session.refill(worker_id)

    assert all(item not in s.queue for s in session.workers.values())


def test_resume_goes_back_to_the_origin() -> None:
    session = build()
    worker_id = busiest(session)
    item = session.workers[worker_id].queue[0]
    session.hold(worker_id, item.id, HoldReason.MEMBER_FOLLOW_UP)

    session.resume(item.id, worker_id)

    assert item in session.workers[worker_id].queue
    assert item.pushed
    assert item.held_reason is None


def test_urgency_is_offered_not_imposed() -> None:
    session = build()
    candidate = session.candidates_for("MAJ")[0]
    item = session.pushable("MAJ")[0]

    session.push_urgency(item.id, candidate.worker.id)

    assert item in session.offers[candidate.worker.id]
    assert item not in candidate.queue


def test_declining_costs_nothing_and_returns_it_to_the_bin() -> None:
    session = build()
    candidate = session.candidates_for("MAJ")[0]
    item = session.pushable("MAJ")[0]
    session.push_urgency(item.id, candidate.worker.id)

    session.decline_offer(candidate.worker.id, item.id)

    assert item in session.backlog
    assert item.pushed
    assert item.assigned_to is None
    assert item not in session.offers[candidate.worker.id]


def test_accepting_puts_it_in_the_lot() -> None:
    session = build()
    candidate = session.candidates_for("MAJ")[0]
    item = session.pushable("MAJ")[0]
    session.push_urgency(item.id, candidate.worker.id)

    session.accept_offer(candidate.worker.id, item.id)

    assert item in candidate.queue
    assert item.assigned_to == candidate.worker.id


def test_leaving_the_perimeter_only_returns_that_lot() -> None:
    """Nobody else's queue moves: colleagues pick the work up at their next
    refill, so there is no plan to recompute."""
    session = build()
    worker_id = busiest(session)
    others = {w: list(s.queue) for w, s in session.workers.items() if w != worker_id}

    returned = session.set_allocation(worker_id, 0)

    assert returned > 0
    assert session.workers[worker_id].queue == []
    for other_id, queue in others.items():
        assert session.workers[other_id].queue == queue


def test_target_follows_allocated_time() -> None:
    session = build()
    worker_id = busiest(session)
    session.set_allocation(worker_id, REFERENCE_DAY_MINUTES // 2)
    assert session.target(session.workers[worker_id]) == 50


def test_trusted_caseworkers_come_first() -> None:
    session = build()
    candidates = session.candidates_for("RECL")
    trusted = [c.worker.trusted for c in candidates]
    assert trusted == sorted(trusted, reverse=True)