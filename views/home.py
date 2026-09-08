"""Home screen: what the tool does, and how to read it.

The three principles below are the design decisions users need to know
before they see a single case.
"""

from __future__ import annotations

import streamlit as st

from dispatch.app.session import DaySession
from dispatch.sim.fixtures import ACT_TYPES
from views.ui import LOGO, tier_legend


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