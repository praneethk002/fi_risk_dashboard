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
nelson_siegel_fit        Fit NS model to yield curve data
carry_roll_analysis      Carry + roll-down for 3M/6M/1Y horizons
z_spread_analysis        Z-spread over Treasury spot curve
curve_spread_metrics     2s10s, 5s30s, 2s5s10s butterfly from live curve

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

import numpy as np
from mcp.server.fastmcp import FastMCP

from core.pricing import price_bond as _price_bond
from core.risk import modified_duration, dv01, convexity
from core.scenarios import (
    parallel_shift,
    bear_steepening,
    bear_flattening,
    bull_steepening,
    bull_flattening,
    custom_shift,
)
from core.basis import (
    gross_basis,
    carry as calc_carry,
    net_basis,
    implied_repo,
    find_ctd as _find_ctd,
)
from core.curves import (
    TREASURY_MATURITIES_YRS,
    fit_nelson_siegel,
    SpotCurve,
)
from core.analytics import (
    Bond,
    z_spread as _z_spread,
    roll_down_return,
    curve_spreads as _curve_spreads,
    HOLD_3M,
    HOLD_6M,
    HOLD_1Y,
)
from mcp_server.fred_client import get_yield_curve as _get_yield_curve

_MATURITY_MAP: dict[str, float] = {
    "3M": 0.25, "2Y": 2.0, "5Y": 5.0, "10Y": 10.0, "30Y": 30.0,
}


def _build_spot_curve() -> SpotCurve:
    """Fetch FRED data, fit Nelson-Siegel, and return a SpotCurve."""
    raw = _get_yield_curve()
    mats = np.array([_MATURITY_MAP[k] for k in raw if k in _MATURITY_MAP])
    ylds = np.array([raw[k] for k in raw if k in _MATURITY_MAP])
    order = np.argsort(mats)
    params = fit_nelson_siegel(mats[order], ylds[order])
    return SpotCurve.from_nelson_siegel(params)

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
        "bull_steepening": bull_steepening,
        "bull_flattening": bull_flattening,
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


# ── Tool 7: Nelson-Siegel fit ──────────────────────────────────────────────

@mcp.tool()
def nelson_siegel_fit(
    maturities_yrs: list[float],
    yields_pct: list[float],
) -> dict:
    """Fit the Nelson-Siegel (1987) model to observed yield curve data.

    The NS model decomposes the yield curve into three economically meaningful
    factors that macro fixed income desks use for risk attribution:

      β₀ — Long-run level: where all yields converge at infinite maturity.
            Represents market's long-term inflation + real rate expectation.
      β₁ — Slope: negative = normal (upward-sloping) curve; positive = inverted.
            Approximately equal to (short_rate − long_rate).
      β₂ — Curvature: hump or trough in the belly (5Y sector).
            Positive = 5Y belly is cheap vs wings (long butterfly exposure).
      λ  — Decay speed: maturity (years) where slope/curvature loadings peak.

    RMSE < 2bps indicates an excellent fit to the data.

    Args:
        maturities_yrs: Pillar maturities in years (e.g., [0.25, 2, 5, 10, 30]).
        yields_pct: Corresponding yields as percentages (e.g., [5.3, 4.9, 4.6, 4.5, 4.7]).

    Returns:
        {
          "beta0_pct": <long-run level in %>,
          "beta1_pct": <slope in %>,
          "beta2_pct": <curvature in %>,
          "lambda_yrs": <decay speed in years>,
          "fit_rmse_bps": <root-mean-square fitting error in bps>,
          "curve_shape": <"normal" | "inverted" | "flat" | "humped">
        }
    """
    mats = np.array(maturities_yrs, dtype=float)
    ylds = np.array(yields_pct, dtype=float) / 100.0
    order = np.argsort(mats)
    params = fit_nelson_siegel(mats[order], ylds[order])

    # Characterise curve shape from fitted parameters
    if params.beta1 < -0.005:
        shape = "normal"
    elif params.beta1 > 0.005:
        shape = "inverted"
    elif abs(params.beta2) > 0.005:
        shape = "humped"
    else:
        shape = "flat"

    return {
        "beta0_pct": round(params.beta0 * 100, 4),
        "beta1_pct": round(params.beta1 * 100, 4),
        "beta2_pct": round(params.beta2 * 100, 4),
        "lambda_yrs": round(params.lambda_, 4),
        "fit_rmse_bps": round(params.fit_rmse_bps, 4),
        "curve_shape": shape,
    }


