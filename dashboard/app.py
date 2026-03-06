"""Fixed Income Risk Dashboard — Streamlit UI.

Sections
--------
1. Risk Summary     — bond price, modified duration, DV01, convexity
2. Live Yield Curve — US Treasury curve from FRED (with 5-min cache)
3. Scenario Analysis — parallel shift, bear steepening/flattening, custom
4. Cash-Futures Basis — gross basis, net basis, implied repo
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go

from core.pricing import price_bond
from core.risk import modified_duration, dv01, convexity
from core.scenarios import parallel_shift, bear_steepening, bear_flattening, custom_shift
from core.basis import gross_basis, net_basis, implied_repo
from mcp_server.fred_client import get_yield_curve

st.set_page_config(page_title="FI Risk Dashboard", layout="wide")
st.title("Fixed Income Risk Dashboard")

# ── SIDEBAR — Bond Inputs ──────────────────────────────────────────────────
st.sidebar.header("Bond Parameters")
face_value = st.sidebar.number_input("Face Value ($)", value=1_000.0, step=100.0)
coupon_rate = st.sidebar.number_input("Coupon Rate (%)", value=5.0, step=0.25) / 100
years_to_maturity = st.sidebar.number_input("Years to Maturity", value=10, min_value=1, max_value=50)
yield_rate = st.sidebar.number_input("Yield (%)", value=4.5, step=0.05) / 100
frequency = st.sidebar.selectbox("Payment Frequency", [1, 2, 4], index=1,
                                  format_func=lambda f: {1: "Annual", 2: "Semi-annual", 4: "Quarterly"}[f])

# ── SECTION 1 — Risk Summary ───────────────────────────────────────────────
st.header("Risk Summary")

price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
dur = modified_duration(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
dv01_val = dv01(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
cvx = convexity(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Price", f"${price:.2f}")
col2.metric("Modified Duration", f"{dur:.2f} yrs")
col3.metric("DV01", f"${dv01_val:.4f}")
col4.metric("Convexity", f"{cvx:.2f}")

# ── SECTION 2 — Live Yield Curve ───────────────────────────────────────────
st.header("Live US Treasury Yield Curve")

_FALLBACK_CURVE = {
    "3M": 0.0425, "2Y": 0.0435, "5Y": 0.0448, "10Y": 0.0462, "30Y": 0.0478,
}

with st.spinner("Fetching live rates from FRED..."):
    try:
        curve = get_yield_curve()
        if not curve:
            raise ValueError("Empty response from FRED")
        curve_label = "Live (FRED)"
    except Exception as exc:
        curve = _FALLBACK_CURVE
        curve_label = f"Fallback — hardcoded ({exc})"

st.caption(f"Source: {curve_label}")

fig_curve = go.Figure()
fig_curve.add_trace(go.Scatter(
    x=list(curve.keys()),
    y=[r * 100 for r in curve.values()],
    mode="lines+markers",
    name="Yield (%)",
    line=dict(color="steelblue", width=2),
))
fig_curve.update_layout(
    xaxis_title="Maturity",
    yaxis_title="Yield (%)",
    height=300,
    margin=dict(t=10, b=40),
)
st.plotly_chart(fig_curve, use_container_width=True)

# ── SECTION 3 — Scenario Analysis ─────────────────────────────────────────
st.header("Scenario Analysis")

col_a, col_b = st.columns([2, 1])
with col_a:
    scenario = st.selectbox(
        "Yield Curve Scenario",
        ["Parallel Shift", "Bear Steepening", "Bear Flattening", "Custom"],
    )
with col_b:
    shift_bps = st.slider("Shift (bps)", min_value=-200, max_value=200, value=50, step=5)

if scenario == "Parallel Shift":
    shifted_curve = parallel_shift(curve, shift_bps)
elif scenario == "Bear Steepening":
    shifted_curve = bear_steepening(curve, shift_bps)
elif scenario == "Bear Flattening":
    shifted_curve = bear_flattening(curve, shift_bps)
else:
    st.info("Enter per-maturity shifts below.")
    custom_shifts: dict[str, float] = {}
    cols = st.columns(len(curve))
    for col, maturity in zip(cols, curve):
        custom_shifts[maturity] = col.number_input(f"{maturity} (bps)", value=0, step=5)
    shifted_curve = custom_shift(curve, custom_shifts)

fig_scenario = go.Figure()
fig_scenario.add_trace(go.Scatter(
    x=list(curve.keys()), y=[r * 100 for r in curve.values()],
    name="Current", line=dict(color="steelblue", width=2),
))
fig_scenario.add_trace(go.Scatter(
    x=list(shifted_curve.keys()), y=[r * 100 for r in shifted_curve.values()],
    name="Shocked", line=dict(color="crimson", width=2, dash="dash"),
))
fig_scenario.update_layout(
    xaxis_title="Maturity", yaxis_title="Yield (%)", height=320, margin=dict(t=10),
)
st.plotly_chart(fig_scenario, use_container_width=True)

new_yield = shifted_curve.get("10Y", yield_rate)
new_price = price_bond(face_value, coupon_rate, years_to_maturity, new_yield, frequency)
price_change = new_price - price
duration_est = -dur * (new_yield - yield_rate) * price
convexity_correction = 0.5 * cvx * (new_yield - yield_rate) ** 2 * price

col1, col2, col3, col4 = st.columns(4)
col1.metric("New 10Y Yield", f"{new_yield*100:.3f}%", delta=f"{(new_yield - yield_rate)*10000:.0f}bps")
col2.metric("New Price", f"${new_price:.2f}", delta=f"${price_change:.2f}")
col3.metric("Duration Estimate", f"${duration_est:.2f}")
col4.metric("Convexity Correction", f"${convexity_correction:.2f}")

# ── SECTION 4 — Cash-Futures Basis ────────────────────────────────────────
st.header("Cash-Futures Basis")
st.caption("Uses ACT/365 for coupon accrual and ACT/360 for repo financing (US convention).")

col1, col2, col3 = st.columns(3)
cash_p = col1.number_input("Cash Price (% of par)", value=98.50, step=0.01)
futures_p = col2.number_input("Futures Price (% of par)", value=97.00, step=0.01)
cf = col3.number_input("Conversion Factor", value=0.9750, step=0.0001, format="%.4f")

col1, col2, col3 = st.columns(3)
repo_r = col1.number_input("Repo Rate (%)", value=4.30, step=0.05) / 100
days = int(col2.number_input("Days to Delivery", value=90, min_value=1, max_value=365))
bond_coupon = coupon_rate  # reuse sidebar coupon for the deliverable bond

gb = gross_basis(cash_p, futures_p, cf)
nb = net_basis(cash_p, futures_p, cf, bond_coupon, repo_r, days)
ir = implied_repo(cash_p, futures_p, cf, bond_coupon, days)

col1, col2, col3 = st.columns(3)
col1.metric("Gross Basis", f"{gb:.4f} pts")
col2.metric("Net Basis", f"{nb:.4f} pts")
col3.metric("Implied Repo", f"{ir*100:.3f}%")

if ir > repo_r:
    st.success(f"Implied repo ({ir*100:.3f}%) > actual repo ({repo_r*100:.3f}%) — carry trade looks attractive.")
else:
    st.info(f"Implied repo ({ir*100:.3f}%) ≤ actual repo ({repo_r*100:.3f}%) — no carry advantage.")
