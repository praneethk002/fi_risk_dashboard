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
    plot_bgcolor="rgba(13,17,23,0.5)",
    font=dict(family="'Courier New', monospace", color="#8b949e", size=11),
    margin=dict(t=24, b=44, l=56, r=20),
    xaxis=dict(gridcolor="#21262d", linecolor="#30363d", zerolinecolor="#30363d"),
    yaxis=dict(gridcolor="#21262d", linecolor="#30363d", zerolinecolor="#30363d"),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="#21262d", borderwidth=1),
)

# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = """
<style>
html, body, [class*="css"] { font-family: "Inter", "Segoe UI", sans-serif; }
.stApp { background-color: #0d1117; }
#MainMenu, footer { visibility: hidden; }

[data-testid="stSidebar"] {
    background-color: #161b27;
    border-right: 1px solid #21262d;
}
[data-testid="stSidebar"] .stMarkdown p {
    color: #8b949e; font-size: 0.68rem; letter-spacing: 0.1em;
    text-transform: uppercase; margin: 1rem 0 0.3rem 0; font-weight: 600;
}

/* Metric card */
.mc {
    background: linear-gradient(160deg,#161b27 0%,#0d1117 100%);
    border: 1px solid #21262d; border-radius: 6px;
    padding: 0.9rem 1.1rem 0.8rem; margin-bottom: 0.5rem;
}
.mc-lbl { color: #8b949e; font-size: 0.6rem; letter-spacing: 0.14em;
          text-transform: uppercase; font-weight: 600; margin-bottom: 0.25rem; }
.mc-val { color: #e6edf3; font-size: 1.55rem; font-weight: 700;
          font-family: "Courier New", monospace; line-height: 1.1; }
.mc-sub { color: #8b949e; font-size: 0.68rem; margin-top: 0.15rem; }
.pos { color: #3fb950; } .neg { color: #f85149; } .neu { color: #d29922; }

/* Section header */
.sh {
    color: #8b949e; font-size: 0.6rem; font-weight: 600;
    letter-spacing: 0.15em; text-transform: uppercase;
    border-bottom: 1px solid #21262d; padding-bottom: 0.35rem;
    margin: 1.1rem 0 0.75rem 0;
}

/* Info banner */
.banner {
    background: #1c2128; border-left: 3px solid #58a6ff;
    border-radius: 0 4px 4px 0; padding: 0.6rem 0.9rem;
    font-size: 0.78rem; color: #8b949e; margin-bottom: 0.8rem;
}
.banner-warn { border-left-color: #d29922; }
.banner-ok   { border-left-color: #3fb950; }
.banner-red  { border-left-color: #f85149; }

/* Data table */
.fi-table { width:100%; border-collapse:collapse; font-size:0.78rem;
            font-family:"Courier New",monospace; }
.fi-table th { color:#8b949e; font-size:0.6rem; letter-spacing:0.1em;
               text-transform:uppercase; padding:0.4rem 0.8rem;
               text-align:right; border-bottom:1px solid #21262d;
               background:#161b27; }
.fi-table th:first-child { text-align:left; }
.fi-table td { padding:0.45rem 0.8rem; border-bottom:1px solid #161b27;
               color:#e6edf3; text-align:right; }
.fi-table td:first-child { text-align:left; color:#8b949e; }
.fi-table tr:hover td { background:#1c2128; }
.ctd-row td { color:#58a6ff !important; font-weight:700; }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def mc(label: str, value: str, sub: str = "", sub_cls: str = "") -> str:
    sub_html = f'<div class="mc-sub {sub_cls}">{sub}</div>' if sub else ""
    return (
        f'<div class="mc"><div class="mc-lbl">{label}</div>'
        f'<div class="mc-val">{value}</div>{sub_html}</div>'
    )


def sh(text: str) -> None:
    st.markdown(f'<div class="sh">{text}</div>', unsafe_allow_html=True)


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
            '<div style="color:#e6edf3;font-size:1.05rem;font-weight:700;'
            'letter-spacing:0.03em;padding:0.5rem 0 0.2rem;">'
            'CTD Basis Monitor</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"{CONTRACT} · 10-Year Treasury Note Futures")
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
