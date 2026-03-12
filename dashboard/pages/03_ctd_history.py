"""Page 03 — CTD History.

Gantt-style CTD identity timeline + implied repo spread (proximity to switch) +
CTD transition log from the SQLite database.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from dashboard.shared import (
    CONTRACT, C_BLUE, C_GREEN, C_RED, C_AMBER, C_PURPLE,
    PLOTLY_BASE, inject_css, mc, sh, banner, sidebar_inputs, get_db, page_header,
)

st.set_page_config(page_title="CTD History", page_icon="📅", layout="wide")
inject_css()
params = sidebar_inputs()
page_header("03 · CTD History", "CTD History",
            "CTD identity timeline, implied repo spread proximity, and transition log")

db = get_db()

# ── Load DB data ───────────────────────────────────────────────────────────────
try:
    db.init_schema()
    snapshots = db.get_current_basket(CONTRACT)   # latest snapshot
    transitions = db.get_ctd_transitions(CONTRACT)
    has_data = not snapshots.empty
except Exception as e:
    snapshots = pd.DataFrame()
    transitions = pd.DataFrame()
    has_data = False

if not has_data:
    banner(
        "<b>No history data.</b>  Build history by running the ingest CLI once per day:<br>"
        "<code>python -m data.ingest --contract TYM26 --futures-price 108.50 "
        "--repo-rate 0.053</code><br>"
        "Each run adds one row per bond to the <code>basis_snapshots</code> table.",
        "banner-warn",
    )
    st.stop()

# ── Pull full history for all bonds ───────────────────────────────────────────
try:
    # Get full snapshots table via db directly
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    full = pd.read_sql_query(
        "SELECT snapshot_dt, cusip, net_basis, implied_repo, is_ctd "
        "FROM basis_snapshots WHERE contract = ? ORDER BY snapshot_dt",
        conn, params=(CONTRACT,),
    )
    conn.close()
except Exception as e:
    full = pd.DataFrame()
    st.warning(f"Could not load full history: {e}")

# ── CTD identity timeline (Gantt-style) ────────────────────────────────────────
if not full.empty:
    sh("CTD identity over time")

    ctd_timeline = full[full["is_ctd"] == 1][["snapshot_dt", "cusip"]].copy()

    # Load bond labels
    from core.basket import get_basket, bond_label
    basket = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}
    ctd_timeline["label"] = ctd_timeline["cusip"].map(label_map).fillna(ctd_timeline["cusip"])

    # Assign a color per unique CTD bond
    unique_bonds = ctd_timeline["label"].unique().tolist()
    palette = [C_BLUE, C_GREEN, C_AMBER, C_PURPLE, C_RED,
               "#79c0ff", "#56d364", "#e3b341", "#d2a8ff", "#ffa198"]
    color_map = {b: palette[i % len(palette)] for i, b in enumerate(unique_bonds)}

    fig_tl = go.Figure()
    for bond in unique_bonds:
        sub = ctd_timeline[ctd_timeline["label"] == bond]
        fig_tl.add_trace(go.Scatter(
            x=sub["snapshot_dt"],
            y=[bond] * len(sub),
            mode="markers",
            name=bond,
            marker=dict(
                symbol="square",
                size=14,
                color=color_map[bond],
                line=dict(color="#0d1117", width=1),
            ),
        ))

    fig_tl.update_layout(
        **{k: v for k, v in PLOTLY_BASE.items() if k not in ("xaxis", "yaxis")},
        height=max(180, 60 + len(unique_bonds) * 60),
        xaxis=dict(**PLOTLY_BASE["xaxis"], title="Date"),
        yaxis=dict(**PLOTLY_BASE["yaxis"], title=""),
        showlegend=False,
    )
    st.plotly_chart(fig_tl, use_container_width=True)
    st.caption(
        "Each square = one daily snapshot where that bond was the CTD. "
        "Gaps indicate no snapshot was ingested on that date."
    )

# ── Implied repo spread (proximity to switch) ──────────────────────────────────
if not full.empty:
    sh("Implied repo spread · CTD vs runner-up")

    try:
        proximity = db.get_transition_proximity(CONTRACT)
    except Exception:
        proximity = pd.DataFrame()

    if not proximity.empty:
        # get_transition_proximity returns spread_to_second_bps already in bps
        fig_prox = go.Figure()
        fig_prox.add_trace(go.Scatter(
            x=proximity["snapshot_dt"],
            y=proximity["spread_to_second_bps"],
            mode="lines+markers",
            name="Spread to runner-up",
            line=dict(color=C_BLUE, width=2),
            marker=dict(size=5),
            fill="tozeroy",
            fillcolor="rgba(88,166,255,0.08)",
        ))
        fig_prox.add_hline(
            y=25, line=dict(color=C_AMBER, dash="dot", width=1),
            annotation_text="  25bps threshold",
            annotation_font=dict(color=C_AMBER, size=10),
        )
        fig_prox.add_hline(
            y=10, line=dict(color=C_RED, dash="dot", width=1),
            annotation_text="  10bps alert",
            annotation_font=dict(color=C_RED, size=10),
        )
        fig_prox.update_layout(
            **{k: v for k, v in PLOTLY_BASE.items() if k not in ("xaxis", "yaxis")},
            height=280,
            xaxis=dict(**PLOTLY_BASE["xaxis"], title="Date"),
            yaxis=dict(**PLOTLY_BASE["yaxis"], title="Spread (bps)", rangemode="tozero"),
        )
        st.plotly_chart(fig_prox, use_container_width=True)
        st.caption(
            "Spread = implied repo of CTD minus implied repo of runner-up. "
            "Below 25bps = elevated transition risk. Below 10bps = watch closely."
        )
    else:
        st.info("Proximity data requires at least 2 bonds per snapshot date.")

# ── Transition log ─────────────────────────────────────────────────────────────
sh("CTD transition log")

if not transitions.empty:
    label_map_full = {b["cusip"]: bond_label(b) for b in get_basket(use_api=False)}

    rows = ""
    for _, row in transitions.iterrows():
        prev_label = label_map_full.get(row["prev_ctd_cusip"], row["prev_ctd_cusip"] or "—")
        new_label  = label_map_full.get(row["new_ctd_cusip"],  row["new_ctd_cusip"])
        spread_str = (
            f'{row["implied_repo_spread_bps"]:.1f}bps'
            if row["implied_repo_spread_bps"] is not None
            else "—"
        )
        rows += (
            f'<tr>'
            f'<td>{row["change_dt"]}</td>'
            f'<td>{prev_label}</td>'
            f'<td style="color:#58a6ff;font-weight:600">{new_label}</td>'
            f'<td>{spread_str}</td>'
            f'</tr>'
        )

    st.markdown(
        '<table class="fi-table"><thead>'
        '<tr><th>Date</th><th>Previous CTD</th><th>New CTD</th><th>Spread at Switch</th></tr>'
        f'</thead><tbody>{rows}</tbody></table>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Spread at switch = implied repo spread between the incoming CTD and the outgoing CTD "
        "on the day of the transition. A narrow spread means the switch was close."
    )
else:
    st.info("No CTD transitions recorded yet. Transitions are logged automatically during ingest.")
