"""Streamlit prototype. Throwaway UI on top of the real engine.

Only here to test flows and rules with actual users — not a production front.
"""

from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

from dispatch.app.session import DaySession, WorkerState
from dispatch.domain.models import REFERENCE_DAY_MINUTES, HoldReason, WorkItem
from dispatch.domain.rules import effective_minutes, slack, target_points
from dispatch.sim.fixtures import ACT_TYPES, CASEWORKERS, DAILY_ARRIVALS, make_backlog

TODAY = date(2026, 8, 25)
URGENT = -999
ALLOCATIONS = [420, 336, 252, 210, 126, 0]

TIERS = {-3: "#4f1616", -2: "#8a2828", -1: "#c93b38", 0: "#e8a317", 1: "#6f7d8b", 2: "#a8a69e"}
HOLD_LABELS = {
    HoldReason.MISSING_DOCUMENT: "Pièce manquante",
    HoldReason.MEMBER_FOLLOW_UP: "Relance adhérent",
    HoldReason.MEDICAL_OPINION: "Avis médical",
    HoldReason.THIRD_PARTY: "Attente d'un tiers",
}

CSS = """
<style>
  .block-container {padding-top: 2.2rem; padding-bottom: 2rem;}
  div[data-testid="stMetricValue"] {font-size: 1.4rem;}
  div[data-testid="stMetricLabel"] {font-size: .78rem;}
  .stButton button {padding: .15rem .6rem; font-size: .8rem; min-height: 0;}
  .chip {display:inline-flex; align-items:center; gap:5px; padding:2px 8px;
         border-radius:5px; font-size:.74rem; background:rgba(128,128,128,.12);}
  .dot {width:9px; height:9px; border-radius:2px; display:inline-block;}
  .muted {color:#8a8880; font-size:.74rem;}
</style>
"""


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------


def tier_label(days: int) -> str:
    if days <= URGENT:
        return "urgence"
    if days < 0:
        return f"J{days}"
    return "J" if days == 0 else f"J+{days}"


def tier_full(days: int) -> str:
    if days <= URGENT:
        return "Urgence poussée"
    if days < 0:
        return f"butoir dépassé de {-days} j"
    return "échoit aujourd'hui" if days == 0 else f"butoir dans {days} j"


def tier_colour(days: int) -> str:
    if days <= URGENT:
        return "#4a3aa7"
    return TIERS.get(max(-3, min(2, days)), "#d2d0c7")


def hm(minutes: float) -> str:
    if minutes <= 0:
        return "0 h"
    return f"{int(minutes // 60)} h {int(minutes % 60):02d}"


def by_tier(session: DaySession, items: list[WorkItem]) -> dict[int, list[WorkItem]]:
    out: dict[int, list[WorkItem]] = {}
    for item in items:
        key = URGENT if item.pushed else slack(TODAY, item.due_on)
        out.setdefault(key, []).append(item)
    return out


@st.cache_resource
def bootstrap() -> DaySession:
    backlog = make_backlog(TODAY)
    workers = {c.id: WorkerState(worker=c) for c in CASEWORKERS}
    session = DaySession(today=TODAY, types=ACT_TYPES, backlog=backlog, workers=workers)
    for worker_id in workers:
        session.refill(worker_id)
    return session


