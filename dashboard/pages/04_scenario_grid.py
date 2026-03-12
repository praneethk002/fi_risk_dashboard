"""Page 04 — Scenario Grid.

Yield-shock the delivery basket across a range of parallel shifts and display:
  • Plotly heatmap  — implied repo (%) for every bond × shift combination
  • CTD annotations — which bond is CTD at each shift
  • Summary table   — shift → CTD identity, spread to runner-up, ctd_changed flag
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from dashboard.shared import (
    CONTRACT, C_BLUE, C_GREEN, C_RED, C_AMBER,
    PLOTLY_BASE, inject_css, mc, sh, banner, sidebar_inputs,
)

st.set_page_config(page_title="Scenario Grid", page_icon="🔢", layout="wide")
inject_css()
params = sidebar_inputs()

st.markdown(
    '<div style="color:#e6edf3;font-size:1.2rem;font-weight:700;padding:0.4rem 0 0.8rem;">'
    '04 · Scenario Grid</div>',
    unsafe_allow_html=True,
)

banner(
    "Parallel yield shifts applied to the delivery basket. "
    "Each cell shows implied repo (%) for that bond under the shifted yield. "
    "The <b>CTD</b> bond at each shift is annotated.",
)

# ── Build scenario grid ─────────────────────────────────────────────────────
from datetime import date
from core.basket import get_basket, bond_label
from core.scenario import scenario_grid

basket = get_basket(use_api=False)
as_of  = date.today()

# Use the flat yield from sidebar as base yield for every bond
base_yields = {b["cusip"]: params["flat_yield"] for b in basket}

SHIFTS = [-100, -75, -50, -25, 0, 25, 50, 75, 100]

try:
    summary_df, heatmap_df = scenario_grid(
        basket,
        base_yields,
        params["futures_price"],
        params["repo_rate"],
        params["days"],
        shifts_bps=SHIFTS,
        as_of=as_of,
    )
    ok = True
except Exception as e:
    st.error(f"Scenario computation failed: {e}")
    ok = False

if not ok:
    st.stop()

# ── Metric row: base-case (shift=0) ─────────────────────────────────────────
base_row = summary_df[summary_df["shift_bps"] == 0].iloc[0]

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        mc("CTD (base case)", base_row["ctd_label"],
           f"IR {base_row['ctd_implied_repo']*100:.3f}%"),
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        mc("Runner-up", base_row["runner_label"],
           f"IR {base_row['runner_implied_repo']*100:.3f}%"),
        unsafe_allow_html=True,
    )
with col3:
    spread_cls = "neg" if base_row["spread_bps"] < 10 else ("neu" if base_row["spread_bps"] < 25 else "pos")
    st.markdown(
        mc("Spread to runner-up",
           f"{base_row['spread_bps']:.1f} bps", "", spread_cls),
        unsafe_allow_html=True,
    )
with col4:
    transitions = int(summary_df["ctd_changed"].sum())
    st.markdown(
        mc("CTD switches in grid",
           str(transitions),
           f"across {len(SHIFTS)} shift scenarios"),
        unsafe_allow_html=True,
    )

# ── Heatmap ─────────────────────────────────────────────────────────────────
sh("Implied repo heat map  ·  bonds × yield shift (bps)")

# heatmap_df: rows=bond label, cols=shift_bps, values=implied_repo %
bonds  = heatmap_df.index.tolist()
shifts = [int(c) for c in heatmap_df.columns]
z      = heatmap_df.values.tolist()

# Build text annotations: show value, suffix "★" for CTD
ctd_by_shift = dict(zip(summary_df["shift_bps"], summary_df["ctd_label"]))
text_matrix = []
for bond in bonds:
    row_text = []
    for sh_val in shifts:
        ir_val = heatmap_df.loc[bond, sh_val]
        marker = " ★" if ctd_by_shift.get(sh_val) == bond else ""
        row_text.append(f"{ir_val:.3f}%{marker}")
    text_matrix.append(row_text)

col_labels = [f"{s:+d}" for s in shifts]

fig_hm = go.Figure(go.Heatmap(
    z=z,
    x=col_labels,
    y=bonds,
    text=text_matrix,
    texttemplate="%{text}",
    textfont=dict(size=10, family="'Courier New', monospace"),
    colorscale=[
        [0.0,  "#1a0a0a"],
        [0.35, "#7d1f1f"],
        [0.55, "#d29922"],
        [0.75, "#1a4a1a"],
        [1.0,  "#3fb950"],
    ],
    colorbar=dict(
        title=dict(text="Impl. Repo %", font=dict(color="#8b949e", size=10)),
        tickfont=dict(color="#8b949e", size=9),
        thickness=12,
        len=0.8,
    ),
    hovertemplate=(
        "<b>%{y}</b><br>"
        "Shift: %{x} bps<br>"
        "Implied Repo: %{text}<extra></extra>"
    ),
))

fig_hm.update_layout(
    **{k: v for k, v in PLOTLY_BASE.items() if k not in ("xaxis", "yaxis")},
    height=max(280, 60 + len(bonds) * 52),
    xaxis=dict(
        **PLOTLY_BASE["xaxis"],
        title="Yield shift (bps)",
        side="bottom",
    ),
    yaxis=dict(
        **PLOTLY_BASE["yaxis"],
        title="",
        autorange="reversed",
    ),
)

st.plotly_chart(fig_hm, use_container_width=True)
st.caption(
    "★ = CTD at that yield shift. "
    "Darker red = lower implied repo (more expensive to deliver). "
    "Brighter green = higher implied repo (cheapest to deliver)."
)

# ── Summary table ────────────────────────────────────────────────────────────
sh("CTD identity by shift")

base_ctd = base_row["ctd_label"]

rows = ""
for _, row in summary_df.iterrows():
    shift_val   = int(row["shift_bps"])
    shift_str   = f"{shift_val:+d} bps"
    ctd_lbl     = row["ctd_label"]
    ir_str      = f"{row['ctd_implied_repo']*100:.4f}%"
    runner_lbl  = row["runner_label"]
    spread_str  = f"{row['spread_bps']:.1f} bps"
    changed     = bool(row["ctd_changed"])

    row_cls = ' class="ctd-row"' if shift_val == 0 else ""
    ctd_col = (
        f'<span style="color:#f85149;font-weight:700">{ctd_lbl} ⚠</span>'
        if changed else
        f'<span style="color:#58a6ff;font-weight:600">{ctd_lbl}</span>'
    )
    changed_col = (
        '<span style="color:#f85149">yes</span>'
        if changed else
        '<span style="color:#3fb950">—</span>'
    )
    rows += (
        f'<tr{row_cls}>'
        f'<td>{shift_str}</td>'
        f'<td>{ctd_col}</td>'
        f'<td>{ir_str}</td>'
        f'<td style="color:#8b949e">{runner_lbl}</td>'
        f'<td>{spread_str}</td>'
        f'<td>{changed_col}</td>'
        f'</tr>'
    )

st.markdown(
    '<table class="fi-table"><thead>'
    '<tr>'
    '<th>Shift</th>'
    '<th>CTD Bond</th>'
    '<th>CTD Impl. Repo</th>'
    '<th>Runner-up</th>'
    '<th>Spread</th>'
    '<th>CTD Changed?</th>'
    '</tr>'
    f'</thead><tbody>{rows}</tbody></table>',
    unsafe_allow_html=True,
)
st.caption(
    f"Base case (0 bps) CTD: {base_ctd}. "
    "Red rows indicate CTD identity changes vs. the base case. "
    "Yield assumption: flat yield from sidebar applied to all bonds."
)
