"""Streamlit prototype. Throwaway UI on top of the real engine.

Only here to test flows and rules with actual users — not a production front.
Colours and type follow the mutuelle's 2018 brand guidelines.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from dispatch.app.session import (
    ASSUMED_LUNCH_MINUTES,
    DAY_END_MINUTES,
    DAY_START_MINUTES,
    DaySession,
    WorkerState,
)
from dispatch.domain.models import REFERENCE_DAY_MINUTES, HoldReason, WorkItem
from dispatch.domain.rules import effective_minutes, slack, target_points
from dispatch.sim.fixtures import ACT_TYPES, CASEWORKERS, DAILY_ARRIVALS, make_backlog

TODAY = date(2026, 8, 25)
URGENT = -999
ALLOCATIONS = [420, 336, 252, 210, 126, 0]
OVERTIME = [0, 30, 60, 90, 120]
LOGO = Path(__file__).parent / "assets" / "LOGO_MGC_2018.png"

BRAND = "#C30048"
INK = "#4D4F53"
STONE = "#B7B1A9"
TIER_INDIGO = "#3C3D8A"

# Slack in business days. Negative means late, so the display flips the sign:
# slack -3 shows as J+3. Red for arrears, orange on the due date, green for
# remaining margin — the deeper the colour, the closer the deadline.
TIER_SCALE: dict[int, str] = {
    -5: "#8f0016",
    -4: "#b30020",
    -3: "#d6002a",
    -2: "#e8322f",
    -1: "#f26152",
    0: "#e8951a",
    1: "#1f7a4d",
    2: "#3f9c68",
    3: "#6bb98a",
    4: "#9dd2b1",
    5: "#c9e6d5",
}

HOLD_LABELS = {
    HoldReason.MISSING_DOCUMENT: "Pièce manquante",
    HoldReason.MEMBER_FOLLOW_UP: "Relance adhérent",
    HoldReason.MEDICAL_OPINION: "Avis médical",
    HoldReason.THIRD_PARTY: "Attente d'un tiers",
}

CSS = f"""
<style>
  html, body, [class*="css"] {{font-family: Arial, Helvetica, sans-serif;}}
  .block-container {{padding-top: 2rem; padding-bottom: 3rem; max-width: 1480px;}}

  h1, h2, h3, h4 {{color: {INK}; letter-spacing: -.01em;}}
  h4 {{margin-top: 1.6rem; margin-bottom: .2rem; font-size: 1.02rem;}}
  h5 {{color: {INK}; font-size: .95rem; margin: 0 0 .3rem;}}

  div[data-testid="stMetricValue"] {{font-size: 1.45rem; color: {INK};}}
  div[data-testid="stMetricLabel"] {{font-size: .76rem; text-transform: uppercase;
    letter-spacing: .04em; color: {STONE};}}

  .stButton button {{padding: .2rem .7rem; font-size: .8rem; min-height: 0;
    border-radius: 4px;}}

  .stTabs [data-baseweb="tab-list"] {{gap: 1.4rem; border-bottom: 1px solid #e6e3de;}}
  .stTabs [data-baseweb="tab"] {{padding: .4rem 0; font-size: .92rem;}}
  .stTabs [aria-selected="true"] {{color: {BRAND};}}

  .chip {{display:inline-flex; align-items:center; gap:5px; padding:2px 9px;
    border-radius:11px; font-size:.72rem; background:#f2f0ec; color:{INK};}}
  .dot {{width:9px; height:9px; border-radius:2px; display:inline-block;}}
  .muted {{color:{STONE}; font-size:.75rem;}}
  .lead {{font-size:1.02rem; line-height:1.6; color:{INK};}}

  .card {{border:1px solid #e6e3de; border-left:3px solid {BRAND};
    border-radius:6px; padding:.85rem 1.1rem; margin-bottom:.7rem;
    background:#fdfcfb;}}
  .card h5 {{margin:0 0 .3rem; font-size:.92rem; color:{INK};}}
  .card p {{margin:0; font-size:.82rem; color:#6f6d68; line-height:1.5;}}

  .rule {{border:0; border-top:1px solid #e6e3de; margin:1.4rem 0 .8rem;}}

  .cellrow {{display:flex; flex-wrap:wrap; gap:4px; margin:4px 0 8px;}}
  .cell {{display:inline-flex; flex-direction:column; align-items:center;
    justify-content:center; min-width:52px; height:44px; border-radius:5px;
    padding:0 6px; line-height:1.25;}}
  .cell b {{font-size:11px; font-weight:700;}}
  .cell span {{font-size:9px; opacity:.9;}}
</style>
"""

HELP = {
    "lot": (
        "Le lot",
        "Chacun reçoit une petite quantité de travail, réapprovisionnée à mesure "
        "qu'elle s'épuise. Rien n'est planifié pour la journée entière : un dossier "
        "arrivé il y a une heure entre dans le prochain lot. L'encours se rétracte "
        "en fin de journée pour que rien ne reparte au stock le soir.",
    ),
    "tiers": (
        "Les délais",
        "Chaque dossier porte sa date butoir. J+3 veut dire trois jours de retard, "
        "J-3 trois jours de marge. Votre lot est constitué du travail le plus urgent "
        "disponible, et la liste reste triée dans cet ordre quel que soit le tri "
        "choisi. La durée de traitement n'entre jamais dans la priorité.",
    ),
    "hold": (
        "La mise en attente",
        "Un dossier qu'on ne peut pas traiter — pièce manquante, relance en cours — "
        "sort du flux avec son motif. Le temps libéré est aussitôt comblé par un "
        "autre dossier. Le délai contractuel continue de courir : au réveil, le "
        "dossier revient en priorité, chez celui qui l'avait suspendu.",
    ),
    "urgency": (
        "Les urgences",
        "Le manager fait remonter un dossier du stock. Nommée, l'urgence est "
        "proposée : le gestionnaire accepte ou refuse, sans avoir à se justifier. "
        "Sans destinataire, elle va en corbeille et le premier habilité qui se "
        "réapprovisionne la prend.",
    ),
    "allocation": (
        "Le temps alloué",
        "Ce que chacun consacre à ce périmètre aujourd'hui, de 0 à 7 heures. "
        "Zéro ne veut pas dire absent : la personne travaille ailleurs. La cible "
        "de points suit ce temps — 100 points pour 7 heures, 50 pour une "
        "demi-journée.",
    ),
    "overtime": (
        "Heures supplémentaires et amplitude",
        "L'amplitude va de 8 h 30 à 20 h. Une journée pleine fait 7 heures, à "
        "laquelle s'ajoute au moins une heure de pause — jamais enregistrée, "
        "seulement supposée pour projeter l'heure de fin. Les heures "
        "supplémentaires sont décidées par le manager et augmentent la cible de "
        "points d'autant.",
    ),
    "points": (
        "Les points",
        "Le barème de productivité attribue des points à chaque acte. La cible "
        "est de 100 points par journée de 7 heures, proratisée au temps alloué. "
        "Le taux affiché ne porte que sur ce périmètre — hors qualité, hors prime "
        "collective, hors activité ailleurs.",
    ),
}


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------


def tier_label(days: int) -> str:
    """Display convention: J+n means n days late, J-n means n days left.

    The engine reasons in slack — days remaining before the due date — so the
    sign is flipped here and here only.
    """
    if days <= URGENT:
        return "urgence"
    if days < 0:
        return f"J+{-days}"
    return "J" if days == 0 else f"J-{days}"


def tier_full(days: int) -> str:
    if days <= URGENT:
        return "Urgence poussée"
    if days < 0:
        return f"retard de {-days} jour" + ("s" if days < -1 else "")
    if days == 0:
        return "échoit aujourd'hui"
    return f"{days} jour" + ("s" if days > 1 else "") + " avant butoir"


def tier_colour(days: int) -> str:
    if days <= URGENT:
        return TIER_INDIGO
    return TIER_SCALE[max(-5, min(5, days))]


def tier_text(days: int) -> str:
    """White on the dark end of each family, ink on the light end."""
    if days <= URGENT or days <= -2 or days in (1, 2):
        return "#ffffff"
    return "#1D1D1D"


def hm(minutes: float) -> str:
    if minutes <= 0:
        return "0 h"
    return f"{int(minutes // 60)} h {int(minutes % 60):02d}"


def clock_label(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def days_of(item: WorkItem) -> int:
    return URGENT if item.pushed else slack(TODAY, item.due_on)


def by_tier(items: list[WorkItem]) -> dict[int, list[WorkItem]]:
    out: dict[int, list[WorkItem]] = {}
    for item in items:
        out.setdefault(days_of(item), []).append(item)
    return out


def tier_legend(compact: bool = False) -> None:
    """The whole scale at a glance, from oldest arrears to widest margin."""
    chips = []
    for days in range(-5, 6):
        label = tier_label(days)
        if days == -5:
            label = "J+5 et +"
        elif days == 5:
            label = "J-5 et +"
        chips.append(
            f"<span title='{tier_full(days)}' style='display:inline-flex;"
            f"align-items:center;justify-content:center;min-width:44px;padding:3px 7px;"
            f"border-radius:4px;background:{tier_colour(days)};color:{tier_text(days)};"
            f"font-size:.7rem;font-weight:600'>{label}</span>"
        )
    chips.append(
        f"<span title='Urgence poussée' style='display:inline-flex;align-items:center;"
        f"justify-content:center;min-width:44px;padding:3px 7px;border-radius:4px;"
        f"background:{TIER_INDIGO};color:#fff;font-size:.7rem;font-weight:600'>"
        "urgence</span>"
    )
    caption = (
        ""
        if compact
        else "<div class='muted' style='margin-top:4px'>Rouge : retard, du plus "
        "ancien au plus récent · Orange : échoit aujourd'hui · Vert : marge "
        "restante, du plus serré au plus large</div>"
    )
    st.markdown(
        f"<div style='display:flex;gap:3px;flex-wrap:wrap'>{''.join(chips)}</div>"
        f"{caption}",
        unsafe_allow_html=True,
    )


def help_note(key: str) -> None:
    title, body = HELP[key]
    with st.popover("Comment ça marche"):
        st.markdown(f"**{title}**")
        st.caption(body)


@st.cache_resource
def bootstrap() -> DaySession:
    backlog = make_backlog(TODAY)
    workers = {c.id: WorkerState(worker=c) for c in CASEWORKERS}
    session = DaySession(today=TODAY, types=ACT_TYPES, backlog=backlog, workers=workers)
    for worker_id in workers:
        session.refill(worker_id)
    return session


# --------------------------------------------------------------------------
# Visual building blocks
# --------------------------------------------------------------------------


def cell(
    item: WorkItem,
    session: DaySession,
    level: int = 2,
    done: bool = False,
    on_date: date | None = None,
) -> str:
    """One square per case: tier, act code, and its weight in points.

    A completed case is drawn hollow rather than filled: opacity alone reads
    poorly on a light background, so the fill itself carries the state.
    """
    days = URGENT if item.pushed else slack(on_date or TODAY, item.due_on)
    act = ACT_TYPES[item.type_code]
    colour = tier_colour(days)
    minutes = session.minutes_of(item, level)
    mark = "↑" if item.pushed else ""
    status = "traité" if done else "à traiter"
    tip = (
        f"{item.reference} — {act.label} · {tier_full(days)} · "
        f"{act.points} points · {minutes:.0f} min · {status}"
    )

    if done:
        style = (
            f"background:transparent;border:1.5px solid {colour};"
            f"color:{colour};opacity:.55"
        )
        top = f"✓ {tier_label(days)}"
    else:
        style = f"background:{colour};color:{tier_text(days)}"
        top = f"{mark}{tier_label(days)}"

    return (
        f"<span class='cell' title='{tip}' style='{style}'>"
        f"<span>{top}</span>"
        f"<b>{item.type_code}</b>"
        f"<span>{act.points:g} pts</span></span>"
    )


def cell_row(
    items: list[WorkItem],
    session: DaySession,
    level: int = 2,
    done: bool = False,
    on_date: date | None = None,
) -> str:
    ref = on_date or TODAY
    ordered = sorted(
        items,
        key=lambda i: (not i.pushed, slack(ref, i.due_on), i.type_code),
    )
    cells = "".join(cell(i, session, level, done, on_date) for i in ordered)
    return f"<div class='cellrow'>{cells}</div>"


def day_bar(session: DaySession, state: WorkerState, height: int = 14) -> str:
    """One segment per case: width is its handling time, colour its deadline.

    Reading the bar tells the whole day at a glance — how much is done, what is
    still in hand, and how urgent each piece of it is.
    """
    if not state.on_perimeter:
        return (
            f"<div style='height:{height}px;display:flex;align-items:center;"
            f"padding-left:9px;font-size:11px;color:{STONE}'>hors périmètre</div>"
        )

    level = state.worker.level
    pairs = [(i, True) for i in state.done] + [(i, False) for i in state.queue]
    pairs.sort(key=lambda p: (not p[1], not p[0].pushed, days_of(p[0]), p[0].type_code))

    blocks = []
    for item, done in pairs:
        days = days_of(item)
        act = ACT_TYPES[item.type_code]
        minutes = session.minutes_of(item, level)
        tip = (
            f"{item.reference} — {act.label} · {tier_full(days)} · "
            f"{act.points} points · {minutes:.0f} min · "
            f"{'traité' if done else 'à traiter'}"
        )
        shade = (
            "<span style='position:absolute;inset:0;"
            "background:repeating-linear-gradient(45deg,rgba(255,255,255,.75) 0 3px,"
            "rgba(255,255,255,.25) 3px 6px)'></span>"
            if done
            else ""
        )
        blocks.append(
            f"<div title='{tip}' style='flex:{minutes:.1f} 0 0;min-width:5px;"
            f"position:relative;background:{tier_colour(days)};"
            f"border-right:1px solid rgba(255,255,255,.85)'>{shade}</div>"
        )
    used = state.minutes_worked + session.queue_minutes(state)
    free = max(0.0, state.working_minutes - used)
    if free > 2:
        blocks.append(
            f"<div title='{hm(free)} non encore distribué' "
            f"style='flex:{free:.0f} 0 0;min-width:14px;"
            "border:1.5px dashed rgba(128,128,128,.4);border-radius:3px'></div>"
        )

    pct = state.working_minutes / REFERENCE_DAY_MINUTES * 100
    return (
        f"<div style='display:flex'><div style='width:{min(100, pct):.0f}%;display:flex;"
        f"height:{height}px;background:#f2f0ec;border-radius:3px;"
        f"overflow:hidden'>{''.join(blocks)}</div></div>"
    )


def lot_summary(session: DaySession, state: WorkerState) -> str:
    """A single line: what has been given, done, pushed and put on hold."""
    given = len(state.done) + len(state.queue)
    pushed = sum(1 for i in state.done + state.queue if i.pushed)
    return (
        f"<span class='muted'>{given} acte(s) reçus depuis ce matin · "
        f"{len(state.done)} traité(s) · {len(state.queue)} en lot · "
        f"{state.lots_served} lot(s) servis · {pushed} urgence(s) poussée(s) · "
        f"{hm(state.minutes_worked)} travaillées</span>"
    )


# --------------------------------------------------------------------------
# Caseworker view
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# Manager view
# --------------------------------------------------------------------------


def render_lot_detail(session: DaySession, state: WorkerState) -> None:
    """Read-only for the manager: what this caseworker holds, right now."""
    level = state.worker.level
    st.markdown(f"**{state.worker.display_name}**")
    st.markdown(lot_summary(session, state), unsafe_allow_html=True)

    offers = session.offers.get(state.worker.id, [])
    if offers:
        st.markdown("---")
        st.markdown(f"**Proposées, sans réponse — {len(offers)}**")
        for item in offers:
            st.markdown(
                f"<span class='muted'>{item.reference} · "
                f"{ACT_TYPES[item.type_code].label}</span>",
                unsafe_allow_html=True,
            )

    st.markdown("---")
    if not state.queue:
        st.write("Lot vide.")
    else:
        st.markdown(f"**Lot en cours — {len(state.queue)}**")
        st.markdown(cell_row(state.queue, session, level), unsafe_allow_html=True)
        for days, items in sorted(by_tier(state.queue).items()):
            groups: dict[str, list[WorkItem]] = {}
            for item in items:
                groups.setdefault(item.type_code, []).append(item)
            st.markdown(
                f"<span class='dot' style='background:{tier_colour(days)}'></span> "
                f"<b>{tier_label(days)}</b> — {tier_full(days)} · {len(items)} acte(s)",
                unsafe_allow_html=True,
            )
            for code, group in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                refs = ", ".join(i.reference for i in group[:5])
                more = f" et {len(group) - 5} autre(s)" if len(group) > 5 else ""
                st.markdown(
                    f"<span class='muted'>{len(group)} × {ACT_TYPES[code].label} — "
                    f"{refs}{more}</span>",
                    unsafe_allow_html=True,
                )

    if state.done:
        st.markdown("---")
        st.markdown(f"**Traités — {len(state.done)}**")
        st.markdown(
            cell_row(state.done, session, level, done=True), unsafe_allow_html=True
        )


def render_today(session: DaySession) -> None:
    states = list(session.workers.values())
    given = sum(len(s.done) + len(s.queue) for s in states)

    m = st.columns(6)
    m[0].metric("Heure", session._clock_label())
    m[1].metric("Alloué", hm(sum(s.working_minutes for s in states)))
    m[2].metric("Distribués", given)
    m[3].metric("Traités", sum(len(s.done) for s in states))
    m[4].metric("Corbeille", len(session.urgency_bin))
    m[5].metric("En attente", len(session.held))

    tools = st.columns([1, 1, 1, 1, 4])
    with tools[0]:
        help_note("urgency")
    with tools[1]:
        help_note("allocation")
    with tools[2]:
        help_note("overtime")
    with tools[3]:
        help_note("points")

    bar = st.columns([1, 1, 6])
    if bar[0].button("+15 min", use_container_width=True):
        session.advance(15)
        st.rerun()
    if bar[1].button("+1 h", use_container_width=True):
        session.advance(60)
        st.rerun()

    # ---- Pushing urgencies -------------------------------------------------

    with st.container(border=True):
        st.markdown("##### Pousser une ou plusieurs urgences")
        st.caption(
            "Saisissez tout ou partie d'un numéro SUDE, ou plusieurs séparés par "
            "une virgule. Nommées, les urgences sont proposées au gestionnaire, "
            "qui peut refuser ; sans destinataire, elles partent en corbeille."
        )

        search = st.text_input(
            "Numéros SUDE",
            placeholder="SUDE-26-40417, 40592, 41003 — ou un fragment commun",
            label_visibility="collapsed",
            key="sude-search",
        )

        pool = session.pushable(limit=4000)
        chosen: list[WorkItem] = []
        terms = [t.strip().upper() for t in search.split(",") if t.strip()]
        terms = [t for t in terms if len(t) >= 3]

        if not terms:
            st.markdown(
                f"<span class='muted'>{len(pool)} dossier(s) poussables dans le "
                "stock. Tapez au moins trois caractères.</span>",
                unsafe_allow_html=True,
            )
        else:
            hits = [i for i in pool if any(t in i.reference.upper() for t in terms)]
            hits.sort(key=lambda i: i.due_on)
            if not hits:
                st.warning("Aucun dossier du stock ne correspond à cette saisie.")
            else:
                extra = " — 12 affichées" if len(hits) > 12 else ""
                st.markdown(
                    f"<span class='muted'>{len(hits)} correspondance(s), les plus "
                    f"urgentes d'abord{extra}.</span>",
                    unsafe_allow_html=True,
                )
                for item in hits[:12]:
                    act = ACT_TYPES[item.type_code]
                    days = slack(TODAY, item.due_on)
                    cols = st.columns([0.5, 1.1, 1.8, 4.6])
                    ticked = cols[0].checkbox(
                        "Sélectionner",
                        key=f"pick-{item.id}",
                        label_visibility="collapsed",
                    )
                    if ticked:
                        chosen.append(item)
                    cols[1].markdown(
                        f"<div style='padding-top:.2rem'>{cell(item, session)}</div>",
                        unsafe_allow_html=True,
                    )
                    cols[2].markdown(
                        f"<div style='padding-top:.6rem;font-size:.82rem'>"
                        f"{item.reference}</div>",
                        unsafe_allow_html=True,
                    )
                    cols[3].markdown(
                        f"<div style='padding-top:.6rem'><span class='muted'>"
                        f"{act.label} · {act.points} pts · {tier_full(days)} · "
                        f"niveaux {', '.join(str(n) for n in act.levels)}"
                        "</span></div>",
                        unsafe_allow_html=True,
                    )

        if chosen:
            st.markdown("---")
            types = {i.type_code for i in chosen}
            action = st.columns([4, 1.5, 1.5])
            action[0].markdown(
                f"**{len(chosen)} dossier(s) sélectionné(s)** — "
                f"{', '.join(ACT_TYPES[t].label for t in sorted(types))}"
            )
            if action[1].button("Attribuer", use_container_width=True):
                st.session_state["pending"] = [i.id for i in chosen]
                st.rerun()
            if action[2].button("En corbeille", use_container_width=True):
                for item in chosen:
                    session.push_urgency(item.id)
                st.toast(f"{len(chosen)} urgence(s) déposée(s) en corbeille")
                st.rerun()

        pending_ids = st.session_state.get("pending") or []
        pending = [i for i in session.backlog if i.id in pending_ids]
        if pending_ids and not pending:
            st.session_state["pending"] = None
        elif pending:
            st.markdown("---")
            labels = ", ".join(i.reference for i in pending[:4])
            more = f" et {len(pending) - 4} autre(s)" if len(pending) > 4 else ""
            needed = {i.type_code for i in pending}
            st.markdown(
                f"**{labels}{more}** — à qui les attribuer ?<br>"
                "<span class='muted'>Les gestionnaires de confiance sont suggérés "
                "en premier, mais le choix reste libre parmi les habilités.</span>",
                unsafe_allow_html=True,
            )

            # Clearance is a business rule and cannot be overridden. Trust is
            # only a suggestion: the manager may pick anyone cleared, junior
            # included, for instance because they already know the member.
            eligible = [
                s
                for s in session.workers.values()
                if s.on_perimeter
                and all(s.worker.level in ACT_TYPES[t].levels for t in needed)
            ]
            eligible.sort(key=lambda s: (not s.worker.trusted, session.queue_minutes(s)))

            def offer_to(state: WorkerState, key: str) -> None:
                cols = st.columns([3, 2.4, 1])
                tag = " · confiance" if state.worker.trusted else ""
                cols[0].write(f"{state.worker.display_name}{tag}")
                cols[1].markdown(
                    f"<span class='muted'>niv. {state.worker.level} · "
                    f"{len(state.queue)} acte(s) · "
                    f"{hm(session.queue_minutes(state))} en lot</span>",
                    unsafe_allow_html=True,
                )
                if cols[2].button("Choisir", key=key):
                    for item in pending:
                        session.push_urgency(item.id, state.worker.id)
                    st.session_state["pending"] = None
                    st.toast(
                        f"{len(pending)} urgence(s) proposée(s) à "
                        f"{state.worker.display_name}"
                    )
                    st.rerun()

            if not eligible:
                st.warning(
                    "Aucun gestionnaire habilité pour tous ces types n'est sur le "
                    "périmètre. Poussez-les séparément, ou en corbeille."
                )
            else:
                for state in eligible[:3]:
                    offer_to(state, f"give-{state.worker.id}")
                others = eligible[3:]
                if others:
                    with st.expander(
                        f"Choisir quelqu'un d'autre — {len(others)} habilité(s)"
                    ):
                        st.caption(
                            "Tous les gestionnaires habilités pour ces types, "
                            "quel que soit leur niveau."
                        )
                        for state in others:
                            offer_to(state, f"alt-{state.worker.id}")

            if st.button("Annuler"):
                st.session_state["pending"] = None
                st.rerun()

    # ---- Team load ---------------------------------------------------------

    waiting = sum(len(v) for v in session.offers.values())
    if waiting:
        who = ", ".join(
            session.workers[w].worker.display_name
            for w, v in session.offers.items()
            if v
        )
        st.caption(f"**{waiting} urgence(s) proposée(s)**, en attente de réponse — {who}")

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    tier_legend()
    st.markdown(
        "<div class='muted' style='margin-top:.6rem'>Gestionnaire · temps alloué · "
        "heures sup · traités sur reçus · points et fin au plus tôt</div>",
        unsafe_allow_html=True,
    )

    for worker_id, state in session.workers.items():
        head = st.columns([1.8, 1.1, 1, 1.3, 1.5, 1])
        tag = "confiance" if state.worker.trusted else f"niv. {state.worker.level}"
        head[0].markdown(
            f"<b style='font-size:.88rem'>{state.worker.display_name}</b><br>"
            f"<span class='muted'>{tag} · {len(state.queue)} en lot</span>",
            unsafe_allow_html=True,
        )
        choice = head[1].selectbox(
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
        extra_time = head[2].selectbox(
            "Heures sup",
            OVERTIME,
            index=OVERTIME.index(state.overtime_minutes)
            if state.overtime_minutes in OVERTIME
            else 0,
            format_func=lambda m: "—" if m == 0 else f"+{m} min",
            key=f"ot-{worker_id}",
            label_visibility="collapsed",
            disabled=not state.on_perimeter,
        )
        if extra_time != state.overtime_minutes:
            session.set_overtime(worker_id, extra_time)
            st.rerun()

        received = len(state.done) + len(state.queue)
        pushed = sum(1 for i in state.done + state.queue if i.pushed)
        head[3].markdown(
            f"<span style='font-size:.82rem'>{len(state.done)}/{received}</span><br>"
            f"<span class='muted'>{pushed} urgence(s)</span>",
            unsafe_allow_html=True,
        )
        points, target = session.points_earned(state), session.target(state)
        rate = int(points / target * 100) if target else 0
        end = state.earliest_end
        over = end > DAY_END_MINUTES
        note = f"fin ≥ {clock_label(min(end, 1439))}" if state.on_perimeter else "—"
        head[4].markdown(
            f"<span style='font-size:.82rem'>{points:.0f}/{target:.0f} · "
            f"{rate if state.minutes_worked else '—'} %</span><br>"
            f"<span class='muted' style='color:{BRAND if over else STONE}'>"
            f"{note}</span>",
            unsafe_allow_html=True,
        )
        with head[5].popover("Détail"):
            render_lot_detail(session, state)

        if not state.on_perimeter:
            st.markdown(
                "<div class='muted' style='margin:.2rem 0 1rem'>hors périmètre "
                "aujourd'hui</div>",
                unsafe_allow_html=True,
            )
            continue

        st.markdown(day_bar(session, state), unsafe_allow_html=True)
        cells = ""
        if state.done:
            cells += cell_row(state.done, session, state.worker.level, done=True)
        if state.queue:
            cells += cell_row(state.queue, session, state.worker.level)
        st.markdown(cells or "<div class='muted'>lot vide</div>", unsafe_allow_html=True)
        st.markdown(
            "<hr class='rule' style='margin:.4rem 0 1rem'/>", unsafe_allow_html=True
        )


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
        else:
            st.markdown(cell_row(session.urgency_bin, session), unsafe_allow_html=True)
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

    Two questions: what has been distributed and done, by activity, and where
    the unassigned backlog is ageing.
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
    m[2].metric("En retard en stock", len(overdue))
    m[3].metric("Échoit aujourd'hui", len(due_today))
    spread = 0
    if len(active) > 1:
        rates = [
            session.points_earned(s) / session.target(s)
            for s in active
            if session.target(s)
        ]
        spread = int((max(rates) - min(rates)) * 100) if rates else 0
    m[4].metric("Écart de rendement", f"{spread} pts")

    if overdue:
        st.warning(
            f"{len(overdue)} dossier(s) en retard encore non affectés. "
            "Ils passeront en tête du prochain lot d'un habilité."
        )

    # ---- Distributed and completed, by activity ---------------------------

    st.markdown("#### Distribué et accompli, par activité")
    st.caption(
        "Deux barres par gestionnaire : à gauche ce qui a été distribué, à "
        "droite ce qui a été accompli. Chaque couleur est une activité — "
        "l'écart entre les deux barres est ce qui repartirait au stock ce soir."
    )

    codes = sorted(
        {i.type_code for s in states for i in s.done + s.queue},
        key=lambda c: -sum(
            1 for s in states for i in s.done + s.queue if i.type_code == c
        ),
    )
    palette = [
        "#C30048",
        "#3C3D8A",
        "#1f7a4d",
        "#e8951a",
        "#1D71B8",
        "#8f0016",
        "#6bb98a",
        "#8385bd",
        "#b3b0a8",
        "#4D4F53",
    ]
    tint = dict(zip(codes, palette, strict=False))

    if not codes:
        st.info("Rien de distribué pour l'instant.")
    else:
        # Plotly accepts a two-level axis when given parallel lists, which is
        # what places the two bars side by side under each name.
        pairs_x: list[list[str]] = [[], []]
        for name in names:
            pairs_x[0] += [name, name]
            pairs_x[1] += ["distribué", "accompli"]

        fig = go.Figure()
        for code in codes:
            values: list[int] = []
            for state in states:
                values.append(
                    sum(1 for i in state.done + state.queue if i.type_code == code)
                )
                values.append(sum(1 for i in state.done if i.type_code == code))
            fig.add_bar(
                name=ACT_TYPES[code].label,
                x=pairs_x,
                y=values,
                marker_color=tint[code],
                hovertemplate=f"{ACT_TYPES[code].label} — %{{y}}<extra></extra>",
            )

        fig.update_layout(
            barmode="stack",
            height=440,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", y=-0.28, x=0, font=dict(size=10)),
            yaxis_title="actes",
        )
        st.plotly_chart(fig, use_container_width=True, key="perf-distributed")

    # ---- Where the backlog is ageing --------------------------------------

    left, right = st.columns(2)

    with left:
        st.markdown("#### Stock par délai")
        st.caption("Ce qui n'est affecté à personne, du plus en retard au plus large.")
        tiers = by_tier(unassigned)
        order = sorted(tiers)
        fig2 = go.Figure(
            go.Bar(
                x=[tier_label(t) for t in order],
                y=[len(tiers[t]) for t in order],
                marker_color=[tier_colour(t) for t in order],
                text=[len(tiers[t]) for t in order],
                textposition="outside",
            )
        )
        fig2.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="actes"
        )
        st.plotly_chart(fig2, use_container_width=True, key="perf-stock-tiers")

    with right:
        st.markdown("#### Où est le retard")
        st.caption("Répartition par activité des dossiers déjà en retard.")
        late_by_type: dict[str, int] = {}
        for item in overdue:
            late_by_type[item.type_code] = late_by_type.get(item.type_code, 0) + 1
        if late_by_type:
            fig3 = go.Figure(
                go.Pie(
                    labels=[ACT_TYPES[c].label for c in late_by_type],
                    values=list(late_by_type.values()),
                    hole=0.45,
                    textinfo="value",
                )
            )
            fig3.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", y=-0.15, font=dict(size=10)),
            )
            st.plotly_chart(fig3, use_container_width=True, key="perf-late-mix")
        else:
            st.success("Aucun dossier en retard dans le stock.")

    # ---- Held cases -------------------------------------------------------

    if session.held:
        st.markdown("#### Dossiers en attente")
        st.caption(
            "Par motif. Une hausse durable des pièces manquantes est un problème "
            "de complétude en entrée, pas de répartition."
        )
        reasons = session.held_by_reason
        fig4 = go.Figure(
            go.Bar(
                x=[len(v) for v in reasons.values()],
                y=[HOLD_LABELS[k] for k in reasons],
                orientation="h",
                marker_color="#8c9aa4",
                text=[len(v) for v in reasons.values()],
                textposition="outside",
            )
        )
        fig4.update_layout(
            height=max(200, 44 * len(reasons)),
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="dossiers",
        )
        st.plotly_chart(fig4, use_container_width=True, key="perf-held-reasons")

    st.markdown("#### Stock par activité")
    rows = []
    for code, act in ACT_TYPES.items():
        in_stock = [i for i in unassigned if i.type_code == code]
        late = sum(1 for i in in_stock if slack(TODAY, i.due_on) < 0)
        rows.append(
            {
                "Activité": act.label,
                "En stock": len(in_stock),
                "En retard": late,
                "Butoir": f"{act.sla_days} j",
                "Points": act.points,
                "Durée": f"{effective_minutes(act, 2):.0f} min",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_tomorrow(session: DaySession) -> None:
    """Tomorrow has no lots — they are drawn on the day. What it has is a
    backlog, a capacity set against it, and an opening lot we can forecast.

    Everything here follows from today: what is left this evening ages by one
    day, held cases keep ageing while they wait, and pushed urgencies that
    nobody took are still there in the morning.
    """
    tomorrow_date = TODAY + timedelta(days=1)
    tomorrow = st.session_state.setdefault(
        "tomorrow",
        {i: (s.allocated_minutes, 0) for i, s in session.workers.items()},
    )

    leftovers = [i for i in session.backlog if i.assigned_to is None]
    in_lots = [i for s in session.workers.values() for i in s.queue]
    pushed_left = [i for i in leftovers if i.pushed]
    offers_left = [i for v in session.offers.values() for i in v]
    inherited = leftovers + in_lots + offers_left + list(session.held)

    def tomorrow_slack(item: WorkItem) -> int:
        return slack(tomorrow_date, item.due_on)

    urgent_tomorrow = [i for i in inherited if tomorrow_slack(i) <= 0]
    arrivals = sum(DAILY_ARRIVALS.values())
    arrivals_urgent = sum(
        v for c, v in DAILY_ARRIVALS.items() if ACT_TYPES[c].sla_days <= 1
    )

    need_minutes = sum(
        effective_minutes(ACT_TYPES[i.type_code], min(ACT_TYPES[i.type_code].levels))
        for i in urgent_tomorrow
    )
    capacity = sum(a + o for a, o in tomorrow.values())
    cover = min(100, int(capacity / need_minutes * 100)) if need_minutes else 100

    m = st.columns(5)
    m[0].metric("Reporté ce soir", len(inherited))
    m[1].metric("Arrivées attendues", arrivals)
    m[2].metric("Urgent demain", len(urgent_tomorrow) + arrivals_urgent)
    m[3].metric("Capacité", hm(capacity))
    m[4].metric("Couverture", f"{cover} %")

    if cover < 100:
        st.warning(
            f"Il manque {hm(need_minutes - capacity)} pour traiter demain tout ce "
            "qui sera échu ou en retard. Ajustez les temps alloués ou les heures "
            "supplémentaires."
        )
    else:
        st.success(
            "La capacité couvre l'urgent de demain. Le reste ira au stock à "
            "marge confortable."
        )

    with st.container(border=True):
        st.markdown("##### Ce que la journée d'aujourd'hui lègue à demain")
        cols = st.columns(4)
        cols[0].markdown(
            f"**{len(in_lots)}** acte(s) encore dans les lots<br>"
            "<span class='muted'>rendus au stock ce soir</span>",
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f"**{len(pushed_left)}** urgence(s) en corbeille<br>"
            "<span class='muted'>toujours prioritaires demain</span>",
            unsafe_allow_html=True,
        )
        cols[2].markdown(
            f"**{len(offers_left)}** proposition(s) sans réponse<br>"
            "<span class='muted'>repartent en corbeille</span>",
            unsafe_allow_html=True,
        )
        cols[3].markdown(
            f"**{len(session.held)}** dossier(s) en attente<br>"
            "<span class='muted'>le délai continue de courir</span>",
            unsafe_allow_html=True,
        )
        if session.held:
            aged = [i for i in session.held if tomorrow_slack(i) < 0]
            if aged:
                st.caption(
                    f"{len(aged)} dossier(s) en attente seront en retard demain. "
                    "Ils reviendront en urgence chez celui qui les a suspendus."
                )

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    st.markdown("#### Stock projeté au matin")
    st.caption(
        "Ce qui reste ce soir, vieilli d'un jour, plus les arrivées attendues. "
        "Les dossiers en attente comptent : leur délai court même hors du flux."
    )
    tier_legend()

    projected: dict[int, int] = {}
    for item in inherited:
        key = URGENT if item.pushed else tomorrow_slack(item)
        projected[key] = projected.get(key, 0) + 1
    for code, volume in DAILY_ARRIVALS.items():
        key = ACT_TYPES[code].sla_days
        projected[key] = projected.get(key, 0) + volume

    order = sorted(projected)
    fig = go.Figure(
        go.Bar(
            x=[tier_label(t) for t in order],
            y=[projected[t] for t in order],
            marker_color=[tier_colour(t) for t in order],
            text=[projected[t] for t in order],
            textposition="outside",
        )
    )
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="actes")
    st.plotly_chart(fig, use_container_width=True, key="tomorrow-stock")

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    st.markdown("#### Temps alloué et premier lot")
    st.caption(
        "Réglez le temps de chacun : le premier lot se recalcule aussitôt. "
        "C'est une projection, pas un engagement — le tirage réel se fera "
        "demain, contre le stock du moment, arrivées de la nuit comprises."
    )

    preview = session.preview_first_lots(tomorrow, tomorrow_date)
    total_preview = sum(len(v) for v in preview.values())
    urgent_preview = sum(
        1 for v in preview.values() for i in v if slack(tomorrow_date, i.due_on) <= 0
    )
    remaining_urgent = max(0, len(urgent_tomorrow) + arrivals_urgent - urgent_preview)

    p = st.columns(3)
    p[0].metric("Actes au premier lot", total_preview)
    p[1].metric("Dont urgents", urgent_preview)
    p[2].metric("Urgent non couvert au matin", remaining_urgent)
    if remaining_urgent:
        st.caption(
            f"{remaining_urgent} dossier(s) urgents resteront au stock après le "
            "premier tour. Ils partiront aux réapprovisionnements suivants."
        )

    quick = st.columns([1.5, 1.8, 5])
    if quick[0].button("Tous à 7 h", use_container_width=True):
        for worker_id in tomorrow:
            tomorrow[worker_id] = (REFERENCE_DAY_MINUTES, 0)
        st.rerun()
    if quick[1].button("Copier aujourd'hui", use_container_width=True):
        for worker_id, state in session.workers.items():
            tomorrow[worker_id] = (state.allocated_minutes, state.overtime_minutes)
        st.rerun()

    tier_legend()
    st.markdown(
        "<div class='muted' style='margin-top:.6rem'>Gestionnaire · temps alloué · "
        "heures sup · cible · fin au plus tôt · premier lot</div>",
        unsafe_allow_html=True,
    )

    for worker_id, state in session.workers.items():
        allocated, overtime = tomorrow[worker_id]
        head = st.columns([1.8, 1.1, 1, 1.3, 1.5, 1.3])
        tag = "confiance" if state.worker.trusted else f"niv. {state.worker.level}"
        head[0].markdown(
            f"<b style='font-size:.88rem'>{state.worker.display_name}</b><br>"
            f"<span class='muted'>{tag}</span>",
            unsafe_allow_html=True,
        )
        new_allocated = head[1].selectbox(
            "Temps",
            ALLOCATIONS,
            index=ALLOCATIONS.index(allocated) if allocated in ALLOCATIONS else 0,
            format_func=hm,
            key=f"tom-alloc-{worker_id}",
            label_visibility="collapsed",
        )
        new_overtime = head[2].selectbox(
            "Heures sup",
            OVERTIME,
            index=OVERTIME.index(overtime) if overtime in OVERTIME else 0,
            format_func=lambda m: "—" if m == 0 else f"+{m} min",
            key=f"tom-ot-{worker_id}",
            label_visibility="collapsed",
            disabled=new_allocated == 0,
        )
        if (new_allocated, new_overtime) != (allocated, overtime):
            tomorrow[worker_id] = (new_allocated, new_overtime)
            st.rerun()

        working = new_allocated + new_overtime
        items = preview.get(worker_id, [])
        pts = sum(ACT_TYPES[i.type_code].points for i in items)
        urgent_here = sum(1 for i in items if slack(tomorrow_date, i.due_on) <= 0)

        head[3].markdown(
            f"<span style='font-size:.82rem'>{pts:.0f}/"
            f"{target_points(working):.0f} pts</span><br>"
            f"<span class='muted'>au premier lot</span>",
            unsafe_allow_html=True,
        )
        if working == 0:
            head[4].markdown(
                "<span class='muted'>hors périmètre</span>", unsafe_allow_html=True
            )
        else:
            end = DAY_START_MINUTES + working + ASSUMED_LUNCH_MINUTES
            over = end > DAY_END_MINUTES
            head[4].markdown(
                f"<span style='font-size:.82rem;color:{BRAND if over else INK}'>"
                f"fin ≥ {clock_label(min(end, 1439))}</span><br>"
                f"<span class='muted'>{hm(working)} de travail</span>",
                unsafe_allow_html=True,
            )
        head[5].markdown(
            f"<span style='font-size:.82rem'>{len(items)} acte(s)</span><br>"
            f"<span class='muted'>{urgent_here} urgent(s)</span>",
            unsafe_allow_html=True,
        )

        if working <= 0:
            st.markdown(
                "<div class='muted' style='margin:.2rem 0 1rem'>hors périmètre "
                "demain</div>",
                unsafe_allow_html=True,
            )
            continue

        if items:
            st.markdown(
                cell_row(items, session, state.worker.level, on_date=tomorrow_date),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='muted'>rien à servir — stock épuisé pour ses "
                "habilitations</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            "<hr class='rule' style='margin:.4rem 0 1rem'/>", unsafe_allow_html=True
        )


# --------------------------------------------------------------------------
# Home
# --------------------------------------------------------------------------


def render_home(session: DaySession) -> None:
    head = st.columns([1, 5])
    if LOGO.exists():
        head[0].image(str(LOGO), width=110)
    with head[1]:
        st.markdown("# Dispatch")
        st.markdown(
            "<p class='lead'>La répartition des actes de gestion entre "
            "gestionnaires, sous contrainte de délai contractuel, d'habilitation "
            "et de temps disponible.</p>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    st.markdown(
        "<p class='lead'>L'outil ne construit pas de planning le matin. Il sert "
        "le travail par petits lots, réapprovisionnés au fil de la journée, en "
        "respectant trois règles simples.</p>",
        unsafe_allow_html=True,
    )

    cols = st.columns(3)
    principles = [
        (
            "Le délai commande",
            "Les dossiers sont servis du plus en retard au plus confortable. "
            "La durée de traitement décide seulement de ce qui tient dans un lot, "
            "jamais de l'ordre.",
        ),
        (
            "Chacun garde la main",
            "L'ordre à l'intérieur d'un lot est libre. Une urgence se refuse sans "
            "justification. Un dossier incomplet se met en attente et se fait "
            "remplacer aussitôt.",
        ),
        (
            "La charge s'équilibre",
            "À délai égal, les actes les mieux cotés vont à qui est sous sa "
            "trajectoire de points. Personne ne décroche à cause du mix qu'on "
            "lui a donné.",
        ),
    ]
    for col, (title, body) in zip(cols, principles, strict=True):
        col.markdown(
            f"<div class='card'><h5>{title}</h5><p>{body}</p></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    st.markdown("#### Lire les délais")
    tier_legend()

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        st.markdown("#### La vue gestionnaire")
        st.markdown(
            "<p class='muted'>Son lot du moment, une case par dossier, triable "
            "par type. Il traite, met en attente, accepte ou refuse une urgence, "
            "et suit ses points au fil de la journée.</p>",
            unsafe_allow_html=True,
        )
    with right:
        st.markdown("#### La vue manager")
        st.markdown(
            "<p class='muted'>Le plan de charge de l'équipe, le temps alloué de "
            "chacun, les deux corbeilles, un tableau de bord de performance et la "
            "préparation du lendemain.</p>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    m = st.columns(4)
    m[0].metric("Gestionnaires", len(session.workers))
    m[1].metric("Stock du jour", len(session.backlog))
    m[2].metric("Activités", len(ACT_TYPES))
    m[3].metric("Journée de référence", "7 h · 100 pts")

    st.caption(
        "Prototype sur données fictives. Les cadences viennent du barème de "
        "productivité ; les durées réelles restent à mesurer."
    )


def main() -> None:
    st.set_page_config(page_title="Dispatch — mutuelle MGC", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    session = bootstrap()

    if LOGO.exists():
        st.sidebar.image(str(LOGO), width=96)
    st.sidebar.markdown("### Dispatch")
    role = st.sidebar.radio(
        "Vue", ["Accueil", "Gestionnaire", "Manager"], label_visibility="collapsed"
    )
    st.sidebar.markdown("<hr class='rule'/>", unsafe_allow_html=True)
    st.sidebar.caption(f"Heure simulée : {session._clock_label()}")
    st.sidebar.caption(f"Stock non affecté : {len(session.backlog)}")
    st.sidebar.caption(
        "Distribués : "
        f"{sum(len(s.done) + len(s.queue) for s in session.workers.values())}"
    )
    if st.sidebar.button("Réinitialiser la journée"):
        st.cache_resource.clear()
        st.rerun()

    if role == "Accueil":
        render_home(session)
    elif role == "Gestionnaire":
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