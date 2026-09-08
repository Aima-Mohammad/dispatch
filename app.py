"""Streamlit prototype. Throwaway UI on top of the real engine.

Only here to test flows and rules with actual users — not a production front.
This file holds the page setup, the session and the routing; every screen
lives in views/.
"""

from __future__ import annotations

import streamlit as st

from dispatch.app.session import DaySession, WorkerState
from dispatch.sim.fixtures import ACT_TYPES, CASEWORKERS, make_backlog
from views.home import render_home
from views.manager import render_bins, render_performance, render_today, render_tomorrow
from views.ui import CSS, LOGO, TODAY
from views.worker import render_worker


@st.cache_resource
def bootstrap() -> DaySession:
    backlog = make_backlog(TODAY)
    workers = {c.id: WorkerState(worker=c) for c in CASEWORKERS}
    session = DaySession(today=TODAY, types=ACT_TYPES, backlog=backlog, workers=workers)
    for worker_id in workers:
        session.refill(worker_id)
    return session


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