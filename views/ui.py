"""Shared presentation layer for the Streamlit prototype.

Everything here is about how the domain is shown, never about what it means.
Colours and type follow the mutuelle's 2018 brand guidelines.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from dispatch.app.session import DaySession, WorkerState
from dispatch.domain.models import REFERENCE_DAY_MINUTES, HoldReason, WorkItem
from dispatch.domain.rules import slack
from dispatch.sim.fixtures import ACT_TYPES

# Anchored on the repository root rather than on this file's own directory:
# assets/ sits next to app.py, one level above this package.
ROOT = Path(__file__).resolve().parents[1]

TODAY = date(2026, 8, 25)
URGENT = -999
ALLOCATIONS = [420, 336, 252, 210, 126, 0]
OVERTIME = [0, 30, 60, 90, 120]
LOGO = ROOT / "assets" / "LOGO_MGC_2018.png"

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