"""
Fixed Income Risk Dashboard — MCP Server

Exposes bond analytics as Model Context Protocol (MCP) tools so that an LLM
(Claude, etc.) can call them programmatically during a conversation.

Available tools
---------------
get_yield_curve          Live US Treasury curve from FRED
price_bond               DCF bond price
risk_metrics             Modified duration, DV01, convexity
scenario_analysis        Yield curve scenario + price impact
basis_analytics          Gross basis, net basis, implied repo
find_ctd                 Cheapest-to-deliver identification

Run
---
    python -m mcp_server.server          # stdio transport (default for Claude)
    python mcp_server/server.py          # same
"""

from __future__ import annotations

import sys
import os

# Allow running from the project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from core.pricing import price_bond as _price_bond
from core.risk import modified_duration, dv01, convexity
from core.scenarios import (
    parallel_shift,
    bear_steepening,
    bear_flattening,
    custom_shift,
)
from core.basis import (
    gross_basis,
    carry as calc_carry,
    net_basis,
    implied_repo,
    find_ctd as _find_ctd,
)
from mcp_server.fred_client import get_yield_curve as _get_yield_curve

mcp = FastMCP("fi-risk-dashboard")


# ── Tool 1: Live yield curve ───────────────────────────────────────────────

@mcp.tool()
def get_yield_curve() -> dict[str, float]:
    """Return the live US Treasury yield curve from FRED.

    Returns a mapping of maturity label to decimal yield,
    e.g. {"3M": 0.0425, "2Y": 0.0435, "5Y": 0.0448, "10Y": 0.0462, "30Y": 0.0478}.
    Rates are cached for 5 minutes.
    """
    return _get_yield_curve()


# ── Tool 2: Bond pricing ───────────────────────────────────────────────────

@mcp.tool()
def price_bond(
    face_value: float,
    coupon_rate_pct: float,
    years_to_maturity: float,
    yield_rate_pct: float,
    frequency: int = 2,
) -> dict[str, float]:
    """Price a fixed-coupon bond on a coupon date (clean = dirty price).

    Args:
        face_value: Principal (e.g. 1000).
        coupon_rate_pct: Annual coupon as a percentage (e.g. 5.0 for 5%).
        years_to_maturity: Remaining life in years (e.g. 10).
        yield_rate_pct: Annual yield as a percentage (e.g. 4.5 for 4.5%).
        frequency: Coupon payments per year (1 = annual, 2 = semi-annual).

    Returns:
        {"price": <float>}
    """
    p = _price_bond(
        face_value,
        coupon_rate_pct / 100,
        years_to_maturity,
        yield_rate_pct / 100,
        frequency,
    )
    return {"price": round(p, 6)}


# ── Tool 3: Risk metrics ───────────────────────────────────────────────────

@mcp.tool()
def risk_metrics(
    face_value: float,
    coupon_rate_pct: float,
    years_to_maturity: float,
    yield_rate_pct: float,
    frequency: int = 2,
) -> dict[str, float]:
    """Calculate modified duration, DV01, and convexity for a bond.

    Args:
        face_value: Principal (e.g. 1000).
        coupon_rate_pct: Annual coupon as a percentage.
        years_to_maturity: Remaining life in years.
        yield_rate_pct: Annual yield as a percentage.
        frequency: Coupon payments per year.

    Returns:
        {
          "modified_duration": <years>,
          "dv01": <currency per 1bp>,
          "convexity": <years²>
        }
    """
    cr = coupon_rate_pct / 100
    yr = yield_rate_pct / 100
    return {
        "modified_duration": round(modified_duration(face_value, cr, years_to_maturity, yr, frequency), 4),
        "dv01": round(dv01(face_value, cr, years_to_maturity, yr, frequency), 6),
        "convexity": round(convexity(face_value, cr, years_to_maturity, yr, frequency), 4),
    }


# ── Tool 4: Scenario analysis ──────────────────────────────────────────────

