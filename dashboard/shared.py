"""Shared CSS, helpers, colors, and sidebar for the CTD Basis Monitor."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

# ── Constants ──────────────────────────────────────────────────────────────────

CONTRACT = "TYM26"

C_BLUE   = "#58a6ff"
C_RED    = "#f85149"
C_GREEN  = "#3fb950"
C_AMBER  = "#d29922"
C_PURPLE = "#bc8cff"

PLOTLY_BASE: dict = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(8,12,20,0.8)",
    font=dict(family="'Inter', 'Segoe UI', sans-serif", color="#6e7681", size=11),
    margin=dict(t=28, b=44, l=56, r=20),
    xaxis=dict(gridcolor="#1e2535", linecolor="#1e2535", zerolinecolor="#1e2535"),
    yaxis=dict(gridcolor="#1e2535", linecolor="#1e2535", zerolinecolor="#1e2535"),
    legend=dict(
        bgcolor="rgba(8,12,20,0.9)",
        bordercolor="#1e2535",
        borderwidth=1,
        font=dict(size=10),
    ),
)

# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Reset & base ── */
*, *::before, *::after { box-sizing: border-box; }
html, body, [class*="css"] {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
}
.stApp { background: #080c14; color: #e6edf3; }
#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding-top: 1.8rem !important;
    padding-bottom: 3rem !important;
    max-width: 1380px !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #050810;
    border-right: 1px solid #111827;
}
[data-testid="stSidebar"] .stMarkdown p {
    color: #374151;
    font-size: 0.6rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-weight: 700;
    margin: 1.3rem 0 0.4rem;
}
[data-testid="stSidebar"] .stNumberInput input {
    background: #0d1425;
    border: 1px solid #1e2535;
    border-radius: 6px;
    color: #c9d1d9;
    font-family: "Courier New", monospace;
    font-size: 0.83rem;
}
[data-testid="stSidebar"] .stNumberInput input:focus {
    border-color: #58a6ff;
    box-shadow: 0 0 0 3px rgba(88,166,255,0.12);
    outline: none;
}
[data-testid="stSidebar"] hr { border-color: #111827; }
[data-testid="stSidebar"] .stCaption { color: #374151 !important; font-size: 0.65rem !important; }

/* ── Page header ── */
.page-header {
    padding: 0.2rem 0 1.3rem;
    border-bottom: 1px solid #111827;
    margin-bottom: 1.5rem;
}
.page-header-eyebrow {
    font-size: 0.58rem;
    font-weight: 700;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #58a6ff;
    margin-bottom: 0.25rem;
}
.page-header-title {
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: #e6edf3;
    line-height: 1.15;
}
.page-header-sub {
    font-size: 0.73rem;
    color: #374151;
    margin-top: 0.3rem;
    font-weight: 400;
}

/* ── Live badge ── */
.live-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: rgba(63,185,80,0.08);
    border: 1px solid rgba(63,185,80,0.2);
    border-radius: 20px;
    padding: 3px 10px 3px 7px;
    font-size: 0.58rem;
    font-weight: 700;
    color: #3fb950;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}
.live-dot {
    width: 6px; height: 6px;
    background: #3fb950;
    border-radius: 50%;
    animation: livepulse 2.2s ease-in-out infinite;
    flex-shrink: 0;
}
@keyframes livepulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.3; }
}

/* ── KPI cards ── */
.kpi-card {
    background: linear-gradient(150deg, #0d1425 0%, #080c14 100%);
    border: 1px solid #111827;
    border-radius: 10px;
    padding: 1.1rem 1.3rem 1rem;
    position: relative;
    overflow: hidden;
    height: 100%;
    transition: border-color 0.25s, transform 0.2s, box-shadow 0.25s;
}
.kpi-card:hover {
    border-color: #1e3a5f;
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.45);
}
.kpi-accent {
    position: absolute;
    top: 0; left: 0; right: 0; height: 2px;
    background: var(--accent, linear-gradient(90deg, transparent, #58a6ff 50%, transparent));
}
.kpi-lbl {
    font-size: 0.57rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #374151;
    margin-bottom: 0.45rem;
}
.kpi-val {
    font-size: 1.7rem;
    font-weight: 700;
    font-family: "Courier New", monospace;
    color: #e6edf3;
    line-height: 1.05;
    letter-spacing: -0.02em;
}
.kpi-sub {
    font-size: 0.64rem;
    color: #374151;
    margin-top: 0.4rem;
    display: flex;
    align-items: center;
    gap: 7px;
}

/* ── Legacy mc card ── */
.mc {
    background: linear-gradient(150deg, #0d1425 0%, #080c14 100%);
    border: 1px solid #111827;
    border-radius: 10px;
    padding: 1rem 1.2rem 0.9rem;
    margin-bottom: 0.6rem;
    transition: border-color 0.2s;
}
.mc:hover { border-color: #1e2535; }
.mc-lbl {
    font-size: 0.57rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #374151;
    margin-bottom: 0.3rem;
}
.mc-val {
    font-size: 1.55rem;
    font-weight: 700;
    font-family: "Courier New", monospace;
    color: #e6edf3;
    line-height: 1.1;
}
.mc-sub { font-size: 0.65rem; color: #374151; margin-top: 0.2rem; }

/* ── Pills ── */
.pill {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 20px;
    font-size: 0.57rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    white-space: nowrap;
}
.pill-green { background: rgba(63,185,80,0.1);  color: #3fb950; border: 1px solid rgba(63,185,80,0.22); }
.pill-amber { background: rgba(210,153,34,0.1); color: #d29922; border: 1px solid rgba(210,153,34,0.22); }
.pill-red   { background: rgba(248,81,73,0.1);  color: #f85149; border: 1px solid rgba(248,81,73,0.22); }
.pill-blue  { background: rgba(88,166,255,0.1); color: #58a6ff; border: 1px solid rgba(88,166,255,0.22); }

/* ── Section headers ── */
.sh {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 1.5rem 0 0.9rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid #111827;
}
.sh-text {
    font-size: 0.58rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #374151;
}

/* ── Data tables ── */
.fi-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.77rem;
    font-family: "Courier New", monospace;
}
.fi-table th {
    color: #374151;
    font-size: 0.57rem;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    padding: 0.55rem 0.9rem;
    text-align: right;
    border-bottom: 1px solid #111827;
    background: #080c14;
    font-weight: 700;
}
.fi-table th:first-child { text-align: left; }
.fi-table td {
    padding: 0.55rem 0.9rem;
    border-bottom: 1px solid #0a0e18;
    color: #c9d1d9;
    text-align: right;
    transition: background 0.12s;
}
.fi-table td:first-child { text-align: left; color: #6e7681; }
.fi-table tr:hover td { background: #0d1425; }
.ctd-row td {
    color: #58a6ff !important;
    font-weight: 600;
    background: rgba(88,166,255,0.03) !important;
}
.ctd-row td:first-child { color: #79c0ff !important; }

/* ── IR bar ── */
.ir-bar-wrap { display: flex; align-items: center; gap: 7px; justify-content: flex-end; }
.ir-bar-track { width: 72px; height: 3px; background: #111827; border-radius: 2px; overflow: hidden; }
.ir-bar-fill  { height: 100%; border-radius: 2px; background: linear-gradient(90deg, #1e3a5f, #58a6ff); }

/* ── Nav cards ── */
.nav-card {
    background: linear-gradient(150deg, #0d1425 0%, #080c14 100%);
    border: 1px solid #111827;
    border-radius: 10px;
    padding: 1.2rem 1.4rem;
    height: 100%;
    transition: border-color 0.25s, transform 0.2s, box-shadow 0.25s;
}
.nav-card:hover {
    border-color: rgba(88,166,255,0.3);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
}
.nav-card-num {
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #374151;
    margin-bottom: 0.45rem;
}
.nav-card-title {
    font-size: 0.85rem;
    font-weight: 700;
    color: #e6edf3;
    margin-bottom: 0.35rem;
}
.nav-card-desc {
    font-size: 0.7rem;
    color: #6e7681;
    line-height: 1.45;
}
.nav-card-stat {
    font-size: 1.05rem;
    font-weight: 700;
    font-family: "Courier New", monospace;
    color: #58a6ff;
    margin-top: 0.75rem;
    border-top: 1px solid #111827;
    padding-top: 0.6rem;
}

/* ── Banners ── */
.banner {
    background: #0a0e1a;
    border-left: 3px solid #58a6ff;
    border-radius: 0 8px 8px 0;
    padding: 0.7rem 1rem;
    font-size: 0.77rem;
    color: #6e7681;
    margin-bottom: 1rem;
    line-height: 1.55;
}
.banner code {
    background: #111827;
    border-radius: 4px;
    padding: 1px 6px;
    font-family: "Courier New", monospace;
    font-size: 0.74rem;
    color: #79c0ff;
}
.banner b { color: #c9d1d9; }
.banner-warn { border-left-color: #d29922; }
.banner-ok   { border-left-color: #3fb950; }
.banner-red  { border-left-color: #f85149; }

/* ── Color utils ── */
.pos { color: #3fb950; }
.neg { color: #f85149; }
.neu { color: #d29922; }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(num: str, title: str, sub: str = "") -> None:
    """Consistent top header rendered on every subpage."""
    sub_html = f'<div class="page-header-sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="page-header">'
        f'<div class="page-header-eyebrow">{num}</div>'
        f'<div class="page-header-title">{title}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def mc(label: str, value: str, sub: str = "", sub_cls: str = "") -> str:
    sub_html = f'<div class="mc-sub {sub_cls}">{sub}</div>' if sub else ""
    return (
        f'<div class="mc"><div class="mc-lbl">{label}</div>'
        f'<div class="mc-val">{value}</div>{sub_html}</div>'
    )


def sh(text: str) -> None:
    st.markdown(
        f'<div class="sh"><span class="sh-text">{text}</span></div>',
        unsafe_allow_html=True,
    )


def banner(text: str, style: str = "") -> None:
    st.markdown(
        f'<div class="banner {style}">{text}</div>',
        unsafe_allow_html=True,
    )


# ── Sidebar ────────────────────────────────────────────────────────────────────

def sidebar_inputs() -> dict:
    """Render the shared sidebar. Returns current parameter values."""
    with st.sidebar:
        st.markdown(
            '<div style="padding:0.6rem 0 0.1rem;">'
            '<div style="color:#e6edf3;font-size:0.95rem;font-weight:700;letter-spacing:-0.01em;">'
            'CTD Basis Monitor</div>'
            f'<div style="color:#374151;font-size:0.62rem;margin-top:0.15rem;letter-spacing:0.04em;">'
            f'{CONTRACT} · 10Y Treasury Futures</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        st.markdown("**Market inputs**")
        futures_price = st.number_input(
            "Futures Price (% of par)", value=108.50, step=0.01, format="%.4f",
        )
        repo_rate = st.number_input(
            "Repo Rate (%)", value=5.30, step=0.05, format="%.2f",
        ) / 100
        days = int(st.number_input(
            "Days to Delivery", value=110, min_value=1, max_value=365, step=1,
        ))

        st.divider()
        st.markdown("**Yield assumption**")
        st.caption("Flat yield used when DB has no snapshot data.")
        flat_yield = st.number_input(
            "Flat Yield (%)", value=4.50, step=0.05, format="%.2f",
        ) / 100

    return {
        "futures_price": float(futures_price),
        "repo_rate":     float(repo_rate),
        "days":          days,
        "flat_yield":    float(flat_yield),
    }


# ── DB loader ──────────────────────────────────────────────────────────────────

@st.cache_resource
def get_db():
    from data.db import BasisDB
    return BasisDB()


# ── Basket + fresh prices ──────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def fresh_basket(futures_price: float, repo_rate: float, days: int, flat_yield: float):
    """Compute a ranked basket using a flat yield assumption (no DB needed)."""
    from datetime import date
    from core.basket import get_basket
    from core.ctd import rank_basket
    from core.pricing import price_bond

    basket = get_basket(use_api=False)
    as_of  = date.today()
    prices = {
        b["cusip"]: price_bond(
            100.0, b["coupon"],
            max(0.01, (b["maturity"] - as_of).days / 365.25),
            flat_yield,
        )
        for b in basket
    }
    ranked = rank_basket(basket, futures_price, prices, repo_rate, days)
    return ranked
