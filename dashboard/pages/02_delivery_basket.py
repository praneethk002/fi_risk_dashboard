"""Page 02 — Delivery Basket.

Full basket ranking table with all analytics columns + CTD transition risk gauge.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go

from dashboard.shared import (
    CONTRACT, C_BLUE, C_GREEN, C_RED, C_AMBER,
    PLOTLY_BASE, inject_css, mc, sh, banner, sidebar_inputs, fresh_basket,
)

st.set_page_config(page_title="Delivery Basket", page_icon="📋", layout="wide")
inject_css()
params = sidebar_inputs()

st.markdown(
    '<div style="color:#e6edf3;font-size:1.2rem;font-weight:700;padding:0.4rem 0 0.8rem;">'
    '02 · Delivery Basket</div>',
    unsafe_allow_html=True,
)

ranked = fresh_basket(
    params["futures_price"], params["repo_rate"],
    params["days"], params["flat_yield"],
)

ctd    = ranked[ranked["is_ctd"]].iloc[0]
runner = ranked[ranked.index == 2].iloc[0]
spread = (ctd["implied_repo"] - runner["implied_repo"]) * 10_000

# ── CTD transition risk gauge ──────────────────────────────────────────────────
sh("CTD transition risk")
col_gauge, col_detail = st.columns([2, 3], gap="large")

with col_gauge:
    # Gauge: 0–100bps range; red zone < 10bps, amber 10–25bps, green > 25bps
    MAX_SPREAD = 100.0
    pct = min(spread / MAX_SPREAD, 1.0)

    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=spread,
        number=dict(suffix=" bps", font=dict(color="#e6edf3", size=28, family="Courier New")),
        delta=dict(reference=25, increasing=dict(color=C_GREEN), decreasing=dict(color=C_RED)),
        gauge=dict(
            axis=dict(range=[0, MAX_SPREAD], tickcolor="#8b949e",
                      tickfont=dict(color="#8b949e", size=10)),
            bar=dict(color=C_BLUE, thickness=0.25),
            bgcolor="#161b27",
            borderwidth=0,
            steps=[
                dict(range=[0,  10], color="#3d1f1f"),
                dict(range=[10, 25], color="#3d2e0d"),
                dict(range=[25, MAX_SPREAD], color="#0d2318"),
            ],
            threshold=dict(
                line=dict(color=C_AMBER, width=2),
                thickness=0.75,
                value=25,
            ),
        ),
        title=dict(text="Spread to runner-up", font=dict(color="#8b949e", size=11)),
    ))
    fig_gauge.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Courier New", color="#8b949e"),
        height=220,
        margin=dict(t=30, b=10, l=20, r=20),
    )
    st.plotly_chart(fig_gauge, use_container_width=True)

with col_detail:
    if spread <= 10:
        banner(
            f"<b>Elevated risk:</b> only <b>{spread:.1f}bps</b> separates {ctd['label']} from "
            f"{runner['label']}. A small yield move could trigger a CTD switch.",
            "banner-red",
        )
    elif spread <= 25:
        banner(
            f"<b>Moderate risk:</b> {spread:.1f}bps spread. "
            f"Monitor {runner['label']} as the likely next CTD.",
            "banner-warn",
        )
    else:
        banner(
            f"<b>Low risk:</b> {spread:.1f}bps spread. "
            f"{ctd['label']} is firmly CTD.",
            "banner-ok",
        )

    c1, c2 = st.columns(2)
    c1.markdown(mc("CTD",         ctd["label"],    f"IR: {ctd['implied_repo']*100:.4f}%"),    unsafe_allow_html=True)
    c2.markdown(mc("Runner-up",   runner["label"], f"IR: {runner['implied_repo']*100:.4f}%"), unsafe_allow_html=True)

# ── Full basket table ──────────────────────────────────────────────────────────
sh("Full basket analytics")

rows = ""
for rank, row in ranked.iterrows():
    is_ctd   = row["is_ctd"]
    ir_color = "pos" if row["implied_repo"] > params["repo_rate"] else "neg"
    nb_color = "pos" if row["net_basis"] < 0 else "neg"
    tr_cls   = "ctd-row" if is_ctd else ""
    flag     = " ★" if is_ctd else ""
    rows += (
        f'<tr class="{tr_cls}">'
        f'<td>{rank}</td>'
        f'<td>{row["label"]}{flag}</td>'
        f'<td style="color:#8b949e;font-size:0.7rem">{row["cusip"]}</td>'
        f'<td>{row["coupon"]*100:.3f}%</td>'
        f'<td>{row["maturity"]}</td>'
        f'<td>{row["cash_price"]:.4f}</td>'
        f'<td>{row["conv_factor"]:.4f}</td>'
        f'<td>{row["gross_basis"]:.4f}</td>'
        f'<td>{row["carry"]:.4f}</td>'
        f'<td class="{nb_color}">{row["net_basis"]:.4f}</td>'
        f'<td class="{ir_color}">{row["implied_repo"]*100:.4f}%</td>'
        f'</tr>'
    )

st.markdown(
    '<table class="fi-table"><thead>'
    '<tr><th>Rank</th><th>Bond</th><th>CUSIP</th><th>Coupon</th><th>Maturity</th>'
    '<th>Price</th><th>CF</th><th>Gross Basis</th><th>Carry</th>'
    '<th>Net Basis</th><th>Impl. Repo</th></tr>'
    f'</thead><tbody>{rows}</tbody></table>',
    unsafe_allow_html=True,
)
st.caption(
    "★ = CTD  ·  Gross basis = cash − futures × CF  ·  "
    "Carry = coupon accrual (ACT/365) − repo financing (ACT/360)  ·  "
    "Net basis = gross basis − carry  ·  "
    "Implied repo > market repo → positive carry for the basis trade"
)

# ── Implied repo bar chart ─────────────────────────────────────────────────────
sh("Implied repo by bond")

colors = [C_BLUE if b else "#1c2736" for b in ranked["is_ctd"]]
fig = go.Figure(go.Bar(
    x=ranked["label"].tolist(),
    y=(ranked["implied_repo"] * 100).tolist(),
    marker_color=colors,
    text=[f"{v:.3f}%" for v in ranked["implied_repo"] * 100],
    textposition="outside",
    textfont=dict(size=9, color="#8b949e"),
))
fig.add_hline(
    y=params["repo_rate"] * 100,
    line=dict(color=C_AMBER, dash="dot", width=1.5),
    annotation_text=f"  Repo {params['repo_rate']*100:.2f}%",
    annotation_font=dict(color=C_AMBER, size=10),
)
fig.add_hline(y=0, line=dict(color="#30363d", width=1))
fig.update_layout(
    **{k: v for k, v in PLOTLY_BASE.items() if k not in ("xaxis", "yaxis")},
    height=300,
    showlegend=False,
    xaxis=dict(**PLOTLY_BASE["xaxis"], tickangle=-30),
    yaxis=dict(**PLOTLY_BASE["yaxis"], title="Implied Repo (%)"),
)
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "Blue bar = CTD (highest implied repo).  "
    "Bonds above the amber line earn more than the repo rate — "
    "basis trade is profitable for these bonds."
)