# ── Tool 8: Carry + roll-down ──────────────────────────────────────────────

@mcp.tool()
def carry_roll_analysis(
    face_value: float,
    coupon_rate_pct: float,
    years_to_maturity: float,
    ytm_pct: float,
    repo_rate_pct: float,
    frequency: int = 2,
) -> dict:
    """Carry + roll-down return assuming a static Treasury yield curve.

    The carry + roll is the "free money" from being long duration on a
    steep curve: coupon income minus repo financing cost, plus price
    appreciation from rolling to a shorter (lower-yielding) maturity.

    The forward breakeven yield is the yield the bond must reach at the
    horizon to exactly zero out the carry + roll profit. A steep curve
    means the breakeven is well above the current yield — providing a
    substantial cushion against rate rises.

    Uses the live US Treasury spot curve (FRED) to compute roll-down.
    Falls back to a representative curve if FRED is unavailable.

    Args:
        face_value: Principal (e.g. 1000).
        coupon_rate_pct: Annual coupon as a percentage.
        years_to_maturity: Remaining life in years.
        ytm_pct: Yield to maturity as a percentage.
        repo_rate_pct: Overnight/term repo rate as a percentage.
        frequency: Coupon payments per year (2 = semi-annual).

    Returns:
        Dict with carry, roll-down, and total for 3M, 6M, and 1Y horizons.
        Each horizon also reports the forward breakeven yield.
    """
    bond = Bond(
        face_value=face_value,
        coupon_rate=coupon_rate_pct / 100,
        years_to_maturity=years_to_maturity,
        ytm=ytm_pct / 100,
        frequency=frequency,
    )
    spot_curve = _build_spot_curve()
    repo = repo_rate_pct / 100

    results: dict[str, dict] = {}
    for label, hp in [("3M", HOLD_3M), ("6M", HOLD_6M), ("1Y", HOLD_1Y)]:
        if hp >= bond.years_to_maturity:
            continue
        rd = roll_down_return(bond, spot_curve, hp)
        financing_pct = repo * hp * 100.0
        net_carry_pct = rd.coupon_accrual_pct - financing_pct
        results[label] = {
            "coupon_accrual_pct": round(rd.coupon_accrual_pct, 4),
            "financing_cost_pct": round(financing_pct, 4),
            "net_carry_pct": round(net_carry_pct, 4),
            "roll_down_pct": round(rd.roll_down_pct, 4),
            "total_carry_roll_pct": round(net_carry_pct + rd.roll_down_pct, 4),
            "forward_breakeven_ytm_pct": round(rd.forward_breakeven_ytm * 100, 4),
        }

    return results


# ── Tool 9: Z-spread ───────────────────────────────────────────────────────