@mcp.tool()
def scenario_analysis(
    face_value: float,
    coupon_rate_pct: float,
    years_to_maturity: float,
    current_yield_pct: float,
    scenario: str,
    shift_bps: float,
    frequency: int = 2,
) -> dict[str, float | str]:
    """Apply a yield curve scenario and report the resulting bond price change.

    Args:
        face_value: Principal.
        coupon_rate_pct: Annual coupon as a percentage.
        years_to_maturity: Remaining life in years.
        current_yield_pct: Current annual yield as a percentage.
        scenario: One of "parallel", "bear_steepening", "bear_flattening".
        shift_bps: Shift magnitude in basis points.
        frequency: Coupon payments per year.

    Returns:
        {
          "scenario": <str>,
          "shift_bps": <float>,
          "original_price": <float>,
          "new_yield_pct": <float>,
          "new_price": <float>,
          "price_change": <float>,
          "price_change_pct": <float>
        }
    """
    base_curve = {"10Y": current_yield_pct / 100}

    scenario_map = {
        "parallel": parallel_shift,
        "bear_steepening": bear_steepening,
        "bear_flattening": bear_flattening,
    }
    if scenario not in scenario_map:
        valid = ", ".join(scenario_map)
        raise ValueError(f"scenario must be one of: {valid}")

    shifted_curve = scenario_map[scenario](base_curve, shift_bps)
    new_yield = shifted_curve["10Y"]

    cr = coupon_rate_pct / 100
    original_price = _price_bond(face_value, cr, years_to_maturity, current_yield_pct / 100, frequency)
    new_price = _price_bond(face_value, cr, years_to_maturity, new_yield, frequency)
    price_change = new_price - original_price

    return {
        "scenario": scenario,
        "shift_bps": shift_bps,
        "original_price": round(original_price, 4),
        "new_yield_pct": round(new_yield * 100, 4),
        "new_price": round(new_price, 4),
        "price_change": round(price_change, 4),
        "price_change_pct": round(price_change / original_price * 100, 4),
    }


# ── Tool 5: Basis analytics ────────────────────────────────────────────────

@mcp.tool()
def basis_analytics(
    cash_price: float,
    futures_price: float,
    conversion_factor: float,
    coupon_rate_pct: float,
    repo_rate_pct: float,
    days_to_delivery: int,
) -> dict[str, float]:
    """Calculate Treasury cash-futures basis metrics.

    Args:
        cash_price: Clean cash price as % of par (e.g. 98.50).
        futures_price: Quoted futures price as % of par (e.g. 97.00).
        conversion_factor: CME/CBOT conversion factor for the bond.
        coupon_rate_pct: Annual coupon as a percentage.
        repo_rate_pct: Repo rate as a percentage.
        days_to_delivery: Calendar days to futures delivery date.

    Returns:
        {
          "gross_basis": <price points>,
          "carry": <price points>,
          "net_basis": <price points>,
          "implied_repo_pct": <percentage>
        }
    """
    cr = coupon_rate_pct / 100
    rr = repo_rate_pct / 100
    return {
        "gross_basis": round(gross_basis(cash_price, futures_price, conversion_factor), 6),
        "carry": round(calc_carry(cash_price, cr, rr, days_to_delivery), 6),
        "net_basis": round(net_basis(cash_price, futures_price, conversion_factor, cr, rr, days_to_delivery), 6),
        "implied_repo_pct": round(implied_repo(cash_price, futures_price, conversion_factor, cr, days_to_delivery) * 100, 4),
    }


# ── Tool 6: Find CTD ───────────────────────────────────────────────────────

@mcp.tool()
def find_ctd(
    bonds_json: list[dict],
    futures_price: float,
    days_to_delivery: int,
) -> dict:
    """Identify the cheapest-to-deliver (CTD) bond in a delivery basket.

    The CTD is determined by the highest implied repo rate.

    Args:
        bonds_json: List of bond dicts, each with:
                    - "cash_price" (float): clean price as % of par
                    - "conversion_factor" (float): CME/CBOT CF
                    - "coupon_rate_pct" (float): annual coupon as a percentage
                    - "label" (str, optional): identifier
        futures_price: Quoted futures price as % of par.
        days_to_delivery: Calendar days to futures delivery.

    Returns:
        The CTD bond dict augmented with "implied_repo_pct".
    """
    # Normalise coupon_rate_pct → coupon_rate decimal for internal functions
    normalised = [
        {**b, "coupon_rate": b["coupon_rate_pct"] / 100}
        for b in bonds_json
    ]
    ctd = _find_ctd(normalised, futures_price, days_to_delivery)
    # Return pct for readability
    ctd["implied_repo_pct"] = round(ctd.pop("implied_repo") * 100, 4)
    ctd.pop("coupon_rate", None)  # remove internal decimal field
    return ctd


if __name__ == "__main__":
    mcp.run()