def day_bar(session: DaySession, state: WorkerState, height: int = 26) -> str:
    """One block per due-date tier: width is time, the figure is the count."""
    if not state.on_perimeter:
        return (
            f"<div style='height:{height}px;display:flex;align-items:center;"
            "padding-left:9px;font-size:11px;color:#8a8880'>hors périmètre</div>"
        )

    groups: dict[int, list[tuple[float, bool]]] = {}
    pairs = [(i, True) for i in state.done] + [(i, False) for i in state.queue]
    for item, done in pairs:
        key = URGENT if item.pushed else slack(TODAY, item.due_on)
        groups.setdefault(key, []).append(
            (session.minutes_of(item, state.worker.level), done)
        )

    blocks = []
    for days in sorted(groups):
        cells = groups[days]
        width = sum(m for m, _ in cells)
        opacity = 1.0 if all(d for _, d in cells) else 0.5
        blocks.append(
            f"<div title='{tier_full(days)} · {len(cells)} acte(s)' "
            f"style='flex:{width:.0f} 0 0;min-width:22px;background:{tier_colour(days)};"
            f"opacity:{opacity};display:flex;align-items:center;justify-content:center;"
            f"border-right:1px solid rgba(255,255,255,.6);color:#fff;font-size:10px;"
            f"font-weight:600'>{len(cells)}</div>"
        )

    used = state.minutes_worked + session.queue_minutes(state)
    free = max(0.0, state.allocated_minutes - used)
    if free > 2:
        blocks.append(
            f"<div style='flex:{free:.0f} 0 0;min-width:16px;"
            "border:1.5px dashed rgba(128,128,128,.4);border-radius:3px'></div>"
        )

    pct = state.allocated_minutes / REFERENCE_DAY_MINUTES * 100
    return (
        f"<div style='display:flex'><div style='width:{pct:.0f}%;display:flex;"
        f"height:{height}px;background:rgba(128,128,128,.12);border-radius:3px;"
        f"overflow:hidden'>{''.join(blocks)}</div></div>"
    )


# --------------------------------------------------------------------------
# Caseworker view
# --------------------------------------------------------------------------