@mcp.tool()
def z_spread_analysis(
    face_value: float,
    coupon_rate_pct: float,
    years_to_maturity: float,
    ytm_pct: float,
    dirty_price: float | None = None,
    frequency: int = 2,
) -> dict[str, float | str]:
    """Z-spread (zero-volatility spread) over the live Treasury spot curve.

    The Z-spread is the constant spread added to every point on the Treasury
    spot curve that makes the present value of the bond's cash flows equal its
    market price. It is the single most comparable spread metric across bonds
    with different coupon structures.

    Comparison with simpler spread measures:
      Yield spread — YTM minus the on-the-run Treasury yield at nearest maturity.
                     Ignores the shape of the yield curve entirely.
      Z-spread     — constant spread over the full spot curve; properly accounts
                     for cash flows at all maturities.
      OAS          — Z-spread adjusted for embedded options; requires a rate model.

    Positive Z-spread: bond is cheap vs Treasuries (carries a risk premium).
    Negative Z-spread: bond is rich vs Treasuries (e.g. off-the-run richness, special).

    Uses live FRED Treasury spot curve. If dirty_price is omitted, the bond is
    priced at its input YTM (assumes settlement on a coupon date).

    Args:
        face_value: Principal (e.g. 1000).
        coupon_rate_pct: Annual coupon as a percentage.
        years_to_maturity: Remaining life in years.
        ytm_pct: Yield to maturity as a percentage (used to compute dirty price
            if dirty_price is not supplied).
        dirty_price: Invoice price (optional). If None, computed from ytm_pct.
        frequency: Coupon payments per year.

    Returns:
        {
          "dirty_price": <invoice price>,
          "z_spread_bps": <Z-spread in basis points>,
          "treasury_spot_rate_pct": <Treasury spot rate at bond maturity>,
          "yield_spread_bps": <simple yield spread = YTM − Treasury spot>,
          "compounding_note": <convention description>
        }
    """
    bond = Bond(
        face_value=face_value,
        coupon_rate=coupon_rate_pct / 100,
        years_to_maturity=years_to_maturity,
        ytm=ytm_pct / 100,
        frequency=frequency,
    )
    if dirty_price is None:
        dirty_price = _price_bond(
            face_value, coupon_rate_pct / 100, years_to_maturity,
            ytm_pct / 100, frequency,
        )

    spot_curve = _build_spot_curve()
    zs = _z_spread(bond, dirty_price, spot_curve)
    treasury_spot = spot_curve.rate(years_to_maturity)
    yield_spread = ytm_pct / 100 - treasury_spot

    return {
        "dirty_price": round(dirty_price, 4),
        "z_spread_bps": round(zs * 10_000, 2),
        "treasury_spot_rate_pct": round(treasury_spot * 100, 4),
        "yield_spread_bps": round(yield_spread * 10_000, 2),
        "compounding_note": "Z-spread on continuous compounding basis (SpotCurve convention).",
    }


# ── Tool 10: Curve spread metrics ─────────────────────────────────────────

@mcp.tool()
def curve_spread_metrics() -> dict[str, float | str]:
    """Live US Treasury curve spread metrics from FRED.

    These are the primary relative value signals for macro fixed income desks:

      2s10s (bps)       — The most-watched recession indicator. Negative
                          (inverted) when the Fed is hiking aggressively.
                          Turned negative in March 2022, went as low as −108bps
                          in July 2023, re-steepened as the cutting cycle began.

      5s30s (bps)       — Long-end steepness. Driven by term premium and fiscal
                          supply dynamics. A steep 5s30s generates positive
                          carry + roll for duration longs in the 10–30Y sector.

      2s5s10s fly (bps) — Mid-curve richness. Positive = 5Y belly is cheap vs
                          the 2Y/10Y wings (negative curvature in NS terms:
                          β₂ < 0). A long butterfly (long belly, short wings)
                          profits when curvature increases.

    Returns:
        {
          "2s10s_bps": <10Y − 2Y in bps>,
          "5s30s_bps": <30Y − 5Y in bps>,
          "2s5s10s_fly_bps": <2×5Y − 2Y − 10Y in bps>,
          "curve_regime": <"steep" | "flat" | "inverted">,
          "source": "FRED"
        }
    """
    raw = _get_yield_curve()
    spreads = _curve_spreads(raw)

    s2s10 = spreads["2s10s_bps"]
    if s2s10 > 50:
        regime = "steep"
    elif s2s10 > -10:
        regime = "flat"
    else:
        regime = "inverted"

    return {
        "2s10s_bps": round(s2s10, 1),
        "5s30s_bps": round(spreads["5s30s_bps"], 1),
        "2s5s10s_fly_bps": round(spreads["2s5s10s_fly_bps"], 1),
        "curve_regime": regime,
        "source": "FRED",
    }


if __name__ == "__main__":
    mcp.run()
