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


@dataclass(slots=True)
class WorkerState:
    worker: Caseworker
    allocated_minutes: int = REFERENCE_DAY_MINUTES
    minutes_worked: float = 0.0
    queue: list[WorkItem] = field(default_factory=list)
    done: list[WorkItem] = field(default_factory=list)
    lots_served: int = 0

    @property
    def on_perimeter(self) -> bool:
        return self.allocated_minutes > 0


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
    journal: list[Event] = field(default_factory=list)
    clock_minutes: float = 0.0
    counter: int = 0
    offers: dict[str, list[WorkItem]] = field(default_factory=dict)
    hold_origin: dict[str, str] = field(default_factory=dict)

    # ---- read helpers -------------------------------------------------

    def minutes_of(self, item: WorkItem, level: int) -> float:
        return effective_minutes(self.types[item.type_code], level, self.policy)

    def queue_minutes(self, state: WorkerState) -> float:
        return sum(self.minutes_of(i, state.worker.level) for i in state.queue)

    def points_earned(self, state: WorkerState) -> float:
        return sum(self.types[i.type_code].points for i in state.done)

    def target(self, state: WorkerState) -> float:
        return target_points(state.allocated_minutes)

    def yield_rate(self, state: WorkerState) -> float:
        if state.minutes_worked <= 0:
            return 0.0
        return self.points_earned(state) * 60 / state.minutes_worked

    # ---- commands -----------------------------------------------------

    def refill(self, worker_id: str, minimum_minutes: float = 0.0) -> int:
        state = self.workers[worker_id]
        if not state.on_perimeter:
            return 0
        ctx = DrawContext(
            caseworker_id=worker_id,
            level=state.worker.level,
            allocated_minutes=state.allocated_minutes,
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
        self.hold_origin.pop(item.id, None)
        if to_worker and self.workers[to_worker].on_perimeter:
            item.assigned_to = to_worker
            self.workers[to_worker].queue.append(item)
        else:
            item.assigned_to = None
            self.backlog.append(item)

    def set_allocation(self, worker_id: str, minutes: int) -> int:
        """Change the time allocated to this perimeter. Zero means working
        elsewhere — never absent. Work that no longer fits returns to the
        backlog; nobody else's queue is touched."""
        state = self.workers[worker_id]
        state.allocated_minutes = minutes
        returned = 0
        while self.queue_minutes(state) > max(0.0, minutes - state.minutes_worked) + 1e-6:
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

    @property
    def urgency_bin(self) -> list[WorkItem]:
        """Urgencies dropped by the manager, waiting for anyone cleared."""
        return [i for i in self.backlog if i.pushed and i.assigned_to is None]

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

    def advance(self, minutes: float) -> None:
        """Move the clock and let everyone work at a nominal pace."""
        self.clock_minutes += minutes
        for worker_id, state in self.workers.items():
            if not state.on_perimeter:
                continue
            budget = min(self.clock_minutes, state.allocated_minutes) - state.minutes_worked
            while budget > 0 and state.queue:
                item = min(state.queue, key=lambda i: (not i.pushed, i.due_on))
                cost = self.minutes_of(item, state.worker.level)
                if cost > budget:
                    break
                self.complete(worker_id, item.id)
                budget -= cost

    def _log(self, state: WorkerState, label: str, item: WorkItem) -> None:
        self.journal.append(
            Event(
                at=self._clock_label(),
                label=f"{state.worker.display_name} — {label}",
                reference=item.reference,
            )
        )

    def _clock_label(self) -> str:
        total = int(8 * 60 + 30 + self.clock_minutes)
        return f"{total // 60:02d}:{total % 60:02d}"