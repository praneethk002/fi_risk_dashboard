"""CTD Basis Monitor — entry point and landing page.

Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from dashboard.shared import (
    CONTRACT, C_BLUE, C_GREEN, C_AMBER,
    inject_css, mc, sh, banner, sidebar_inputs, get_db, fresh_basket,
)

st.set_page_config(
    page_title="CTD Basis Monitor",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()
params = sidebar_inputs()

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="padding:0.5rem 0 1rem;">
  <div style="color:#e6edf3;font-size:1.4rem;font-weight:700;letter-spacing:0.02em;">
    CTD Basis Monitor
  </div>
  <div style="color:#8b949e;font-size:0.75rem;letter-spacing:0.05em;margin-top:0.2rem;">
    TYM26 · US Treasury 10-Year Note Futures · Cash-Futures Basis &amp; CTD Tracking
  </div>
</div>
""", unsafe_allow_html=True)

# ── DB status ──────────────────────────────────────────────────────────────────
db = get_db()
try:
    db.init_schema()
    latest = db.get_current_basket(CONTRACT)
    has_data = not latest.empty
except Exception:
    has_data = False

if has_data:
    snap_dt = latest["snapshot_dt"].iloc[0]
    banner(
        f"<b>Database:</b> latest snapshot <b>{snap_dt}</b> · "
        f"{len(latest)} bonds · "
        f'<span class="pos">live data available</span>',
        "banner-ok",
    )
else:
    banner(
        "<b>No snapshot data yet.</b>  Run the ingest CLI to populate the database:<br>"
        "<code>python -m data.ingest --contract TYM26 --futures-price 108.50 "
        "--repo-rate 0.053 --dry-run</code>  (remove --dry-run to write)",
        "banner-warn",
    )

# ── Quick metrics from fresh basket ───────────────────────────────────────────
ranked = fresh_basket(
    params["futures_price"], params["repo_rate"],
    params["days"], params["flat_yield"],
)

ctd    = ranked[ranked["is_ctd"]].iloc[0]
runner = ranked[ranked.index == 2].iloc[0]
spread = (ctd["implied_repo"] - runner["implied_repo"]) * 10_000
nb_cls = "pos" if ctd["net_basis"] < 0 else "neg"
ir_cls = "pos" if ctd["implied_repo"] > params["repo_rate"] else "neg"

sh("Current snapshot")
c1, c2, c3, c4 = st.columns(4)
c1.markdown(mc("CTD Bond",     ctd["label"],                      f"rank 1 of {len(ranked)}"), unsafe_allow_html=True)
c2.markdown(mc("Implied Repo", f"{ctd['implied_repo']*100:.4f}%", "annualised", ir_cls),       unsafe_allow_html=True)
c3.markdown(mc("Spread to #2", f"{spread:.1f}bps",                runner["label"], "neu"),     unsafe_allow_html=True)
c4.markdown(mc("Net Basis",    f"{ctd['net_basis']:.4f}",         "price points", nb_cls),     unsafe_allow_html=True)

# ── Getting started ────────────────────────────────────────────────────────────
sh("Getting started")
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
**1 · Seed the database**

```bash
python -m data.ingest \\
  --contract TYM26 \\
  --futures-price 108.50 \\
  --repo-rate 0.053
```
Requires `FRED_API_KEY` in `.env`,
or use `--overrides '{…}'` for
manual prices.
""")

with col2:
    st.markdown("""
**2 · Navigate the pages**

| Page | Content |
|---|---|
| 01 Basis Monitor | CTD + 90-day history |
| 02 Delivery Basket | Full basket ranking |
| 03 CTD History | Transition timeline |
| 04 Scenario Grid | Yield-shock heatmap |
""")

with col3:
    st.markdown("""
**3 · Set market inputs**

Use the **sidebar** on every page:

- **Futures price** — from CME
- **Repo rate** — from DTCC GCF
- **Days to delivery** — count to
  last business day of delivery month
- **Flat yield** — baseline for
  scenario grid
""")
