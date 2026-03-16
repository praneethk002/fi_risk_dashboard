"""CTD Basis Monitor — landing page.

Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from dashboard.shared import (
    CONTRACT, inject_css, sh, banner, sidebar_inputs, get_db, fresh_basket,
)

st.set_page_config(
    page_title="CTD Basis Monitor",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()
params = sidebar_inputs()

# ── DB probe ───────────────────────────────────────────────────────────────────
db = get_db()
try:
    db.init_schema()
    latest = db.get_current_basket(CONTRACT)
    has_data = not latest.empty
    snap_dt  = str(latest["snapshot_dt"].iloc[0]) if has_data else None
    n_bonds  = len(latest) if has_data else 0
except Exception:
    has_data = False
    snap_dt  = None
    n_bonds  = 0

# ── Basket analytics ───────────────────────────────────────────────────────────
ranked = fresh_basket(
    params["futures_price"], params["repo_rate"],
    params["days"], params["flat_yield"],
)
ctd    = ranked[ranked["is_ctd"]].iloc[0]
runner = ranked[ranked.index == 2].iloc[0]
spread = (ctd["implied_repo"] - runner["implied_repo"]) * 10_000

if spread < 10:
    risk_pill  = '<span class="pill pill-red">High&nbsp;Risk</span>'
elif spread < 25:
    risk_pill  = '<span class="pill pill-amber">Elevated</span>'
else:
    risk_pill  = '<span class="pill pill-green">Low Risk</span>'

nb_color = "#3fb950" if ctd["net_basis"] <= 0 else "#f85149"
ir_vs_repo = ctd["implied_repo"] - params["repo_rate"]
ir_color   = "#3fb950" if ir_vs_repo >= 0 else "#f85149"
ir_arrow   = "▲" if ir_vs_repo >= 0 else "▼"

today = date.today().strftime("%b %d, %Y")

# ── Hero header ────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="display:flex;align-items:flex-start;justify-content:space-between;
            padding:0.2rem 0 1.4rem;border-bottom:1px solid #111827;margin-bottom:1.4rem;">
  <div>
    <div style="font-size:1.7rem;font-weight:700;letter-spacing:-0.03em;color:#e6edf3;line-height:1.1;">
      CTD Basis Monitor
    </div>
    <div style="font-size:0.75rem;color:#374151;margin-top:0.35rem;letter-spacing:0.02em;">
      TYM26 &middot; US Treasury 10-Year Note Futures &middot; Cash-Futures Basis &amp; CTD Tracking
    </div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;padding-top:4px;">
    <div class="live-badge"><span class="live-dot"></span>Live</div>
    <div style="font-size:0.62rem;color:#374151;letter-spacing:0.05em;">{today}</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Status bar ─────────────────────────────────────────────────────────────────
if has_data:
    banner(
        f'<b>Database connected</b> &middot; latest snapshot <b>{snap_dt}</b> &middot; '
        f'{n_bonds} bonds &middot; <span class="pos">history available</span>',
        "banner-ok",
    )
else:
    banner(
        "<b>No database snapshot yet.</b> &nbsp;Seed it once to enable the history pages:<br>"
        "<code>python -m data.ingest --contract TYM26 --futures-price 108.50 --repo-rate 0.053</code>",
        "banner-warn",
    )

# ── KPI cards ──────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:1.5rem;">

  <div class="kpi-card">
    <div class="kpi-accent" style="--accent:linear-gradient(90deg,transparent,#58a6ff 50%,transparent)"></div>
    <div class="kpi-lbl">CTD Bond</div>
    <div class="kpi-val kpi-val-text">{ctd["label"]}</div>
    <div class="kpi-sub">
      rank&nbsp;1&nbsp;of&nbsp;{len(ranked)}
      &nbsp;<span class="pill pill-blue">CTD</span>
    </div>
  </div>

  <div class="kpi-card">
    <div class="kpi-accent" style="--accent:linear-gradient(90deg,transparent,{ir_color} 50%,transparent)"></div>
    <div class="kpi-lbl">Implied Repo</div>
    <div class="kpi-val" style="color:{ir_color};">{ctd["implied_repo"]*100:.4f}%</div>
    <div class="kpi-sub">
      <span style="color:{ir_color};">{ir_arrow}&nbsp;{abs(ir_vs_repo*100):.2f}% vs repo</span>
    </div>
  </div>

  <div class="kpi-card">
    <div class="kpi-accent" style="--accent:linear-gradient(90deg,transparent,#d29922 50%,transparent)"></div>
    <div class="kpi-lbl">Spread to Runner-up</div>
    <div class="kpi-val">{spread:.1f}<span style="font-size:1rem;color:#374151;">&nbsp;bps</span></div>
    <div class="kpi-sub">
      vs {runner["label"]}&nbsp;&nbsp;{risk_pill}
    </div>
  </div>

  <div class="kpi-card">
    <div class="kpi-accent" style="--accent:linear-gradient(90deg,transparent,{nb_color} 50%,transparent)"></div>
    <div class="kpi-lbl">Net Basis (CTD)</div>
    <div class="kpi-val" style="color:{nb_color};">{ctd["net_basis"]:.4f}</div>
    <div class="kpi-sub">price points &middot; short optionality</div>
  </div>

</div>
""", unsafe_allow_html=True)

