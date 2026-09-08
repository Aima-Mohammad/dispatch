"""Day session. Holds what the engine cannot: who has what, right now.

No business rule lives here — every decision is delegated to `domain`.
This layer only remembers, and orchestrates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from dispatch.domain.lot import DrawContext, draw_lot
from dispatch.domain.models import (
    REFERENCE_DAY_MINUTES,
    ActType,
    Caseworker,
    HoldReason,
    WorkItem,
)
from dispatch.domain.rules import DEFAULT_POLICY, Policy, effective_minutes, target_points

DAY_START_MINUTES = 8 * 60 + 30  # 08:30
DAY_END_MINUTES = 20 * 60  # 20:00
ASSUMED_LUNCH_MINUTES = 60  # never recorded, only assumed for projection


@dataclass(slots=True)
class WorkerState:
    worker: Caseworker
    allocated_minutes: int = REFERENCE_DAY_MINUTES
    overtime_minutes: int = 0
    minutes_worked: float = 0.0
    queue: list[WorkItem] = field(default_factory=list)
    done: list[WorkItem] = field(default_factory=list)
    lots_served: int = 0

    @property
    def on_perimeter(self) -> bool:
        return self.allocated_minutes > 0

    @property
    def working_minutes(self) -> int:
        """What the engine may fill. Overtime is decided by the manager and
        adds to the day, so it adds to the points target too."""
        return self.allocated_minutes + self.overtime_minutes

    @property
    def earliest_end(self) -> int:
        """Wall-clock minute the day can end at, assuming a lunch break.

        The break is never recorded — only assumed — so this is a floor, not a
        forecast: it tells the manager who cannot possibly finish in time.
        """
        return DAY_START_MINUTES + self.working_minutes + ASSUMED_LUNCH_MINUTES


@dataclass(slots=True)
class Event:
    at: str
    label: str
    reference: str


@dataclass(slots=True)
class DaySession:
    """One working day, for the whole team."""

    today: date
    types: dict[str, ActType]
    backlog: list[WorkItem]
    workers: dict[str, WorkerState]
    policy: Policy = DEFAULT_POLICY
    held: list[WorkItem] = field(default_factory=list)
    hold_origin: dict[str, str] = field(default_factory=dict)
    offers: dict[str, list[WorkItem]] = field(default_factory=dict)
    journal: list[Event] = field(default_factory=list)
    clock_minutes: float = 0.0

    # ---- read helpers -------------------------------------------------

    def minutes_of(self, item: WorkItem, level: int) -> float:
        return effective_minutes(self.types[item.type_code], level, self.policy)

    def queue_minutes(self, state: WorkerState) -> float:
        return sum(self.minutes_of(i, state.worker.level) for i in state.queue)

    def points_earned(self, state: WorkerState) -> float:
        return sum(self.types[i.type_code].points for i in state.done)

    def target(self, state: WorkerState) -> float:
        return target_points(state.working_minutes)

    def yield_rate(self, state: WorkerState) -> float:
        if state.minutes_worked <= 0:
            return 0.0
        return self.points_earned(state) * 60 / state.minutes_worked

    @property
    def urgency_bin(self) -> list[WorkItem]:
        """Urgencies dropped by the manager, waiting for anyone cleared."""
        return [i for i in self.backlog if i.pushed and i.assigned_to is None]

    @property
    def held_by_reason(self) -> dict[HoldReason, list[WorkItem]]:
        out: dict[HoldReason, list[WorkItem]] = {}
        for item in self.held:
            if item.held_reason:
                out.setdefault(item.held_reason, []).append(item)
        return out

    def held_by(self, item: WorkItem) -> str | None:
        """Who suspended this case — the one it goes back to when it wakes."""
        return self.hold_origin.get(item.id)

    def preview_first_lots(
        self, plan: dict[str, tuple[int, int]], on_date: date
    ) -> dict[str, list[WorkItem]]:
        """Draw tomorrow's opening lots without touching anything.

        The backlog is copied, so the simulation consumes nothing. What it
        shows is a forecast, not a commitment: the real draw happens on the
        day, against the stock as it stands then.
        """
        pool = [
            WorkItem(
                id=i.id,
                reference=i.reference,
                type_code=i.type_code,
                due_on=i.due_on,
                pushed=i.pushed,
            )
            for i in self.backlog + [q for s in self.workers.values() for q in s.queue]
            if i.held_reason is None
        ]
        pool += [
            WorkItem(
                id=i.id,
                reference=i.reference,
                type_code=i.type_code,
                due_on=i.due_on,
                pushed=i.pushed,
            )
            for v in self.offers.values()
            for i in v
        ]

        out: dict[str, list[WorkItem]] = {}
        # Trusted first, then the rest: whoever is served first gets the most
        # overdue work, which mirrors what happens on the day.
        order = sorted(
            self.workers.values(),
            key=lambda s: (not s.worker.trusted, -s.worker.level),
        )
        for state in order:
            allocated, overtime = plan.get(state.worker.id, (0, 0))
            working = allocated + overtime
            if working <= 0:
                out[state.worker.id] = []
                continue
            ctx = DrawContext(
                caseworker_id=state.worker.id,
                level=state.worker.level,
                allocated_minutes=working,
                minutes_worked=0.0,
                points_earned=0.0,
                queue=[],
            )
            drawn = draw_lot(ctx, pool, self.types, on_date, self.policy)
            out[state.worker.id] = drawn.items
        return out

    def pushable(self, type_code: str | None = None, limit: int = 40) -> list[WorkItem]:
        """Unassigned cases the manager can bring forward, most urgent first."""
        items = [
            i
            for i in self.backlog
            if i.assigned_to is None and i.held_reason is None and not i.pushed
        ]
        if type_code:
            items = [i for i in items if i.type_code == type_code]
        items.sort(key=lambda i: i.due_on)
        return items[:limit]

    def candidates_for(self, type_code: str, limit: int = 3) -> list[WorkerState]:
        """Trusted caseworkers first, then the lightest lot."""
        act = self.types[type_code]
        eligible = [
            s
            for s in self.workers.values()
            if s.on_perimeter and s.worker.level in act.levels
        ]
        eligible.sort(key=lambda s: (not s.worker.trusted, self.queue_minutes(s)))
        return eligible[:limit]

    # ---- commands -----------------------------------------------------

    def refill(self, worker_id: str, minimum_minutes: float = 0.0) -> int:
        state = self.workers[worker_id]
        if not state.on_perimeter:
            return 0
        ctx = DrawContext(
            caseworker_id=worker_id,
            level=state.worker.level,
            allocated_minutes=state.working_minutes,
            minutes_worked=state.minutes_worked,
            points_earned=self.points_earned(state),
            queue=state.queue,
        )
        drawn = draw_lot(
            ctx,
            self.backlog,
            self.types,
            self.today,
            self.policy,
            minimum_minutes=minimum_minutes,
        )
        state.queue.extend(drawn.items)
        if drawn.items and not minimum_minutes:
            state.lots_served += 1
        return len(drawn.items)

    def complete(self, worker_id: str, item_id: str) -> None:
        state = self.workers[worker_id]
        item = next(i for i in state.queue if i.id == item_id)
        state.queue.remove(item)
        state.done.append(item)
        state.minutes_worked += self.minutes_of(item, state.worker.level)
        self._log(state, "traité", item)
        self.refill(worker_id)

    def hold(self, worker_id: str, item_id: str, reason: HoldReason) -> int:
        """Suspend a case that cannot be handled. The freed slot is filled
        straight away — the caseworker never waits for the next lot."""
        state = self.workers[worker_id]
        item = next(i for i in state.queue if i.id == item_id)
        freed = self.minutes_of(item, state.worker.level)
        state.queue.remove(item)
        item.held_reason = reason
        item.assigned_to = None
        self.held.append(item)
        self.hold_origin[item.id] = worker_id
        self._log(state, f"mis en attente — {reason.value}", item)
        return self.refill(worker_id, minimum_minutes=freed)

    def resume(self, item_id: str, to_worker: str | None = None) -> None:
        """Wake a held case. It comes back as an urgency, with priority to the
        caseworker who suspended it."""
        item = next(i for i in self.held if i.id == item_id)
        self.held.remove(item)
        item.held_reason = None
        item.pushed = True
        if to_worker and self.workers[to_worker].on_perimeter:
            item.assigned_to = to_worker
            self.workers[to_worker].queue.append(item)
        else:
            item.assigned_to = None
            self.backlog.append(item)

    def push_urgency(self, item_id: str, worker_id: str | None = None) -> WorkItem:
        """Promote an existing case to urgency.

        A pushed urgency is not a new case: it is one the manager decides to
        bring forward. Named ones are offered, not imposed — the caseworker
        accepts or declines. Unnamed ones land in the bin, where the first
        cleared refill picks them up.
        """
        item = next(i for i in self.backlog if i.id == item_id)
        item.pushed = True
        if worker_id and self.workers[worker_id].on_perimeter:
            self.backlog.remove(item)
            self.offers.setdefault(worker_id, []).append(item)
        return item

    def accept_offer(self, worker_id: str, item_id: str) -> None:
        item = next(i for i in self.offers.get(worker_id, []) if i.id == item_id)
        self.offers[worker_id].remove(item)
        item.assigned_to = worker_id
        self.workers[worker_id].queue.append(item)
        self._log(self.workers[worker_id], "urgence acceptée", item)

    def decline_offer(self, worker_id: str, item_id: str) -> None:
        """Declining costs nothing and is never recorded against anyone.
        The case goes back to the bin, where any cleared caseworker finds it."""
        item = next(i for i in self.offers.get(worker_id, []) if i.id == item_id)
        self.offers[worker_id].remove(item)
        item.assigned_to = None
        self.backlog.append(item)

    def set_allocation(self, worker_id: str, minutes: int) -> int:
        """Change the time allocated to this perimeter. Zero means working
        elsewhere — never absent. Work that no longer fits returns to the
        backlog; nobody else's queue is touched."""
        state = self.workers[worker_id]
        state.allocated_minutes = minutes
        returned = 0
        room = max(0.0, state.working_minutes - state.minutes_worked)
        while self.queue_minutes(state) > room + 1e-6:
            if not state.queue:
                break
            item = max(state.queue, key=lambda i: i.due_on)
            state.queue.remove(item)
            item.assigned_to = None
            self.backlog.append(item)
            returned += 1
        if minutes > 0:
            self.refill(worker_id)
        return returned

    def set_overtime(self, worker_id: str, minutes: int) -> int:
        """Extra time beyond the allocated day, decided by the manager.
        The target follows, so overtime is paid in points as well as in hours."""
        state = self.workers[worker_id]
        state.overtime_minutes = minutes
        return self.refill(worker_id)

    def advance(self, minutes: float) -> None:
        """Move the clock and let everyone work at a nominal pace.

        Two limits apply, and both matter: nobody can have worked more than
        the time actually elapsed since opening — minus the assumed break —
        and nobody works beyond their allocated day.
        """
        span = DAY_END_MINUTES - DAY_START_MINUTES
        self.clock_minutes = min(span, self.clock_minutes + minutes)
        # The break is assumed to be taken midway; before that, the full
        # elapsed time counts as workable.
        elapsed = self.clock_minutes
        if elapsed > span / 2:
            elapsed = max(span / 2, elapsed - ASSUMED_LUNCH_MINUTES)

        for worker_id, state in self.workers.items():
            if not state.on_perimeter:
                continue
            guard = 0
            while guard < 500:
                guard += 1
                budget = min(elapsed, state.working_minutes) - state.minutes_worked
                if budget <= 0:
                    break
                if not state.queue:
                    self.refill(worker_id)
                    if not state.queue:
                        break
                item = min(state.queue, key=lambda i: (not i.pushed, i.due_on))
                cost = self.minutes_of(item, state.worker.level)
                if cost > budget:
                    break
                self.complete(worker_id, item.id)

    def _log(self, state: WorkerState, label: str, item: WorkItem) -> None:
        self.journal.append(
            Event(
                at=self._clock_label(),
                label=f"{state.worker.display_name} — {label}",
                reference=item.reference,
            )
        )

    def _clock_label(self) -> str:
        total = int(DAY_START_MINUTES + self.clock_minutes)
        return f"{total // 60:02d}:{total % 60:02d}"