def render_worker(session: DaySession, worker_id: str) -> None:
    state = session.workers[worker_id]
    points, target = session.points_earned(state), session.target(state)

    head = st.columns([3, 1, 1, 1, 1])
    head[0].markdown(f"### {state.worker.display_name}")
    head[1].metric("Traités", len(state.done))
    head[2].metric("Points", f"{points:.0f}/{target:.0f}")
    head[3].metric("Lot", len(state.queue))
    head[4].metric("Journée", hm(state.minutes_worked))

    st.markdown(day_bar(session, state, height=22), unsafe_allow_html=True)

    for n, offer in enumerate(list(session.offers.get(worker_id, []))):
        act = ACT_TYPES[offer.type_code]
        with st.container(border=True):
            cols = st.columns([4, 1, 1])
            cols[0].markdown(
                f"**Urgence proposée** — {act.label}<br>"
                f"<span class='muted'>{offer.reference} · {act.points} points · "
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
        return

    tiers = by_tier(session, state.queue)
    current = min(tiers)

    locked = [t for t in sorted(tiers) if t > current]
    if locked:
        chips = " ".join(
            f"<span class='chip'><span class='dot' style='background:{tier_colour(t)}'>"
            f"</span>{tier_label(t)} · {len(tiers[t])}</span>"
            for t in locked
        )
        st.markdown(
            f"<span class='muted'>Ensuite, verrouillé :</span> {chips}",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"<span class='dot' style='background:{tier_colour(current)}'></span> "
        f"<b>{tier_label(current)}</b> — {tier_full(current)} · "
        f"{len(tiers[current])} acte(s) · <span class='muted'>ordre libre "
        "dans ce palier</span>",
        unsafe_allow_html=True,
    )

    by_type: dict[str, list[WorkItem]] = {}
    for item in tiers[current]:
        by_type.setdefault(item.type_code, []).append(item)

    for code, group in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        with st.expander(f"{len(group)} × {ACT_TYPES[code].label}", expanded=True):
            for item in group:
                cols = st.columns([4, 1, 1])
                cols[0].markdown(
                    f"<span style='font-size:.82rem'>{item.reference}</span>",
                    unsafe_allow_html=True,
                )
                if cols[1].button("Traiter", key=f"do-{item.id}"):
                    session.complete(worker_id, item.id)
                    st.rerun()
                with cols[2].popover("Attente"):
                    reason = st.selectbox(
                        "Motif",
                        list(HoldReason),
                        format_func=lambda r: HOLD_LABELS[r],
                        key=f"why-{item.id}",
                    )
                    if st.button("Confirmer", key=f"hold-{item.id}"):
                        n = session.hold(worker_id, item.id, reason)
                        st.toast(f"{item.reference} en attente · {n} remplacement(s)")
                        st.rerun()


# --------------------------------------------------------------------------
# Manager view
# --------------------------------------------------------------------------


def render_lot_detail(session: DaySession, state: WorkerState) -> None:
    """Read-only for the manager: what this caseworker holds, by tier and type."""
    st.markdown(f"**{state.worker.display_name}**")
    st.caption(
        f"{hm(state.minutes_worked)} travaillées · {len(state.done)} traité(s) · "
        f"{len(state.queue)} en lot · {state.lots_served} lot(s) servis"
    )

    if not state.queue:
        st.write("Lot vide.")
    for days, items in sorted(by_tier(session, state.queue).items()):
        st.markdown(
            f"<span class='dot' style='background:{tier_colour(days)}'></span> "
            f"<b>{tier_label(days)}</b> — {tier_full(days)} · {len(items)} acte(s)",
            unsafe_allow_html=True,
        )
        by_type: dict[str, list[WorkItem]] = {}
        for item in items:
            by_type.setdefault(item.type_code, []).append(item)
        for code, group in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
            refs = ", ".join(i.reference for i in group[:6])
            more = f" et {len(group) - 6} autre(s)" if len(group) > 6 else ""
            st.markdown(
                f"<span class='muted'>{len(group)} × {ACT_TYPES[code].label} — "
                f"{refs}{more}</span>",
                unsafe_allow_html=True,
            )

    if state.done:
        st.markdown("---")
        st.caption(f"Derniers traités — {len(state.done)} au total")
        for item in state.done[-6:]:
            st.markdown(
                f"<span class='muted'>{item.reference} · "
                f"{ACT_TYPES[item.type_code].label}</span>",
                unsafe_allow_html=True,
            )


def tomorrow_forecast(session: DaySession) -> tuple[int, float]:
    count, minutes = 0, 0.0
    for item in session.backlog:
        if slack(TODAY + timedelta(days=1), item.due_on) <= 0:
            count += 1
            act = session.types[item.type_code]
            minutes += effective_minutes(act, min(act.levels))
    for code, volume in DAILY_ARRIVALS.items():
        act = session.types[code]
        if act.sla_days <= 1:
            count += volume
            minutes += volume * effective_minutes(act, min(act.levels))
    return count, minutes


def render_today(session: DaySession) -> None:
    m = st.columns(5)
    m[0].metric("Heure", session._clock_label())
    m[1].metric("Alloué", hm(sum(s.allocated_minutes for s in session.workers.values())))
    m[2].metric("Traités", sum(len(s.done) for s in session.workers.values()))
    m[3].metric("Corbeille", len(session.urgency_bin))
    m[4].metric("En attente", len(session.held))

    bar = st.columns([1, 1, 2.2, 3, 1.4, 1.4])
    if bar[0].button("+15 min", use_container_width=True):
        session.advance(15)
        st.rerun()
    if bar[1].button("+1 h", use_container_width=True):
        session.advance(60)
        st.rerun()
    code = bar[2].selectbox(
        "Type",
        [None, *ACT_TYPES],
        format_func=lambda c: "Tous les types" if c is None else ACT_TYPES[c].label,
        label_visibility="collapsed",
    )
    picked = bar[3].selectbox(
        "Dossier",
        session.pushable(code),
        format_func=lambda i: (
            f"{i.reference} · {ACT_TYPES[i.type_code].label} · "
            f"{tier_label(slack(TODAY, i.due_on))}"
        ),
        index=None,
        placeholder="Choisir un dossier du stock…",
        label_visibility="collapsed",
    )
    if bar[4].button("Attribuer", use_container_width=True, disabled=picked is None):
        st.session_state["pending"] = picked.id if picked else None
    to_bin = bar[5].button("En corbeille", use_container_width=True, disabled=picked is None)
    if to_bin and picked:
        session.push_urgency(picked.id)
        st.toast(f"{picked.reference} passé en urgence, en corbeille")
        st.rerun()

    if st.session_state.get("pending"):
        item = next(
            (i for i in session.backlog if i.id == st.session_state["pending"]), None
        )
        if item is None:
            st.session_state["pending"] = None
        else:
            act = ACT_TYPES[item.type_code]
            days = slack(TODAY, item.due_on)
            levels = ", ".join(str(n) for n in act.levels)
            with st.container(border=True):
                st.markdown(
                    f"**{item.reference}** — {act.label}<br>"
                    f"<span class='muted'>{tier_full(days)} · {act.points} points · "
                    f"niveaux habilités {levels}</span>",
                    unsafe_allow_html=True,
                )
                st.caption("Confiance d'abord, puis le lot le moins chargé.")
                for state in session.candidates_for(item.type_code):
                    cols = st.columns([3, 2, 1])
                    tag = " · confiance" if state.worker.trusted else ""
                    cols[0].write(f"{state.worker.display_name}{tag}")
                    cols[1].markdown(
                        f"<span class='muted'>{hm(session.queue_minutes(state))} "
                        "en lot</span>",
                        unsafe_allow_html=True,
                    )
                    if cols[2].button("Choisir", key=f"give-{state.worker.id}"):
                        session.push_urgency(item.id, state.worker.id)
                        st.session_state["pending"] = None
                        st.toast(f"{item.reference} proposé à {state.worker.display_name}")
                        st.rerun()
                if st.button("Annuler"):
                    st.session_state["pending"] = None
                    st.rerun()

    waiting = sum(len(v) for v in session.offers.values())
    if waiting:
        who = ", ".join(
            session.workers[w].worker.display_name for w, v in session.offers.items() if v
        )
        st.caption(f"**{waiting} urgence(s) proposée(s)**, en attente de réponse — {who}")

    st.markdown(
        "<div class='muted'>Gestionnaire · temps alloué · journée · points</div>",
        unsafe_allow_html=True,
    )

    for worker_id, state in session.workers.items():
        cols = st.columns([1.9, 1.3, 5.4, 1.4, 1])
        tag = "confiance" if state.worker.trusted else f"niv. {state.worker.level}"
        cols[0].markdown(
            f"<b style='font-size:.85rem'>{state.worker.display_name}</b><br>"
            f"<span class='muted'>{tag}</span>",
            unsafe_allow_html=True,
        )
        choice = cols[1].selectbox(
            "Temps",
            ALLOCATIONS,
            index=ALLOCATIONS.index(state.allocated_minutes)
            if state.allocated_minutes in ALLOCATIONS
            else 0,
            format_func=hm,
            key=f"alloc-{worker_id}",
            label_visibility="collapsed",
        )
        if choice != state.allocated_minutes:
            returned = session.set_allocation(worker_id, choice)
            st.toast(f"{state.worker.display_name} — {returned} acte(s) rendus au stock")
            st.rerun()
        cols[2].markdown(day_bar(session, state), unsafe_allow_html=True)
        points, target = session.points_earned(state), session.target(state)
        rate = int(points / target * 100) if target else 0
        cols[3].markdown(
            f"<span style='font-size:.82rem'>{points:.0f}/{target:.0f}</span><br>"
            f"<span class='muted'>{rate if state.minutes_worked else '—'} %</span>",
            unsafe_allow_html=True,
        )
        with cols[4].popover("Détail"):
            render_lot_detail(session, state)


def render_bins(session: DaySession) -> None:
    """Two opposite queues: what should already be running, and what cannot."""
    urgent, waiting = st.tabs(
        [f"Urgences ({len(session.urgency_bin)})", f"En attente ({len(session.held)})"]
    )

    with urgent:
        st.caption(
            "Sans gestionnaire nommé. Reprises en tête du prochain lot d'un "
            "habilité — aucune action requise ici."
        )
        if not session.urgency_bin:
            st.info("Corbeille vide.")
        for item in session.urgency_bin:
            act = ACT_TYPES[item.type_code]
            cols = st.columns([2, 3, 2, 2])
            cols[0].markdown(
                f"<span style='font-size:.82rem'>{item.reference}</span>",
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f"<span class='muted'>{act.label}</span>", unsafe_allow_html=True
            )
            cols[2].markdown(
                f"<span class='muted'>{act.points} pts · "
                f"{effective_minutes(act, min(act.levels)):.0f} min</span>",
                unsafe_allow_html=True,
            )
            cols[3].markdown(
                f"<span class='muted'>niveaux "
                f"{', '.join(str(n) for n in act.levels)}</span>",
                unsafe_allow_html=True,
            )

    with waiting:
        st.caption(
            "Hors flux tant que la pièce manque, mais le délai continue de courir. "
            "La mise en attente et le réveil appartiennent au gestionnaire — "
            "n'intervenez que sur les dossiers qui traînent."
        )
        if not session.held:
            st.info("Aucun dossier en attente.")
            return

        summary = " · ".join(
            f"{len(v)} {HOLD_LABELS[k].lower()}"
            for k, v in session.held_by_reason.items()
        )
        st.markdown(f"**{len(session.held)} dossier(s)** — {summary}")

        for reason, items in session.held_by_reason.items():
            st.markdown(f"**{HOLD_LABELS[reason]}** — {len(items)}")
            for item in items:
                origin = session.held_by(item)
                who = session.workers[origin].worker.display_name if origin else "—"
                days = slack(TODAY, item.due_on)
                cols = st.columns([2, 3, 2, 1.4, 1.4])
                cols[0].markdown(
                    f"<span style='font-size:.82rem'>{item.reference}</span>",
                    unsafe_allow_html=True,
                )
                cols[1].markdown(
                    f"<span class='muted'>{ACT_TYPES[item.type_code].label}</span>",
                    unsafe_allow_html=True,
                )
                cols[2].markdown(
                    f"<span class='muted'>{who} · {tier_label(days)}</span>",
                    unsafe_allow_html=True,
                )
                if cols[3].button("Réveiller", key=f"wake-{item.id}"):
                    session.resume(item.id, origin)
                    st.toast(f"{item.reference} réactivé chez {who}")
                    st.rerun()
                if cols[4].button("Déléguer", key=f"deleg-{item.id}"):
                    session.resume(item.id, None)
                    st.toast(f"{item.reference} renvoyé en corbeille")
                    st.rerun()


def render_performance(session: DaySession) -> None:
    """What a relationship manager actually needs to decide something.

    Four questions: am I holding my deadlines, who is drifting, where is the
    backlog ageing, and do urgencies always land on the same people.
    """
    states = list(session.workers.values())
    active = [s for s in states if s.minutes_worked > 0]
    names = [s.worker.display_name for s in states]

    worked = sum(s.minutes_worked for s in states)
    points = sum(session.points_earned(s) for s in states)
    unassigned = [i for i in session.backlog if i.assigned_to is None]
    overdue = [i for i in unassigned if slack(TODAY, i.due_on) < 0]
    due_today = [i for i in unassigned if slack(TODAY, i.due_on) == 0]

    m = st.columns(5)
    m[0].metric("Traités", sum(len(s.done) for s in states))
    m[1].metric("Rendement", f"{points * 60 / worked:.1f} pts/h" if worked else "—")
    m[2].metric("Hors délai en stock", len(overdue))
    m[3].metric("Échoit aujourd'hui", len(due_today))
    spread = 0
    if len(active) > 1:
        rates = [session.points_earned(s) / session.target(s) for s in active if session.target(s)]
        spread = int((max(rates) - min(rates)) * 100) if rates else 0
    m[4].metric("Écart de rendement", f"{spread} pts")

    if overdue:
        st.warning(
            f"{len(overdue)} dossier(s) hors délai encore non affectés. "
            "Ils passeront en tête du prochain lot d'un habilité."
        )

    # ---- Distributed against completed, per caseworker --------------------

    st.markdown("#### Distribué et accompli")
    st.caption(
        "Deux barres par personne : ce qui a été donné, ce qui a été fait. "
        "L'écart est ce qui repartirait au stock ce soir."
    )
    given = [len(s.done) + len(s.queue) for s in states]
    completed = [len(s.done) for s in states]
    fig = go.Figure()
    fig.add_bar(
        name="Distribué", x=names, y=given, marker_color="#c8c6bd",
        text=given, textposition="outside",
    )
    fig.add_bar(
        name="Accompli", x=names, y=completed, marker_color="#4a3aa7",
        text=completed, textposition="outside",
    )
    fig.update_layout(
        barmode="group",
        bargap=0.25,
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", y=1.12, x=0),
        yaxis_title="actes",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---- Points against target, diverging --------------------------------

    st.markdown("#### Écart à la cible du jour")
    st.caption(
        "Points acquis moins points attendus à cette heure. En dessous de zéro, "
        "le mix ou le rythme ne suivent pas."
    )
    gaps, colours, labels = [], [], []
    for state in states:
        target = session.target(state)
        if target <= 0:
            continue
        expected = target * min(1.0, state.minutes_worked / state.allocated_minutes)
        gap = session.points_earned(state) - expected
        gaps.append(gap)
        labels.append(state.worker.display_name)
        colours.append("#1baf7a" if gap >= 0 else "#c93b38")
    fig2 = go.Figure(
        go.Bar(
            x=gaps, y=labels, orientation="h", marker_color=colours,
            text=[f"{g:+.0f}" for g in gaps], textposition="outside",
        )
    )
    fig2.update_layout(
        height=max(240, 34 * len(labels)),
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="points d'écart",
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ---- Where the backlog is ageing --------------------------------------

    left, right = st.columns(2)

    with left:
        st.markdown("#### Stock par palier")
        st.caption("Ce qui n'est affecté à personne, du plus en retard au plus large.")
        tiers = by_tier(session, unassigned)
        order = sorted(tiers)
        fig3 = go.Figure(
            go.Bar(
                x=[tier_label(t) for t in order],
                y=[len(tiers[t]) for t in order],
                marker_color=[tier_colour(t) for t in order],
                text=[len(tiers[t]) for t in order],
                textposition="outside",
            )
        )
        fig3.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="actes")
        st.plotly_chart(fig3, use_container_width=True)

    with right:
        st.markdown("#### Où est le retard")
        st.caption("Répartition par activité des dossiers déjà hors délai.")
        late_by_type: dict[str, int] = {}
        for item in overdue:
            late_by_type[item.type_code] = late_by_type.get(item.type_code, 0) + 1
        if late_by_type:
            fig4 = go.Figure(
                go.Pie(
                    labels=[ACT_TYPES[c].label for c in late_by_type],
                    values=list(late_by_type.values()),
                    hole=0.45,
                    textinfo="value",
                )
            )
            fig4.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", y=-0.15, font=dict(size=10)),
            )
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.success("Aucun dossier hors délai dans le stock.")

    # ---- Urgencies --------------------------------------------------------

    st.markdown("#### Exposition aux urgences")
    st.caption(
        "Qui absorbe les urgences poussées. Une concentration durable sur les "
        "mêmes personnes est ce que la rotation des gestionnaires de confiance "
        "doit corriger."
    )
    urgent_done = [sum(1 for i in s.done if i.pushed) for s in states]
    urgent_queue = [sum(1 for i in s.queue if i.pushed) for s in states]
    offered = [len(session.offers.get(s.worker.id, [])) for s in states]
    trust = ["confiance" if s.worker.trusted else "" for s in states]

    if sum(urgent_done) + sum(urgent_queue) + sum(offered) == 0:
        st.info("Aucune urgence poussée pour l'instant.")
    else:
        fig5 = go.Figure()
        fig5.add_bar(name="Traitées", x=names, y=urgent_done, marker_color="#4a3aa7")
        fig5.add_bar(name="En lot", x=names, y=urgent_queue, marker_color="#9a93c9")
        fig5.add_bar(name="Proposées", x=names, y=offered, marker_color="#d6d3e8")
        fig5.update_layout(
            barmode="stack",
            height=300,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", y=1.12, x=0),
            yaxis_title="urgences",
        )
        st.plotly_chart(fig5, use_container_width=True)
        st.caption("Gestionnaires de confiance : " + ", ".join(
            n for n, t in zip(names, trust, strict=True) if t
        ))

    # ---- Yield by activity ------------------------------------------------

    st.markdown("#### Rendement par activité")
    st.caption(
        "Points par heure de chaque activité, au niveau intermédiaire. "
        "La ligne marque les 14,3 pts/h nécessaires pour tenir la cible : "
        "sous cette ligne, une journée entière de cette activité ne suffit pas."
    )
    def yield_of(code: str) -> float:
        return ACT_TYPES[code].points * 60 / effective_minutes(ACT_TYPES[code], 2)

    codes = sorted(ACT_TYPES, key=lambda c: -yield_of(c))
    yields = [yield_of(c) for c in codes]

    fig6 = go.Figure()
    fig6.add_bar(
        x=[ACT_TYPES[c].label for c in codes],
        y=yields,
        marker_color=["#1baf7a" if y >= 14.29 else "#e8a317" for y in yields],
        text=[f"{y:.1f}" for y in yields],
        textposition="outside",
        name="pts/h",
    )
    fig6.add_hline(y=14.29, line_dash="dash", line_color="#c93b38")
    fig6.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis_title="points par heure",
        showlegend=False,
    )
    st.plotly_chart(fig6, use_container_width=True)

    # ---- Held cases -------------------------------------------------------

    if session.held:
        st.markdown("#### Dossiers en attente")
        st.caption(
            "Par motif. Une hausse durable des pièces manquantes est un problème "
            "de complétude en entrée, pas de répartition."
        )
        reasons = session.held_by_reason
        fig7 = go.Figure(
            go.Bar(
                x=[len(v) for v in reasons.values()],
                y=[HOLD_LABELS[k] for k in reasons],
                orientation="h",
                marker_color="#8c9aa4",
                text=[len(v) for v in reasons.values()],
                textposition="outside",
            )
        )
        fig7.update_layout(
            height=max(200, 44 * len(reasons)),
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="dossiers",
        )
        st.plotly_chart(fig7, use_container_width=True)

    # ---- Volume table -----------------------------------------------------

    st.markdown("#### Stock par activité")
    rows = []
    for code, act in ACT_TYPES.items():
        in_stock = [i for i in unassigned if i.type_code == code]
        late = sum(1 for i in in_stock if slack(TODAY, i.due_on) < 0)
        rows.append(
            {
                "Activité": act.label,
                "En stock": len(in_stock),
                "Hors délai": late,
                "Butoir": f"{act.sla_days} j",
                "Points": act.points,
                "Durée": f"{effective_minutes(act, 2):.0f} min",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_tomorrow(session: DaySession) -> None:
    st.caption(
        "Aucun planning n'est construit à l'avance : demain, chacun recevra ses "
        "lots au fil de l'eau. Ne se règlent ici que les temps alloués."
    )
    tomorrow = st.session_state.setdefault(
        "tomorrow", {i: REFERENCE_DAY_MINUTES for i in session.workers}
    )
    count, minutes = tomorrow_forecast(session)
    capacity = sum(tomorrow.values())
    cover = min(100, int(capacity / minutes * 100)) if minutes else 100

    m = st.columns(3)
    m[0].metric("Temps alloué", hm(capacity))
    m[1].metric("À traiter d'ici demain", count)
    m[2].metric("Couverture", f"{cover} %")

    if cover < 100:
        st.warning(f"Il manque {hm(minutes - capacity)} pour tenir les délais.")
    else:
        st.success("Le reste de la capacité ira au stock à marge confortable.")

    left, right = st.columns(2)
    for n, (worker_id, state) in enumerate(session.workers.items()):
        with left if n % 2 == 0 else right:
            cols = st.columns([3, 2, 2])
            cols[0].write(state.worker.display_name)
            tomorrow[worker_id] = cols[1].selectbox(
                "Temps",
                ALLOCATIONS,
                index=ALLOCATIONS.index(tomorrow[worker_id]),
                format_func=hm,
                key=f"tom-{worker_id}",
                label_visibility="collapsed",
            )
            cols[2].markdown(
                f"<span class='muted'>cible "
                f"{target_points(tomorrow[worker_id]):.0f} pts</span>",
                unsafe_allow_html=True,
            )


def main() -> None:
    st.set_page_config(page_title="Dispatch", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    session = bootstrap()

    st.sidebar.markdown("### Dispatch")
    role = st.sidebar.radio("Vue", ["Gestionnaire", "Manager"], label_visibility="collapsed")
    st.sidebar.caption(f"Stock non affecté : {len(session.backlog)}")
    if st.sidebar.button("Réinitialiser la journée"):
        st.cache_resource.clear()
        st.rerun()

    if role == "Gestionnaire":
        names = {c.id: c.display_name for c in CASEWORKERS}
        worker_id = st.sidebar.selectbox(
            "Gestionnaire", list(names), format_func=lambda i: names[i]
        )
        render_worker(session, worker_id)
    else:
        tabs = st.tabs(["Aujourd'hui", "Corbeilles", "Performance", "Demain"])
        with tabs[0]:
            render_today(session)
        with tabs[1]:
            render_bins(session)
        with tabs[2]:
            render_performance(session)
        with tabs[3]:
            render_tomorrow(session)


if __name__ == "__main__":
    main()