# ── Delivery basket snapshot ───────────────────────────────────────────────────
sh("Delivery Basket  ·  ranked by implied repo")

max_ir = ranked["implied_repo"].max()
rows_html = ""
for _, row in ranked.iterrows():
    bar_pct  = (row["implied_repo"] / max_ir * 100) if max_ir > 0 else 0
    is_ctd   = bool(row["is_ctd"])
    row_cls  = ' class="ctd-row"' if is_ctd else ""
    ctd_tag  = '&nbsp;<span class="pill pill-blue" style="font-size:0.52rem;padding:1px 6px;">CTD</span>' if is_ctd else ""
    ir_col   = "#58a6ff" if is_ctd else "#c9d1d9"
    nb_cls   = "pos" if row["net_basis"] <= 0 else "neg"
    rows_html += (
        f'<tr{row_cls}>'
        f'<td>{row["label"]}{ctd_tag}</td>'
        f'<td style="color:{ir_col};">'
        f'{row["implied_repo"]*100:.3f}%'
        f'<div class="ir-bar-track"><div class="ir-bar-fill" style="width:{bar_pct:.0f}%"></div></div>'
        f'</td>'
        f'<td><span class="{nb_cls}">{row["net_basis"]:.4f}</span></td>'
        f'<td>{row["gross_basis"]:.4f}</td>'
        f'<td style="color:#374151;">{row["conv_factor"]:.4f}</td>'
        f'</tr>'
    )

st.markdown(
    '<div style="overflow-x:auto;">'
    '<table class="fi-table"><thead>'
    '<tr>'
    '<th style="text-align:left;">Bond</th>'
    '<th>Implied Repo</th>'
    '<th>Net Basis</th>'
    '<th>Gross Basis</th>'
    '<th>Conv. Factor</th>'
    '</tr>'
    f'</thead><tbody>{rows_html}</tbody></table>'
    '</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Implied repo = annualised return from buying the bond and delivering into futures. "
    "Highest implied repo = CTD. Net basis = gross basis − carry; negative = short has an edge."
)

# ── Navigation cards ───────────────────────────────────────────────────────────
sh("Explore")

c1, c2, c3, c4 = st.columns(4)

n_transitions = 0
if has_data:
    try:
        tr = db.get_ctd_transitions(CONTRACT)
        n_transitions = len(tr)
    except Exception:
        pass

with c1:
    st.markdown(f"""
    <div class="nav-card">
      <div class="nav-card-num">01</div>
      <div class="nav-card-title">Basis Monitor</div>
      <div class="nav-card-desc">
        Live basket ranking + 90-day net basis chart with rolling 20-day mean.
        Spot when the basis is historically wide or compressed.
      </div>
      <div class="nav-card-stat">{ctd["implied_repo"]*100:.3f}% IR</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="nav-card">
      <div class="nav-card-num">02</div>
      <div class="nav-card-title">Delivery Basket</div>
      <div class="nav-card-desc">
        Full analytics table — gross basis, carry, net basis, CF — plus a
        CTD transition risk gauge showing proximity to a switch.
      </div>
      <div class="nav-card-stat">{spread:.0f} bps spread</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="nav-card">
      <div class="nav-card-num">03</div>
      <div class="nav-card-title">CTD History</div>
      <div class="nav-card-desc">
        Gantt-style timeline of CTD identity over time. Implied repo spread
        chart showing how close previous switches were.
      </div>
      <div class="nav-card-stat">{n_transitions} transition{"s" if n_transitions != 1 else ""} logged</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    st.markdown(f"""
    <div class="nav-card">
      <div class="nav-card-num">04</div>
      <div class="nav-card-title">Scenario Grid</div>
      <div class="nav-card-desc">
        Parallel yield-shock heatmap (−100 to +100 bps). See which bond
        becomes CTD at each shift — the key question before a rate move.
      </div>
      <div class="nav-card-stat">±100 bps grid</div>
    </div>
    """, unsafe_allow_html=True)

st.caption("Use the sidebar on each page to update futures price, repo rate, days to delivery, and flat yield.")
