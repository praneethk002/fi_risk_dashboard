"""Page 01 — Basis Monitor (primary view).

Live basket ranked by implied repo + 90-day net basis history for the CTD.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go

from dashboard.shared import (
    CONTRACT, C_BLUE, C_GREEN, C_RED, C_AMBER, C_PURPLE,
    PLOTLY_BASE, inject_css, mc, sh, banner, sidebar_inputs,
    get_db, fresh_basket,
)

st.set_page_config(page_title="Basis Monitor", page_icon="📊", layout="wide")
inject_css()
params = sidebar_inputs()

st.markdown(
    '<div style="color:#e6edf3;font-size:1.2rem;font-weight:700;padding:0.4rem 0 0.8rem;">'
    '01 · Basis Monitor</div>',
    unsafe_allow_html=True,
)

# ── Data ───────────────────────────────────────────────────────────────────────
ranked = fresh_basket(
    params["futures_price"], params["repo_rate"],
    params["days"], params["flat_yield"],
)

ctd    = ranked[ranked["is_ctd"]].iloc[0]
runner = ranked[ranked.index == 2].iloc[0]
spread = (ctd["implied_repo"] - runner["implied_repo"]) * 10_000
ir_cls = "pos" if ctd["implied_repo"] > params["repo_rate"] else "neg"
nb_cls = "pos" if ctd["net_basis"] < 0 else "neg"

# Risk level for spread
if spread > 20:
    risk_txt, risk_cls = "Low transition risk", "banner-ok"
elif spread > 8:
    risk_txt, risk_cls = "Moderate transition risk", "banner-warn"
else:
    risk_txt, risk_cls = "Elevated transition risk — spread narrow", "banner-red"

banner(
    f"CTD: <b>{ctd['label']}</b> &nbsp;·&nbsp; "
    f"Implied repo: <b>{ctd['implied_repo']*100:.4f}%</b> &nbsp;·&nbsp; "
    f"Spread to runner-up ({runner['label']}): <b>{spread:.1f}bps</b> &nbsp;·&nbsp; "
    f"{risk_txt}",
    risk_cls,
)

# ── Metric cards ───────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.markdown(mc("CTD Bond",     ctd["label"],                      f"rank 1 of {len(ranked)}"),  unsafe_allow_html=True)
c2.markdown(mc("Implied Repo", f"{ctd['implied_repo']*100:.4f}%", f"market repo {params['repo_rate']*100:.3f}%", ir_cls), unsafe_allow_html=True)
c3.markdown(mc("Spread to #2", f"{spread:.1f}bps",                runner["label"]),             unsafe_allow_html=True)
c4.markdown(mc("Net Basis",    f"{ctd['net_basis']:.4f}",         "price points — CTD",  nb_cls), unsafe_allow_html=True)

# ── Two-column layout: basket table | history chart ───────────────────────────
col_left, col_right = st.columns([5, 4], gap="large")

with col_left:
    sh("Delivery basket · ranked by implied repo")

    rows = ""
    for rank, row in ranked.iterrows():
        is_ctd = row["is_ctd"]
        ir_color = "pos" if row["implied_repo"] > params["repo_rate"] else "neg"
        nb_color = "pos" if row["net_basis"] < 0 else "neg"
        tr_cls = "ctd-row" if is_ctd else ""
        ctd_flag = " ★" if is_ctd else ""
        rows += (
            f'<tr class="{tr_cls}">'
            f'<td>{rank}</td>'
            f'<td>{row["label"]}{ctd_flag}</td>'
            f'<td>{row["cash_price"]:.4f}</td>'
            f'<td>{row["conv_factor"]:.4f}</td>'
            f'<td class="{nb_color}">{row["net_basis"]:.4f}</td>'
            f'<td class="{ir_color}">{row["implied_repo"]*100:.4f}%</td>'
            f'</tr>'
        )

    st.markdown(
        '<table class="fi-table"><thead>'
        '<tr><th>Rank</th><th>Bond</th><th>Price</th><th>CF</th>'
        '<th>Net Basis</th><th>Impl. Repo</th></tr>'
        f'</thead><tbody>{rows}</tbody></table>',
        unsafe_allow_html=True,
    )
    st.caption("★ = CTD  ·  Net basis in price points  ·  Green = positive carry vs repo")

with col_right:
    sh("Net basis history · CTD bond")

    db = get_db()
    try:
        hist = db.get_basis_history(ctd["cusip"], CONTRACT, days=90)
    except Exception:
        hist = None

    if hist is not None and not hist.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist["snapshot_dt"], y=hist["net_basis"],
            mode="lines+markers", name="Net Basis",
            line=dict(color=C_BLUE, width=2),
            marker=dict(size=5, color=C_BLUE),
        ))
        fig.add_trace(go.Scatter(
            x=hist["snapshot_dt"], y=hist["ma_20d"],
            mode="lines", name="20d MA",
            line=dict(color=C_AMBER, width=1.5, dash="dash"),
        ))
        fig.add_hline(y=0, line=dict(color="#30363d", width=1))
        fig.update_layout(
            **{k: v for k, v in PLOTLY_BASE.items() if k not in ("xaxis", "yaxis")},
            height=320,
            xaxis=dict(**PLOTLY_BASE["xaxis"], title="Date"),
            yaxis=dict(**PLOTLY_BASE["yaxis"], title="Net Basis (pts)"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Percentile from DB
        try:
            pct = db.get_basis_percentile(CONTRACT, days=90)
            ctd_pct = pct[pct["cusip"] == ctd["cusip"]]
            if not ctd_pct.empty:
                p = ctd_pct.iloc[0]["pct_rank"] * 100
                p_cls = "pos" if p < 30 else ("neg" if p > 70 else "neu")
                st.markdown(
                    mc("90d Percentile", f"{p:.0f}th",
                       "of net basis distribution", p_cls),
                    unsafe_allow_html=True,
                )
        except Exception:
            pass

    else:
        st.markdown(
            '<div class="banner banner-warn">'
            '<b>No history yet.</b> Run the ingest CLI to build 90-day history:<br>'
            '<code>python -m data.ingest --contract TYM26 --futures-price '
            f'{params["futures_price"]:.2f} --repo-rate {params["repo_rate"]:.4f}</code>'
            '</div>',
            unsafe_allow_html=True,
        )
        # Show implied repo for all bonds as a static bar chart instead
        sh("Implied repo · current snapshot")
        fig_bar = go.Figure(go.Bar(
            x=ranked["label"].tolist(),
            y=(ranked["implied_repo"] * 100).tolist(),
            marker_color=[C_BLUE if b else "#30363d" for b in ranked["is_ctd"]],
            text=[f"{v:.3f}%" for v in ranked["implied_repo"] * 100],
            textposition="outside",
            textfont=dict(size=9, color="#8b949e"),
        ))
        fig_bar.add_hline(
            y=params["repo_rate"] * 100,
            line=dict(color=C_AMBER, dash="dot", width=1.5),
            annotation_text=f"  Repo {params['repo_rate']*100:.2f}%",
            annotation_font=dict(color=C_AMBER, size=10),
        )
        fig_bar.update_layout(
            **{k: v for k, v in PLOTLY_BASE.items() if k not in ("xaxis", "yaxis")},
            height=320,
            showlegend=False,
            xaxis=dict(**PLOTLY_BASE["xaxis"], tickangle=-35),
            yaxis=dict(**PLOTLY_BASE["yaxis"], title="Implied Repo (%)"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)
