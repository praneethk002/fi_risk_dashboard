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

# ── SIDEBAR — Bond Inputs ──────────────────────────────────────
st.sidebar.header("Bond Parameters")
face_value = st.sidebar.number_input("Face Value", value=1000.0)
coupon_rate = st.sidebar.number_input("Coupon Rate (%)", value=5.0) / 100
years_to_maturity = st.sidebar.number_input("Years to Maturity", value=10, min_value=1)
yield_rate = st.sidebar.number_input("Yield (%)", value=4.5) / 100
frequency = st.sidebar.selectbox("Payment Frequency", [1, 2, 4], index=1)

# ── SECTION 1 — Risk Summary ───────────────────────────────────
st.header("Risk Summary")

price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
dur = modified_duration(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
dv01_val = dv01(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
cvx = convexity(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Price", f"£{price:.2f}")
col2.metric("Duration", f"{dur:.2f} yrs")
col3.metric("DV01", f"£{dv01_val:.4f}")
col4.metric("Convexity", f"{cvx:.2f}")

# ── SECTION 2 — Yield Curve ────────────────────────────────────
st.header("Live Yield Curve")

with st.spinner("Fetching live rates..."):
    try:
        curve = get_yield_curve()
        curve_label = "Live (FRED)"
    except:
        curve = {"3M": 0.037, "2Y": 0.0347, "5Y": 0.0362, "10Y": 0.0405, "30Y": 0.047}
        curve_label = "Fallback (hardcoded)"

st.caption(f"Source: {curve_label}")

# ── SECTION 3 — Scenario Analysis ─────────────────────────────
st.header("Scenario Analysis")

scenario = st.selectbox("Select Scenario", [
    "Parallel Shift", "Bear Steepening", "Bear Flattening", "Custom"
])
shift_bps = st.slider("Shift (bps)", min_value=-200, max_value=200, value=50, step=5)

if scenario == "Parallel Shift":
    shifted_curve = parallel_shift(curve, shift_bps)
elif scenario == "Bear Steepening":
    shifted_curve = bear_steepening(curve, shift_bps)
elif scenario == "Bear Flattening":
    shifted_curve = bear_flattening(curve, shift_bps)
else:
    st.info("Custom: edit shifts per maturity below")
    custom_shifts = {}
    for maturity in curve:
        custom_shifts[maturity] = st.number_input(f"{maturity} shift (bps)", value=0)
    shifted_curve = custom_shift(curve, custom_shifts)

# Plot original vs shifted curve
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=list(curve.keys()), y=[r * 100 for r in curve.values()],
    name="Current", line=dict(color="blue", width=2)
))
fig.add_trace(go.Scatter(
    x=list(shifted_curve.keys()), y=[r * 100 for r in shifted_curve.values()],
    name="Shifted", line=dict(color="red", width=2, dash="dash")
))
fig.update_layout(
    xaxis_title="Maturity", yaxis_title="Rate (%)",
    height=350, margin=dict(t=20)
)
st.plotly_chart(fig, use_container_width=True)

# Price impact
new_yield = shifted_curve.get("10Y", yield_rate)
new_price = price_bond(face_value, coupon_rate, years_to_maturity, new_yield, frequency)
price_change = new_price - price

col1, col2 = st.columns(2)
col1.metric("New Price", f"£{new_price:.2f}", delta=f"£{price_change:.2f}")
col2.metric("Price Change %", f"{(price_change/price)*100:.2f}%")

# ── SECTION 4 — Basis Calculator ──────────────────────────────
st.header("Cash Futures Basis")

col1, col2, col3 = st.columns(3)
cash_price = col1.number_input("Cash Price", value=98.50)
futures_price = col2.number_input("Futures Price", value=97.00)
conversion_factor = col3.number_input("Conversion Factor", value=0.9750)

col1, col2, col3 = st.columns(3)
repo_rate = col1.number_input("Repo Rate (%)", value=4.3) / 100
days_to_delivery = col2.number_input("Days to Delivery", value=90)

gb = gross_basis(cash_price, futures_price, conversion_factor)
nb = net_basis(cash_price, futures_price, conversion_factor,
               coupon_rate, repo_rate, int(days_to_delivery))
ir = implied_repo(cash_price, futures_price, conversion_factor,
                  coupon_rate, int(days_to_delivery))

col1, col2, col3 = st.columns(3)
col1.metric("Gross Basis", f"{gb:.4f}")
col2.metric("Net Basis", f"{nb:.4f}")
col3.metric("Implied Repo", f"{ir*100:.3f}%")