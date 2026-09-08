"""Caseworker view: the lot in hand, and what can be done with it.

The caseworker keeps control here — free ordering inside the lot, urgencies
refused without justification, incomplete cases put on hold. See decision 3.5.
"""

from __future__ import annotations

import streamlit as st

from dispatch.app.session import DaySession
from dispatch.domain.models import HoldReason, WorkItem
from dispatch.domain.rules import effective_minutes
from dispatch.sim.fixtures import ACT_TYPES
from views.ui import (
    HOLD_LABELS,
    cell,
    cell_row,
    day_bar,
    days_of,
    help_note,
    lot_summary,
    tier_full,
    tier_legend,
)


def render_worker(session: DaySession, worker_id: str) -> None:
    state = session.workers[worker_id]
    level = state.worker.level
    points, target = session.points_earned(state), session.target(state)
    given = len(state.done) + len(state.queue)

    head = st.columns([3.4, 1, 1, 1, 1])
    head[0].markdown(f"### {state.worker.display_name}")
    head[1].metric("Reçus", given)
    head[2].metric("Traités", len(state.done))
    head[3].metric("En lot", len(state.queue))
    head[4].metric("Points", f"{points:.0f}/{target:.0f}")

    st.markdown(day_bar(session, state, height=20), unsafe_allow_html=True)
    st.markdown(lot_summary(session, state), unsafe_allow_html=True)
    tier_legend()

    tools = st.columns([1, 1, 1, 5])
    with tools[0]:
        help_note("lot")
    with tools[1]:
        help_note("tiers")
    with tools[2]:
        help_note("hold")

    for n, offer in enumerate(list(session.offers.get(worker_id, []))):
        act = ACT_TYPES[offer.type_code]
        with st.container(border=True):
            cols = st.columns([4, 1, 1])
            cols[0].markdown(
                f"**Urgence proposée** — {act.label}<br>"
                f"<span class='muted'>{offer.reference} · {act.points} points · "
                f"{effective_minutes(act, level):.0f} min · "
                "à traiter aujourd'hui</span>",
                unsafe_allow_html=True,
            )
            if cols[1].button("Accepter", key=f"ok-{worker_id}-{n}-{offer.id}"):
                session.accept_offer(worker_id, offer.id)
                st.rerun()
            if cols[2].button("Refuser", key=f"no-{worker_id}-{n}-{offer.id}"):
                session.decline_offer(worker_id, offer.id)
                st.toast("Urgence renvoyée en corbeille")
                st.rerun()

    if not state.queue:
        st.info("Lot vide — le réapprovisionnement se fait au fil du travail.")
        if state.done:
            st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
            st.markdown(f"#### Traités aujourd'hui — {len(state.done)}")
            st.markdown(
                cell_row(state.done, session, level, done=True), unsafe_allow_html=True
            )
        return

    # The lot is drawn by ascending slack, so everything in it is already the
    # most urgent work available. Sorting changes what comes first, never what
    # is shown: nothing ever disappears from the lot.
    def urgency_key(item: WorkItem) -> tuple[int, int, str, str]:
        return (0 if item.pushed else 1, days_of(item), item.type_code, item.reference)

    ordered = sorted(state.queue, key=urgency_key)
    urgent = [i for i in ordered if i.pushed or days_of(i) <= 0]
    present = sorted({i.type_code for i in ordered})

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    st.markdown(f"#### Votre lot — {len(ordered)} acte(s)")
    st.markdown(cell_row(ordered, session, level), unsafe_allow_html=True)

    bar = st.columns([5, 4])
    picked = bar[0].multiselect(
        "Remonter en tête",
        present,
        format_func=lambda c: (
            f"{ACT_TYPES[c].label} ({sum(1 for i in ordered if i.type_code == c)})"
        ),
        placeholder="Trier par urgence — ou choisir des types à traiter d'abord",
        label_visibility="collapsed",
    )

    if picked:
        chosen = [i for i in ordered if i.type_code in picked]
        rest = [i for i in ordered if i.type_code not in picked]
        shown = chosen + rest
        note = (
            f"{len(chosen)} acte(s) remonté(s) en tête, puis les {len(rest)} "
            "autre(s) — chaque groupe reste trié du plus en retard au plus "
            "confortable."
        )
    else:
        chosen, shown = [], ordered
        note = (
            f"{len(ordered)} acte(s) dans le lot, dont {len(urgent)} urgent(s), "
            "triés du plus en retard au plus confortable."
        )

    bar[1].markdown(
        f"<div style='padding-top:.35rem'><span class='muted'>{note}</span></div>",
        unsafe_allow_html=True,
    )

    for n, item in enumerate(shown):
        if picked and chosen and n == len(chosen):
            st.markdown(
                "<div class='muted' style='margin:.7rem 0 .2rem'>Le reste du lot</div>",
                unsafe_allow_html=True,
            )
        act = ACT_TYPES[item.type_code]
        days = days_of(item)
        cols = st.columns([1.3, 1.9, 3.6, 1, 1])
        cols[0].markdown(
            f"<div style='padding-top:.2rem'>{cell(item, session, level)}</div>",
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f"<div style='padding-top:.6rem;font-size:.82rem'>{item.reference}</div>",
            unsafe_allow_html=True,
        )
        cols[2].markdown(
            f"<div style='padding-top:.6rem'><span class='muted'>{act.label} · "
            f"{act.points} pts · {session.minutes_of(item, level):.0f} min · "
            f"{tier_full(days)}</span></div>",
            unsafe_allow_html=True,
        )
        if cols[3].button("Traiter", key=f"do-{item.id}"):
            session.complete(worker_id, item.id)
            st.rerun()
        with cols[4].popover("Attente"):
            st.caption(f"{item.reference} · {act.label}")
            reason = st.selectbox(
                "Motif",
                list(HoldReason),
                format_func=lambda r: HOLD_LABELS[r],
                key=f"why-{item.id}",
            )
            if st.button("Confirmer", key=f"hold-{item.id}"):
                n_repl = session.hold(worker_id, item.id, reason)
                st.toast(f"{item.reference} en attente · {n_repl} remplacement(s)")
                st.rerun()

    if state.done:
        st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
        st.markdown(f"#### Traités aujourd'hui — {len(state.done)}")
        st.markdown(
            cell_row(state.done, session, level, done=True), unsafe_allow_html=True
        )