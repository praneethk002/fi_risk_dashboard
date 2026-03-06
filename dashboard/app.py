"""Fixed Income Risk Dashboard — Professional UI.

Tabbed layout
-------------
1  Yield Curve       Nelson-Siegel fit over live FRED data, NS params, curve spreads
2  Risk Metrics      Price, modified duration, DV01, convexity, sensitivity curve
3  Carry & Roll      Multi-horizon carry + roll-down waterfall + forward breakeven
4  Scenarios         Six scenario types, overlay chart, per-tenor P&L table
5  Z-Spread          Z-spread vs yield spread, Treasury spot curve overlay
6  Cash-Futures Basis Gross/net basis, implied repo, CTD signal
"""

from __future__ import annotations

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import streamlit as st
import plotly.graph_objects as go

from core.pricing import price_bond
from core.risk import modified_duration, dv01, convexity
from core.scenarios import (
    parallel_shift,
    bear_steepening,
    bear_flattening,
    bull_steepening,
    bull_flattening,
    custom_shift,
)
from core.basis import gross_basis, net_basis, implied_repo
from core.curves import (
    TREASURY_MATURITIES_YRS,
    fit_nelson_siegel,
    nelson_siegel_rate,
    NelsonSiegelParams,
    SpotCurve,
)
from core.analytics import (
    Bond,
    z_spread as compute_z_spread,
    roll_down_return,
    total_return_decomposition,
    curve_spreads,
    HOLD_3M,
    HOLD_6M,
    HOLD_1Y,
)
from mcp_server.fred_client import get_yield_curve

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FI Risk Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ─── Global ───────────────────────────────────────────── */
html, body, [class*="css"] { font-family: "Inter", "Segoe UI", sans-serif; }
.stApp { background-color: #0d1117; }
#MainMenu, footer { visibility: hidden; }

/* ─── Sidebar ──────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #161b27;
    border-right: 1px solid #21262d;
}
[data-testid="stSidebar"] .stMarkdown p {
    color: #8b949e;
    font-size: 0.68rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin: 1rem 0 0.3rem 0;
    font-weight: 600;
}

/* ─── Tabs ─────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background-color: #161b27;
    border-bottom: 1px solid #21262d;
    padding: 0 0.25rem;
}
.stTabs [data-baseweb="tab"] {
    color: #8b949e;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 0.65rem 1.1rem;
    border-radius: 0;
    border-bottom: 2px solid transparent;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    color: #58a6ff !important;
    border-bottom: 2px solid #58a6ff !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.2rem;
}

/* ─── Metric cards ─────────────────────────────────────── */
.mc {
    background: linear-gradient(160deg,#161b27 0%,#0d1117 100%);
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 0.9rem 1.1rem 0.8rem;
    margin-bottom: 0.5rem;
}
.mc-lbl {
    color: #8b949e;
    font-size: 0.6rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-weight: 600;
    margin-bottom: 0.25rem;
}
.mc-val {
    color: #e6edf3;
    font-size: 1.55rem;
    font-weight: 700;
    font-family: "Courier New", monospace;
    line-height: 1.1;
}
.mc-sub { color: #8b949e; font-size: 0.68rem; margin-top: 0.15rem; }
.pos { color: #3fb950; }  .neg { color: #f85149; }  .neu { color: #d29922; }

/* ─── Section header ───────────────────────────────────── */
.sh {
    color: #8b949e;
    font-size: 0.6rem;
    font-weight: 600;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    border-bottom: 1px solid #21262d;
    padding-bottom: 0.35rem;
    margin: 1.1rem 0 0.75rem 0;
}

/* ─── NS param badges ──────────────────────────────────── */
.ns-row { margin: 0.5rem 0 0.9rem; }
.ns-b {
    display: inline-block;
    background: #1c2128;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 0.2rem 0.7rem;
    margin: 0.15rem 0.2rem;
    font-family: "Courier New", monospace;
    font-size: 0.72rem;
    color: #e6edf3;
}
.ns-b span { color: #58a6ff; font-weight: 600; }

/* ─── Info banner ──────────────────────────────────────── */
.banner {
    background: #1c2128;
    border-left: 3px solid #58a6ff;
    border-radius: 0 4px 4px 0;
    padding: 0.6rem 0.9rem;
    font-size: 0.78rem;
    color: #8b949e;
    margin-bottom: 0.8rem;
}

/* ─── Data table ───────────────────────────────────────── */
.fi-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
    font-family: "Courier New", monospace;
}
.fi-table th {
    color: #8b949e;
    font-size: 0.6rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.4rem 0.8rem;
    text-align: right;
    border-bottom: 1px solid #21262d;
    background: #161b27;
}
.fi-table th:first-child { text-align: left; }
.fi-table td {
    padding: 0.45rem 0.8rem;
    border-bottom: 1px solid #161b27;
    color: #e6edf3;
    text-align: right;
}
.fi-table td:first-child { text-align: left; color: #8b949e; }
.fi-table tr:hover td { background: #1c2128; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

_FALLBACK_CURVE: dict[str, float] = {
    "3M": 0.0530, "2Y": 0.0488, "5Y": 0.0462, "10Y": 0.0455, "30Y": 0.0468,
}

_MATURITY_YEARS: dict[str, float] = {
    "3M": 0.25, "2Y": 2.0, "5Y": 5.0, "10Y": 10.0, "30Y": 30.0,
}

_PLOTLY_BASE: dict = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(13,17,23,0.5)",
    font=dict(family="'Courier New', monospace", color="#8b949e", size=11),
    margin=dict(t=24, b=44, l=56, r=20),
    xaxis=dict(gridcolor="#21262d", linecolor="#30363d", zerolinecolor="#30363d"),
    yaxis=dict(gridcolor="#21262d", linecolor="#30363d", zerolinecolor="#30363d"),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#21262d", borderwidth=1),
)

_C_BLUE   = "#58a6ff"
_C_RED    = "#f85149"
_C_GREEN  = "#3fb950"
_C_AMBER  = "#d29922"
_C_PURPLE = "#bc8cff"


def _mc(label: str, value: str, sub: str = "", sub_cls: str = "") -> str:
    sub_html = f'<div class="mc-sub {sub_cls}">{sub}</div>' if sub else ""
    return f'<div class="mc"><div class="mc-lbl">{label}</div><div class="mc-val">{value}</div>{sub_html}</div>'


def _sh(text: str) -> None:
    st.markdown(f'<div class="sh">{text}</div>', unsafe_allow_html=True)


def _curve_to_arrays(curve: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    items = sorted(
        [(y, v) for k, v in curve.items() if (y := _MATURITY_YEARS.get(k))],
    )
    return np.array([m for m, _ in items]), np.array([r for _, r in items])


def _interp_yield_at(curve: dict[str, float], mat_yrs: float) -> float:
    mats, ylds = _curve_to_arrays(curve)
    return float(np.interp(mat_yrs, mats, ylds))


@st.cache_data(ttl=300)
def _fetch_and_fit() -> tuple[dict[str, float], NelsonSiegelParams | None, str]:
    """Fetch FRED, fit NS, return (curve, params, source_label)."""
    try:
        curve = get_yield_curve()
        if not curve:
            raise ValueError("empty FRED response")
        mats, ylds = _curve_to_arrays(curve)
        params = fit_nelson_siegel(mats, ylds)
        return curve, params, "FRED (live)"
    except Exception as exc:
        try:
            mats, ylds = _curve_to_arrays(_FALLBACK_CURVE)
            params = fit_nelson_siegel(mats, ylds)
        except Exception:
            params = None
        return _FALLBACK_CURVE, params, f"Fallback ({exc})"


# ── Live data + NS fit ───────────────────────────────────────────────────────

curve, ns_params, data_source = _fetch_and_fit()
mats_arr, ylds_arr = _curve_to_arrays(curve)

spot_curve: SpotCurve | None = None
if ns_params is not None:
    try:
        spot_curve = SpotCurve.from_nelson_siegel(ns_params)
    except Exception:
        pass

try:
    spreads = curve_spreads(curve)
except KeyError:
    spreads = {}

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "## FI Risk Dashboard",
        help="Fixed Income analytics for US Treasuries and cash-futures basis.",
    )
    st.caption(f"Data: {data_source}")

    st.markdown("**Bond parameters**")
    face_value    = st.number_input("Face Value ($)",      value=1_000.0, step=100.0,  format="%.0f")
    coupon_rate   = st.number_input("Coupon Rate (%)",     value=4.50,    step=0.25,   format="%.2f") / 100
    ytm           = st.number_input("YTM (%)",             value=4.00,    step=0.05,   format="%.3f") / 100
    yrs_to_mat    = st.number_input("Years to Maturity",   value=10,      min_value=1, max_value=50,  step=1)
    frequency     = st.selectbox(
        "Payment Frequency",
        [1, 2, 4],
        index=1,
        format_func=lambda f: {1: "Annual", 2: "Semi-annual", 4: "Quarterly"}[f],
    )

    st.markdown("**Market inputs**")
    repo_rate = st.number_input("Repo Rate (%)", value=4.30, step=0.05, format="%.2f") / 100
    shift_bps = st.slider("Scenario Shift (bps)", min_value=-200, max_value=200, value=50, step=5)

# ── Pre-compute bond metrics ─────────────────────────────────────────────────
_price   = price_bond(face_value, coupon_rate, yrs_to_mat, ytm, frequency)
_dur     = modified_duration(face_value, coupon_rate, yrs_to_mat, ytm, frequency)
_dv01    = dv01(face_value, coupon_rate, yrs_to_mat, ytm, frequency)
_cvx     = convexity(face_value, coupon_rate, yrs_to_mat, ytm, frequency)

# ── Page header ──────────────────────────────────────────────────────────────
st.markdown("""
<div style="padding:0.5rem 0 1rem;">
  <div style="color:#e6edf3;font-size:1.4rem;font-weight:700;letter-spacing:0.02em;">
    Fixed Income Risk Dashboard
  </div>
  <div style="color:#8b949e;font-size:0.75rem;letter-spacing:0.05em;margin-top:0.2rem;">
    Nelson-Siegel · Carry & Roll · Z-Spread · Cash-Futures Basis
  </div>
</div>
""", unsafe_allow_html=True)

# Headline spreads bar
if spreads:
    s2s10  = spreads.get("2s10s_bps", 0)
    s5s30  = spreads.get("5s30s_bps", 0)
    fly    = spreads.get("2s5s10s_fly_bps", 0)
    s_cls  = "pos" if s2s10 > 0 else "neg"
    st.markdown(
        f'<div class="banner">'
        f'<b>Live curve</b> &nbsp;·&nbsp; '
        f'2s10s: <span class="{s_cls}"><b>{s2s10:+.1f}bps</b></span> &nbsp;|&nbsp; '
        f'5s30s: <span class="pos"><b>{s5s30:+.1f}bps</b></span> &nbsp;|&nbsp; '
        f'2s5s10s fly: <b>{fly:+.1f}bps</b>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ── Tabs ─────────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "01 · Yield Curve",
    "02 · Risk Metrics",
    "03 · Carry & Roll",
    "04 · Scenarios",
    "05 · Z-Spread",
    "06 · Basis",
])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — YIELD CURVE
# ════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    col_chart, col_info = st.columns([3, 1], gap="large")

    with col_chart:
        _sh("Nelson-Siegel Fit · US Treasury Spot Curve")

        tau_dense = np.linspace(0.1, 30.0, 300)
        fig_curve = go.Figure()

        if ns_params is not None:
            ns_rates = nelson_siegel_rate(
                tau_dense,
                ns_params.beta0, ns_params.beta1,
                ns_params.beta2, ns_params.lambda_,
            )
            fig_curve.add_trace(go.Scatter(
                x=tau_dense, y=ns_rates * 100,
                mode="lines",
                name="NS Fitted",
                line=dict(color=_C_BLUE, width=2.5),
            ))

        fig_curve.add_trace(go.Scatter(
            x=mats_arr, y=ylds_arr * 100,
            mode="markers+text",
            name="FRED Obs.",
            marker=dict(color=_C_AMBER, size=9, symbol="circle",
                        line=dict(color="#0d1117", width=1.5)),
            text=[f"  {k}" for k in curve],
            textposition="top right",
            textfont=dict(size=10, color="#8b949e"),
        ))

        if spot_curve is not None:
            spot_rates = spot_curve.rate(tau_dense)
            fig_curve.add_trace(go.Scatter(
                x=tau_dense, y=spot_rates * 100,
                mode="lines",
                name="Spot (bootstrapped)",
                line=dict(color=_C_GREEN, width=1.5, dash="dot"),
                opacity=0.7,
            ))

        fig_curve.update_layout(
            **_PLOTLY_BASE,
            height=340,
            xaxis=dict(**_PLOTLY_BASE["xaxis"], title="Maturity (years)"),
            yaxis=dict(**_PLOTLY_BASE["yaxis"], title="Yield (%)"),
        )
        st.plotly_chart(fig_curve, use_container_width=True)

    with col_info:
        _sh("NS Parameters")
        if ns_params is not None:
            β0_s = f"{ns_params.beta0*100:+.3f}%"
            β1_s = f"{ns_params.beta1*100:+.3f}%"
            β2_s = f"{ns_params.beta2*100:+.3f}%"
            λ_s  = f"{ns_params.lambda_:.2f}yr"
            rmse = f"{ns_params.fit_rmse_bps:.2f}bps"
            rmse_cls = "pos" if ns_params.fit_rmse_bps < 2 else "neu"
            st.markdown(
                f'<div class="ns-row">'
                f'<div class="ns-b"><span>β₀</span> {β0_s}</div>'
                f'<div class="ns-b"><span>β₁</span> {β1_s}</div>'
                f'<div class="ns-b"><span>β₂</span> {β2_s}</div>'
                f'<div class="ns-b"><span>λ</span> {λ_s}</div>'
                f'<div class="ns-b"><span class="{rmse_cls}">RMSE</span> {rmse}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "β₀ = long-run level · β₁ = slope · β₂ = curvature · "
                "λ = decay speed. RMSE < 2bps = excellent fit."
            )
        else:
            st.warning("NS fit unavailable.")

        _sh("Curve Spreads")
        if spreads:
            s2s10 = spreads["2s10s_bps"]
            s5s30 = spreads["5s30s_bps"]
            fly   = spreads["2s5s10s_fly_bps"]
            col_a, col_b = st.columns(2)
            col_a.markdown(_mc("2s10s", f"{s2s10:+.1f}", "bps", "pos" if s2s10 > 0 else "neg"), unsafe_allow_html=True)
            col_b.markdown(_mc("5s30s", f"{s5s30:+.1f}", "bps", "pos" if s5s30 > 0 else "neg"), unsafe_allow_html=True)
            st.markdown(_mc("2s5s10s Fly", f"{fly:+.1f}", "bps — belly vs wings"), unsafe_allow_html=True)

        _sh("Tenors")
        rows = "".join(
            f"<tr><td>{k}</td><td>{v*100:.3f}%</td></tr>"
            for k, v in curve.items()
        )
        st.markdown(
            f'<table class="fi-table"><thead>'
            f'<tr><th>Tenor</th><th>Yield</th></tr>'
            f'</thead><tbody>{rows}</tbody></table>',
            unsafe_allow_html=True,
        )

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — RISK METRICS
# ════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    _sh("Bond Risk Summary")

    col1, col2, col3, col4 = st.columns(4)
    clean_pct = (_price / face_value) * 100
    col1.markdown(
        _mc("Clean Price", f"${_price:,.2f}", f"{clean_pct:.3f}% of par"),
        unsafe_allow_html=True,
    )
    col2.markdown(
        _mc("Mod. Duration", f"{_dur:.3f}", "years"),
        unsafe_allow_html=True,
    )
    col3.markdown(
        _mc("DV01", f"${_dv01:.2f}", "per $1M / 1bp" if face_value <= 1000 else ""),
        unsafe_allow_html=True,
    )
    col4.markdown(
        _mc("Convexity", f"{_cvx:.2f}", "yr²"),
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        _sh("Price / Yield Relationship (Convexity Curve)")
        ytm_grid = np.linspace(max(0.001, ytm - 0.03), ytm + 0.03, 150)
        prices = [price_bond(face_value, coupon_rate, yrs_to_mat, y, frequency) for y in ytm_grid]
        dur_approx = [_price - _dur * (y - ytm) * _price for y in ytm_grid]

        fig_py = go.Figure()
        fig_py.add_trace(go.Scatter(
            x=ytm_grid * 100, y=prices,
            mode="lines", name="Actual Price",
            line=dict(color=_C_BLUE, width=2.5),
        ))
        fig_py.add_trace(go.Scatter(
            x=ytm_grid * 100, y=dur_approx,
            mode="lines", name="Duration Approx",
            line=dict(color=_C_RED, width=1.5, dash="dash"),
        ))
        fig_py.add_vline(
            x=ytm * 100,
            line=dict(color=_C_AMBER, width=1, dash="dot"),
            annotation_text="current YTM",
            annotation_font=dict(color=_C_AMBER, size=10),
        )
        fig_py.update_layout(
            **_PLOTLY_BASE,
            height=310,
            xaxis=dict(**_PLOTLY_BASE["xaxis"], title="YTM (%)"),
            yaxis=dict(**_PLOTLY_BASE["yaxis"], title="Price ($)"),
        )
        st.plotly_chart(fig_py, use_container_width=True)
        st.caption(
            "Convexity causes the actual price curve to bow above the duration "
            "linear approximation — the bond gains more than duration predicts "
            "when yields fall, and loses less when yields rise."
        )

    with col_right:
        _sh("Rate Sensitivity (parallel shift)")
        shifts   = [-200, -100, -50, -25, 0, 25, 50, 100, 200]
        rows_tab = ""
        for s in shifts:
            new_y     = ytm + s / 10_000
            new_p     = price_bond(face_value, coupon_rate, yrs_to_mat, new_y, frequency)
            chg       = new_p - _price
            chg_pct   = chg / _price * 100
            clr       = "pos" if chg > 0 else ("neg" if chg < 0 else "")
            rows_tab += (
                f'<tr><td>{s:+d}bps</td>'
                f'<td>${new_p:,.2f}</td>'
                f'<td class="{clr}">{chg:+,.2f}</td>'
                f'<td class="{clr}">{chg_pct:+.2f}%</td></tr>'
            )
        st.markdown(
            f'<table class="fi-table"><thead>'
            f'<tr><th>Shift</th><th>Price</th><th>Δ$</th><th>Δ%</th></tr>'
            f'</thead><tbody>{rows_tab}</tbody></table>',
            unsafe_allow_html=True,
        )

# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — CARRY & ROLL
# ════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    if spot_curve is None:
        st.warning("Spot curve unavailable — carry & roll requires NS fit.")
    else:
        try:
            bond_obj = Bond(
                face_value=face_value,
                coupon_rate=coupon_rate,
                years_to_maturity=float(yrs_to_mat),
                ytm=ytm,
                frequency=frequency,
            )
            _sh("Carry + Roll-Down Decomposition (static curve assumption)")
            st.caption(
                "Assumes the Treasury spot curve is **completely unchanged** over the "
                "holding period. Carry = coupon accrual − repo financing. Roll-down = "
                "price appreciation from sliding to a shorter maturity on a steep curve."
            )

            horizons = [("3M", HOLD_3M), ("6M", HOLD_6M), ("1Y", HOLD_1Y)]
            valid_rds = []
            for label, hp in horizons:
                if hp < bond_obj.years_to_maturity:
                    rd = roll_down_return(bond_obj, spot_curve, hp)
                    financing = repo_rate * hp * 100.0
                    net_carry = rd.coupon_accrual_pct - financing
                    valid_rds.append((label, hp, rd, net_carry))

            # ── Waterfall charts ────────────────────────────────────────────
            n_cols = len(valid_rds)
            wf_cols = st.columns(n_cols, gap="medium")

            for col, (label, hp, rd, net_carry) in zip(wf_cols, valid_rds):
                total = net_carry + rd.roll_down_pct
                fig_wf = go.Figure(go.Waterfall(
                    orientation="v",
                    measure=["relative", "relative", "total"],
                    x=["Net Carry", "Roll-Down", "Total"],
                    y=[net_carry, rd.roll_down_pct, 0],
                    text=[f"{net_carry:+.3f}%", f"{rd.roll_down_pct:+.3f}%", f"{total:+.3f}%"],
                    textposition="outside",
                    textfont=dict(size=10, color="#e6edf3"),
                    connector=dict(line=dict(color="#30363d", width=1)),
                    increasing=dict(marker=dict(color=_C_GREEN, line=dict(color=_C_GREEN, width=0))),
                    decreasing=dict(marker=dict(color=_C_RED,   line=dict(color=_C_RED,   width=0))),
                    totals=dict(   marker=dict(color=_C_BLUE,   line=dict(color=_C_BLUE,  width=0))),
                ))
                fig_wf.update_layout(
                    **_PLOTLY_BASE,
                    height=300,
                    title=dict(text=f"{label} Horizon", font=dict(color="#e6edf3", size=12), x=0.5),
                    showlegend=False,
                    yaxis=dict(**_PLOTLY_BASE["yaxis"], title="Return (%)"),
                )
                col.plotly_chart(fig_wf, use_container_width=True)

            # ── Summary table ───────────────────────────────────────────────
            _sh("Return Summary")
            header = "<tr><th>Metric</th>" + "".join(f"<th>{l}</th>" for l, *_ in valid_rds) + "</tr>"
            rows_data = [
                ("Coupon Accrual (%)", "rd.coupon_accrual_pct"),
                ("Financing Cost (%)", None),
                ("Net Carry (%)",      None),
                ("Roll-Down (%)",      "rd.roll_down_pct"),
                ("Total C+R (%)",      None),
                ("Fwd Breakeven YTM", "rd.forward_breakeven_ytm"),
            ]

            def _row(lbl: str, values: list[str]) -> str:
                cells = "".join(f"<td>{v}</td>" for v in values)
                return f"<tr><td>{lbl}</td>{cells}</tr>"

            financing_vals = [f"{repo_rate * hp * 100:.3f}%" for _, hp, *_ in valid_rds]
            net_carry_vals = [f"{net_carry:+.3f}%"          for _, _, _, net_carry in valid_rds]
            total_vals     = [f"{(net_carry + rd.roll_down_pct):+.3f}%" for _, _, rd, net_carry in valid_rds]
            breakeven_vals = [f"{rd.forward_breakeven_ytm*100:.3f}%"    for _, _, rd, _ in valid_rds]
            coupon_vals    = [f"{rd.coupon_accrual_pct:.3f}%"            for _, _, rd, _ in valid_rds]
            roll_vals      = [f"{rd.roll_down_pct:+.3f}%"                for _, _, rd, _ in valid_rds]

            table_rows = (
                _row("Coupon Accrual",      coupon_vals)
                + _row("Financing Cost",    financing_vals)
                + _row("Net Carry",         net_carry_vals)
                + _row("Roll-Down",         roll_vals)
                + _row("Total (C+R)",       total_vals)
                + _row("Fwd Breakeven YTM", breakeven_vals)
            )
            st.markdown(
                f'<table class="fi-table"><thead>{header}</thead>'
                f'<tbody>{table_rows}</tbody></table>',
                unsafe_allow_html=True,
            )

            # ── Total return decomposition for 3M ──────────────────────────
            _sh("Total Return Decomposition · 3M Horizon")
            st.caption(
                "Decomposes the position P&L into four independently hedgeable components. "
                "Carry/roll hedged via repo. Duration P&L hedged via futures DV01 overlay. "
                "Convexity hedged via options."
            )
            dy_bps = st.slider("Assumed yield change for P&L attribution (bps)", -200, 200, 0, 5)
            dy = dy_bps / 10_000

            if HOLD_3M < bond_obj.years_to_maturity:
                trd = total_return_decomposition(
                    bond_obj, spot_curve, repo_rate,
                    holding_period_yrs=HOLD_3M,
                    yield_change=dy,
                )
                cats = ["Carry", "Roll-Down", "Duration P&L", "Convexity", "Total"]
                vals = [
                    trd.carry_pct, trd.roll_down_pct,
                    trd.duration_pnl_pct, trd.convexity_pnl_pct, trd.total_pct,
                ]
                colors = [
                    _C_GREEN if v >= 0 else _C_RED for v in vals[:-1]
                ] + [_C_BLUE]

                fig_trd = go.Figure(go.Bar(
                    x=cats, y=vals,
                    marker_color=colors,
                    text=[f"{v:+.3f}%" for v in vals],
                    textposition="outside",
                    textfont=dict(size=10, color="#e6edf3"),
                ))
                fig_trd.add_hline(y=0, line=dict(color="#30363d", width=1))
                fig_trd.update_layout(
                    **_PLOTLY_BASE,
                    height=270,
                    showlegend=False,
                    yaxis=dict(**_PLOTLY_BASE["yaxis"], title="Return (%)"),
                )
                st.plotly_chart(fig_trd, use_container_width=True)

        except Exception as exc:
            st.error(f"Carry/roll computation failed: {exc}")

# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — SCENARIOS
# ════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    _sh("Yield Curve Scenarios")

    _SCENARIOS: dict[str, tuple] = {
        "Parallel Shift":  (parallel_shift,  "All tenors shift equally by ±shift_bps."),
        "Bear Steepening": (bear_steepening,  "Long end rises; short end unchanged. Typical of supply-driven sell-off."),
        "Bear Flattening": (bear_flattening,  "Short end rises; long end anchored. Classic Fed hiking regime."),
        "Bull Steepening": (bull_steepening,  "Short end falls; long end anchored. Fed signals cuts while long-end sticky."),
        "Bull Flattening": (bull_flattening,  "Long end falls; short end anchored. Flight to quality / disinflation."),
    }

    col_sel, col_desc = st.columns([1, 2])
    with col_sel:
        scenario_name = st.selectbox("Scenario", list(_SCENARIOS.keys()), label_visibility="collapsed")
    with col_desc:
        st.caption(_SCENARIOS[scenario_name][1])

    scenario_fn = _SCENARIOS[scenario_name][0]
    shocked = scenario_fn(curve, shift_bps)

    # ── Overlay chart ───────────────────────────────────────────────────────
    s_mats, s_ylds = _curve_to_arrays(shocked)
    fig_sc = go.Figure()
    fig_sc.add_trace(go.Scatter(
        x=mats_arr, y=ylds_arr * 100,
        mode="lines+markers", name="Current",
        line=dict(color=_C_BLUE, width=2),
        marker=dict(size=6, color=_C_BLUE),
    ))
    fig_sc.add_trace(go.Scatter(
        x=s_mats, y=s_ylds * 100,
        mode="lines+markers", name=f"Shocked ({shift_bps:+d}bps)",
        line=dict(color=_C_RED, width=2, dash="dash"),
        marker=dict(size=6, color=_C_RED, symbol="diamond"),
    ))
    if ns_params is not None:
        ns_dense = nelson_siegel_rate(
            tau_dense, ns_params.beta0, ns_params.beta1, ns_params.beta2, ns_params.lambda_
        )
        fig_sc.add_trace(go.Scatter(
            x=tau_dense, y=ns_dense * 100,
            mode="lines", name="NS Baseline",
            line=dict(color=_C_BLUE, width=1, dash="dot"),
            opacity=0.4,
        ))
    fig_sc.update_layout(
        **_PLOTLY_BASE,
        height=310,
        xaxis=dict(**_PLOTLY_BASE["xaxis"], title="Maturity (years)"),
        yaxis=dict(**_PLOTLY_BASE["yaxis"], title="Yield (%)"),
    )
    st.plotly_chart(fig_sc, use_container_width=True)

    # ── Per-tenor change table ──────────────────────────────────────────────
    col_tab, col_bond = st.columns([2, 1], gap="large")

    with col_tab:
        _sh("Per-Tenor Impact")
        rows_sc = ""
        for tenor, orig_y in curve.items():
            shocked_y = shocked.get(tenor, orig_y)
            delta     = (shocked_y - orig_y) * 10_000
            clr       = "neg" if delta > 0 else ("pos" if delta < 0 else "")
            rows_sc  += (
                f'<tr><td>{tenor}</td>'
                f'<td>{orig_y*100:.3f}%</td>'
                f'<td>{shocked_y*100:.3f}%</td>'
                f'<td class="{clr}">{delta:+.1f}bps</td></tr>'
            )
        st.markdown(
            f'<table class="fi-table"><thead>'
            f'<tr><th>Tenor</th><th>Base</th><th>Shocked</th><th>Δ</th></tr>'
            f'</thead><tbody>{rows_sc}</tbody></table>',
            unsafe_allow_html=True,
        )

    with col_bond:
        _sh("Bond P&L")
        shocked_yield = _interp_yield_at(shocked, float(yrs_to_mat))
        new_price     = price_bond(face_value, coupon_rate, yrs_to_mat, shocked_yield, frequency)
        price_chg     = new_price - _price
        price_chg_pct = price_chg / _price * 100
        dy_act        = shocked_yield - ytm
        dur_est       = -_dur * dy_act * _price
        cvx_cor       = 0.5 * _cvx * dy_act ** 2 * _price

        st.markdown(
            _mc("Shocked Yield", f"{shocked_yield*100:.3f}%",
                f"{dy_act*10000:+.1f}bps vs input YTM",
                "neg" if dy_act > 0 else "pos"),
            unsafe_allow_html=True,
        )
        st.markdown(
            _mc("New Price", f"${new_price:,.2f}",
                f"{price_chg:+,.2f} ({price_chg_pct:+.2f}%)",
                "pos" if price_chg > 0 else "neg"),
            unsafe_allow_html=True,
        )
        st.markdown(
            _mc("Duration P&L", f"${dur_est:+,.2f}", "linear approx"),
            unsafe_allow_html=True,
        )
        st.markdown(
            _mc("Convexity P&L", f"${cvx_cor:+,.2f}", "second-order correction"),
            unsafe_allow_html=True,
        )

    # ── All-scenarios comparison ────────────────────────────────────────────
    _sh("All Scenarios · Bond P&L Summary")
    rows_all = ""
    for sc_name, (sc_fn, _) in _SCENARIOS.items():
        sh_c  = sc_fn(curve, shift_bps)
        sh_y  = _interp_yield_at(sh_c, float(yrs_to_mat))
        sh_p  = price_bond(face_value, coupon_rate, yrs_to_mat, sh_y, frequency)
        p_chg = sh_p - _price
        p_pct = p_chg / _price * 100
        clr   = "pos" if p_chg > 0 else "neg"
        rows_all += (
            f'<tr><td>{sc_name}</td>'
            f'<td>{sh_y*100:.3f}%</td>'
            f'<td class="{clr}">${p_chg:+,.2f}</td>'
            f'<td class="{clr}">{p_pct:+.2f}%</td></tr>'
        )
    st.markdown(
        f'<table class="fi-table"><thead>'
        f'<tr><th>Scenario ({shift_bps:+d}bps)</th>'
        f'<th>Shocked Yield</th><th>ΔPrice</th><th>ΔPrice%</th></tr>'
        f'</thead><tbody>{rows_all}</tbody></table>',
        unsafe_allow_html=True,
    )

# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — Z-SPREAD
# ════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    if spot_curve is None:
        st.warning("Z-spread requires the Nelson-Siegel spot curve fit. FRED data unavailable.")
    else:
        _sh("Z-Spread vs Treasury Spot Curve")
        st.caption(
            "Z-spread = constant spread over the **full** spot curve that equates the bond's "
            "present value to its market price. Unlike the yield spread (YTM − benchmark), the "
            "Z-spread accounts for the curve shape at every cash flow date. "
            "Computed on a continuous compounding basis consistent with the SpotCurve convention."
        )

        col_zl, col_zr = st.columns([2, 1], gap="large")

        with col_zr:
            _sh("Inputs")
            custom_dp = st.number_input(
                "Dirty Price (optional — leave 0 to use bond YTM price)",
                value=0.0, step=0.01, format="%.4f",
                help="Enter the observed invoice price. If 0, uses the price implied by input YTM.",
            )

        with col_zl:
            try:
                bond_obj_z = Bond(
                    face_value=face_value,
                    coupon_rate=coupon_rate,
                    years_to_maturity=float(yrs_to_mat),
                    ytm=ytm,
                    frequency=frequency,
                )
                dp = (
                    custom_dp
                    if custom_dp > 0
                    else price_bond(face_value, coupon_rate, yrs_to_mat, ytm, frequency)
                )
                zs = compute_z_spread(bond_obj_z, dp, spot_curve)
                tsy_spot = spot_curve.rate(float(yrs_to_mat))
                yld_spread = ytm - tsy_spot

                c1, c2, c3 = st.columns(3)
                zs_cls = "pos" if zs > 0.0005 else ("neg" if zs < -0.0005 else "neu")
                c1.markdown(_mc("Z-Spread", f"{zs*10000:+.1f}", "bps", zs_cls), unsafe_allow_html=True)
                c2.markdown(_mc("Yield Spread", f"{yld_spread*10000:+.1f}", "bps (YTM − Tsy spot)"), unsafe_allow_html=True)
                c3.markdown(_mc("Treasury Spot", f"{tsy_spot*100:.3f}%", f"at {yrs_to_mat}Y"), unsafe_allow_html=True)

                # ── Spot curve + bond yield chart ───────────────────────────
                _sh("Spot Curve vs Bond Yield")
                spot_on_grid = spot_curve.rate(tau_dense)

                fig_zs = go.Figure()
                fig_zs.add_trace(go.Scatter(
                    x=tau_dense, y=spot_on_grid * 100,
                    mode="lines", name="Treasury Spot Curve",
                    line=dict(color=_C_BLUE, width=2),
                ))
                # Z-spread adjusted curve
                fig_zs.add_trace(go.Scatter(
                    x=tau_dense, y=(spot_on_grid + zs) * 100,
                    mode="lines", name=f"Spot + Z-spread ({zs*10000:+.1f}bps)",
                    line=dict(color=_C_GREEN, width=1.5, dash="dash"),
                ))
                # Bond YTM flat line
                fig_zs.add_hline(
                    y=ytm * 100,
                    line=dict(color=_C_AMBER, width=1.5, dash="dot"),
                    annotation_text=f"Bond YTM {ytm*100:.3f}%",
                    annotation_font=dict(color=_C_AMBER, size=10),
                )
                # Mark bond maturity
                fig_zs.add_vline(
                    x=float(yrs_to_mat),
                    line=dict(color="#30363d", width=1),
                    annotation_text=f"  {yrs_to_mat}Y",
                    annotation_font=dict(color="#8b949e", size=10),
                )
                fig_zs.update_layout(
                    **_PLOTLY_BASE,
                    height=300,
                    xaxis=dict(**_PLOTLY_BASE["xaxis"], title="Maturity (years)"),
                    yaxis=dict(**_PLOTLY_BASE["yaxis"], title="Rate (%)"),
                )
                st.plotly_chart(fig_zs, use_container_width=True)

            except Exception as exc:
                st.error(f"Z-spread computation failed: {exc}")

        with col_zr:
            _sh("Interpretation")
            if spot_curve is not None:
                try:
                    interp_txt = (
                        f"**Z-spread: {zs*10000:+.1f}bps**\n\n"
                        + (
                            "Bond is **cheap** vs Treasuries — offers excess yield "
                            "over the risk-free spot curve. Likely reflects a credit, "
                            "liquidity, or off-the-run premium."
                            if zs > 0.0005
                            else (
                                "Bond is **rich** vs Treasuries — yields less than "
                                "the equivalent Treasury. Typical of on-the-run "
                                "benchmark bonds or bonds with special repo status."
                                if zs < -0.0005
                                else "Bond trades approximately **at** the Treasury spot curve."
                            )
                        )
                    )
                    st.markdown(interp_txt)
                    st.caption(
                        "Cash flows discounted at continuous spot rate + z-spread: "
                        "P = Σ CF·exp(−(z(t)+s)·t). "
                        "Solved via Brent's method on [−500bps, +5000bps]."
                    )
                except Exception:
                    pass

# ════════════════════════════════════════════════════════════════════════════
# TAB 6 — CASH-FUTURES BASIS
# ════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    _sh("Cash-Futures Basis · US Treasury Futures")
    st.caption(
        "ACT/365 for coupon accrual · ACT/360 for repo financing (ICMA convention). "
        "Gross basis = cash − (futures × CF). Net basis = gross basis − carry. "
        "Implied repo is the rate locked in by buying cash and selling futures."
    )

    col_b1, col_b2, col_b3 = st.columns(3)
    cash_p     = col_b1.number_input("Cash Price (% of par)", value=98.50, step=0.01, format="%.3f")
    futures_p  = col_b2.number_input("Futures Price (% of par)", value=97.00, step=0.01, format="%.3f")
    cf         = col_b3.number_input("Conversion Factor", value=0.9750, step=0.0001, format="%.4f")

    col_b4, col_b5, col_b6 = st.columns(3)
    repo_r     = col_b4.number_input("Repo Rate (%)", value=4.30, step=0.05, format="%.2f") / 100
    days       = int(col_b5.number_input("Days to Delivery", value=90, min_value=1, max_value=365, step=1))
    bond_cpn   = col_b6.number_input(
        "Deliverable Coupon (%)",
        value=coupon_rate * 100,
        step=0.25, format="%.3f",
    ) / 100

    gb = gross_basis(cash_p, futures_p, cf)
    nb = net_basis(cash_p, futures_p, cf, bond_cpn, repo_r, days)
    ir = implied_repo(cash_p, futures_p, cf, bond_cpn, days)

    _sh("Basis Metrics")
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.markdown(_mc("Gross Basis", f"{gb:.4f}", "price points"), unsafe_allow_html=True)
    col_m2.markdown(_mc("Net Basis",   f"{nb:.4f}", "price points"), unsafe_allow_html=True)

    ir_cls = "pos" if ir > repo_r else "neg"
    col_m3.markdown(
        _mc("Implied Repo", f"{ir*100:.3f}%", f"Market repo: {repo_r*100:.3f}%", ir_cls),
        unsafe_allow_html=True,
    )
    col_m4.markdown(
        _mc("Carry Signal",
            "Attractive" if ir > repo_r else "Unattractive",
            "implied repo > market repo" if ir > repo_r else "implied repo ≤ market repo",
            "pos" if ir > repo_r else "neg"),
        unsafe_allow_html=True,
    )

    # ── Basis explanation ───────────────────────────────────────────────────
    _sh("Economics")
    basis_diff = ir - repo_r
    st.markdown(
        f'<div class="banner">'
        + (
            f"Implied repo ({ir*100:.3f}%) exceeds the market repo rate ({repo_r*100:.3f}%) "
            f"by <b>{basis_diff*100:.1f}bps</b>. Buying the cash bond and selling futures is "
            f"equivalent to lending at {ir*100:.3f}% — above the prevailing repo rate. "
            f"The basis trade captures this spread ({basis_diff*10000:.1f}bps) as risk-free arbitrage "
            f"(subject to delivery option value and margin costs)."
            if ir > repo_r
            else
            f"Implied repo ({ir*100:.3f}%) is below the market repo rate ({repo_r*100:.3f}%) "
            f"by <b>{abs(basis_diff)*100:.1f}bps</b>. The reverse basis (selling cash, buying futures) "
            f"may be more attractive, or the negative basis reflects delivery option value embedded in the futures price."
        )
        + '</div>',
        unsafe_allow_html=True,
    )

    # ── Sensitivity to repo rate ────────────────────────────────────────────
    _sh("Implied Repo vs Market Repo — Sensitivity")
    repo_grid   = np.linspace(max(0, ir - 0.02), ir + 0.02, 80)
    nb_grid     = [net_basis(cash_p, futures_p, cf, bond_cpn, r, days) for r in repo_grid]

    fig_basis = go.Figure()
    fig_basis.add_trace(go.Scatter(
        x=repo_grid * 100, y=nb_grid,
        mode="lines", name="Net Basis",
        line=dict(color=_C_BLUE, width=2),
    ))
    fig_basis.add_hline(y=0, line=dict(color="#30363d", width=1))
    fig_basis.add_vline(
        x=repo_r * 100,
        line=dict(color=_C_AMBER, width=1.5, dash="dot"),
        annotation_text=f"  Market repo {repo_r*100:.2f}%",
        annotation_font=dict(color=_C_AMBER, size=10),
    )
    fig_basis.add_vline(
        x=ir * 100,
        line=dict(color=_C_GREEN, width=1.5, dash="dot"),
        annotation_text=f"  Implied repo {ir*100:.3f}%",
        annotation_font=dict(color=_C_GREEN, size=10),
    )
    fig_basis.update_layout(
        **_PLOTLY_BASE,
        height=260,
        xaxis=dict(**_PLOTLY_BASE["xaxis"], title="Repo Rate (%)"),
        yaxis=dict(**_PLOTLY_BASE["yaxis"], title="Net Basis (pts)"),
    )
    st.plotly_chart(fig_basis, use_container_width=True)
    st.caption(
        "Net basis crosses zero at the implied repo rate. Above implied repo: "
        "basis trade is unattractive. Below: buying cash / selling futures earns positive carry."
    )
