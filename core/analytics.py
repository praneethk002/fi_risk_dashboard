"""
Advanced fixed income analytics: carry, roll-down, z-spread, and forward
breakeven yield.

These metrics constitute the core of how macro fixed income practitioners
evaluate bond positions. The hierarchy of sophistication:

  Level 1 — Yield to maturity:         "This bond yields 4.6%."
  Level 2 — Duration / DV01:           "I lose $780 per $1M per basis point."
  Level 3 — Carry + roll-down:         "I earn 120bps over 3 months if the curve
                                         doesn't move."
  Level 4 — Z-spread vs spot curve:    "This bond is 15bps cheap vs Treasuries."
  Level 5 — Forward breakeven:         "The 10Y must sell off 25bps before I lose
                                         money over the quarter."

A Capula-style relative value fund operates at levels 3–5 daily.

Continuous vs periodic compounding
-----------------------------------
All discount factors in this module use continuous compounding
(DF = e^{-z·τ}) to interface cleanly with the SpotCurve returned by
core.curves. Cash flows from the Bond object are discounted at continuous
rates interpolated from the spline.

The price_bond function in core.pricing uses periodic compounding (the
market convention for quoted bond prices). The two are reconciled when
constructing a SpotCurve from bootstrapped or NS-fitted spot rates.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from scipy.optimize import brentq
from pydantic import BaseModel, Field, model_validator

from core.curves import SpotCurve

# ── Z-spread solver constants ─────────────────────────────────────────────────
_ZS_MIN = -0.05     # −500 bps lower bound  (rare negative spread)
_ZS_MAX = +0.50     # +5000 bps upper bound (captures all HY / distressed)
_ZS_XTOL = 1e-10    # convergence: sub-0.001 bp accuracy

# ── Default holding periods ───────────────────────────────────────────────────
HOLD_3M = 3.0 / 12.0   # 3 months in years
HOLD_6M = 6.0 / 12.0
HOLD_1Y = 1.0


# ── Bond data model ───────────────────────────────────────────────────────────

class Bond(BaseModel):
    """Immutable bond specification.

    All rates are decimals (e.g. 0.045 for 4.5%).  The model is the single
    source of truth passed between analytics functions; it owns the
    cashflow generation logic so callers never re-implement it.

    Attributes
    ----------
    face_value: Principal (par) amount.
    coupon_rate: Annual coupon as a decimal.
    years_to_maturity: Remaining life from today/settlement.
    frequency: Coupon payments per year (2 = semi-annual, US default).
    ytm: Flat yield to maturity as a decimal.
    """

    face_value: float = Field(default=100.0, gt=0.0)
    coupon_rate: float = Field(..., ge=0.0, le=0.25)
    years_to_maturity: float = Field(..., gt=0.0)
    frequency: int = Field(default=2, ge=1, le=4)
    ytm: float = Field(..., ge=0.0, le=0.30)

    @model_validator(mode="after")
    def _check_maturity_periods(self) -> "Bond":
        n = int(round(self.years_to_maturity * self.frequency))
        if n < 1:
            raise ValueError(
                f"years_to_maturity={self.years_to_maturity} gives < 1 coupon period "
                f"at frequency={self.frequency}."
            )
        return self

    @property
    def coupon_cashflow(self) -> float:
        """Single periodic coupon payment."""
        return self.face_value * self.coupon_rate / self.frequency

    @property
    def n_periods(self) -> int:
        """Total coupon periods remaining."""
        return int(round(self.years_to_maturity * self.frequency))

    def cashflow_times(self) -> np.ndarray:
        """Cash flow payment times in years, shape (n_periods,).

        Times run from 1/frequency to years_to_maturity in equal steps.
        The final entry is the maturity date (last coupon + principal).
        """
        dt = 1.0 / self.frequency
        return np.arange(1, self.n_periods + 1, dtype=float) * dt

    def cashflows(self) -> np.ndarray:
        """Cash flow amounts, shape (n_periods,).

        All entries equal coupon_cashflow; the final entry adds face_value.
        """
        cfs = np.full(self.n_periods, self.coupon_cashflow)
        cfs[-1] += self.face_value
        return cfs


# ── Z-spread ──────────────────────────────────────────────────────────────────

def z_spread(
    bond: Bond,
    dirty_price: float,
    spot_curve: SpotCurve,
) -> float:
    """Z-spread: constant spread over the Treasury spot curve that prices the bond.

    The Z-spread (zero-volatility spread) solves for s in:

        P_dirty = Σ_{t} CF_t · e^{−(z(t) + s) · t}

    where z(t) is the interpolated spot rate at maturity t and CF_t is the
    cash flow (coupon or coupon + principal) at time t.

    Comparison with other spread metrics
    -------------------------------------
    Yield spread  — computed vs a single benchmark yield; ignores curve shape.
    Par spread    — assumes a flat discount curve at the bond's own yield.
    Z-spread      — uses the full spot curve as the risk-free base; comparable
                    across bonds with different coupon structures.
    OAS           — Z-spread after stripping out embedded option value (calls,
                    puts); requires a rate model. Not implemented here.

    A positive Z-spread means the bond offers excess yield over Treasuries —
    it is "cheap" vs the risk-free curve.

    Args:
        bond: Bond specification (coupon, maturity, face value, frequency).
        dirty_price: Observed full (invoice) price in the same units as
            ``bond.face_value``.
        spot_curve: Fitted :class:`~core.curves.SpotCurve` for discounting.

    Returns:
        Z-spread as a decimal (e.g. 0.0025 = +25 bps).

    Raises:
        ValueError: If the bond cannot be priced within ±500 / +5000 bps.
    """
    times = bond.cashflow_times()           # shape (n,)
    cfs = bond.cashflows()                  # shape (n,)
    spot_rates = spot_curve.rate(times)     # vectorised: shape (n,)

    def _price_residual(s: float) -> float:
        dfs = np.exp(-(spot_rates + s) * times)
        return float(np.dot(cfs, dfs)) - dirty_price

    lo_val = _price_residual(_ZS_MIN)
    hi_val = _price_residual(_ZS_MAX)

    if lo_val * hi_val > 0:
        raise ValueError(
            f"Z-spread root not bracketed: residuals at bounds are "
            f"{lo_val:.4f} (s={_ZS_MIN*1e4:.0f}bps) and "
            f"{hi_val:.4f} (s={_ZS_MAX*1e4:.0f}bps). "
            f"Check dirty_price={dirty_price:.4f} is realistic."
        )

    return float(brentq(_price_residual, _ZS_MIN, _ZS_MAX, xtol=_ZS_XTOL))


# ── Roll-down return ──────────────────────────────────────────────────────────

class RollDownResult(NamedTuple):
    """Return components from a carry + roll-down analysis."""

    price_now: float
    """Current price using periodic compounding at bond.ytm."""

    price_rolled: float
    """Price after the holding period at the spot curve rate for the shorter maturity."""

    coupon_accrual_pct: float
    """Coupon income over the holding period as % of initial price."""

    roll_down_pct: float
    """Price appreciation (or depreciation) from rolling, as % of initial price."""

    total_carry_roll_pct: float
    """Total carry + roll-down return as % of initial price (= coupon + roll)."""

    forward_breakeven_ytm: float
    """YTM the bond must reach at horizon for the position to break even.
    Derived as the forward rate f(holding_period, years_to_maturity)."""

    holding_period_yrs: float
    """Holding period used for the calculation, in years."""


def roll_down_return(
    bond: Bond,
    spot_curve: SpotCurve,
    holding_period_yrs: float = HOLD_3M,
) -> RollDownResult:
    """Carry + roll-down total return assuming a static yield curve.

    The roll-down assumption: the yield curve shape is completely unchanged
    over the holding period. As calendar time passes, a 10Y bond becomes a
    9.75Y bond (after 3 months). If the curve is upward-sloping, the 9.75Y
    spot rate is lower than the 10Y rate, so the bond price rises. This
    appreciation is the roll-down.

    Why this matters for Capula's strategy
    ----------------------------------------
    Carry + roll is the "free money" from being long duration on a steep
    curve. A fund that is long the 5Y–10Y sector collects both the coupon
    carry and the roll-down even with zero net change in yields. The forward
    breakeven tells you exactly how much the curve must move against you
    before this carry + roll is wiped out.

    Args:
        bond: Bond specification.
        spot_curve: Current spot curve — assumed static over holding period.
        holding_period_yrs: Calendar time elapsed (default 3 months = 0.25yr).

    Returns:
        :class:`RollDownResult` NamedTuple with all return components.

    Raises:
        ValueError: If holding_period_yrs >= bond.years_to_maturity.
    """
    from core.pricing import price_bond as _price_bond

    if holding_period_yrs >= bond.years_to_maturity:
        raise ValueError(
            f"holding_period_yrs={holding_period_yrs} must be < "
            f"bond.years_to_maturity={bond.years_to_maturity}"
        )

    # ── Current price: periodic compounding at bond's own YTM ────────────
    # Consistent with market-quoted clean prices. For a par bond
    # (coupon = ytm), this equals the face value exactly.
    price_now = _price_bond(
        bond.face_value, bond.coupon_rate,
        bond.years_to_maturity, bond.ytm, bond.frequency,
    )

    # ── Rolled price: same bond priced at the SHORTER maturity's spot rate ─
    # Reading the yield at the rolled maturity from the static spot curve
    # isolates the pure roll-down effect (yield pickup from sliding down
    # the curve). Using periodic compounding ensures consistency with
    # price_now and gives roll_down = 0 for a par bond on a flat curve.
    rolled_maturity = bond.years_to_maturity - holding_period_yrs
    rolled_yield = spot_curve.rate(rolled_maturity)
    price_rolled = _price_bond(
        bond.face_value, bond.coupon_rate,
        rolled_maturity, rolled_yield, bond.frequency,
    )

    # ── Coupon accrual over holding period ────────────────────────────────
    coupon_accrual = bond.coupon_rate * bond.face_value * holding_period_yrs
    coupon_pct = coupon_accrual / price_now * 100.0

    # ── Roll-down ─────────────────────────────────────────────────────────
    roll_pct = (price_rolled - price_now) / price_now * 100.0

    # ── Forward breakeven: forward rate for the remaining period ──────────
    fwd_breakeven = spot_curve.forward_rate(holding_period_yrs, bond.years_to_maturity)

    return RollDownResult(
        price_now=round(price_now, 6),
        price_rolled=round(price_rolled, 6),
        coupon_accrual_pct=round(coupon_pct, 4),
        roll_down_pct=round(roll_pct, 4),
        total_carry_roll_pct=round(coupon_pct + roll_pct, 4),
        forward_breakeven_ytm=round(fwd_breakeven, 6),
        holding_period_yrs=holding_period_yrs,
    )


# ── Total return decomposition ────────────────────────────────────────────────

class TotalReturnDecomposition(NamedTuple):
    """Full P&L attribution for a bond position over a holding period."""

    carry_pct: float
    """Coupon accrual minus repo financing, as % of initial price."""

    roll_down_pct: float
    """Price change from rolling down the static curve, as % of initial price."""

    duration_pnl_pct: float
    """P&L from a parallel yield shift: −MD × Δy × 100 (in %, sign = direction)."""

    convexity_pnl_pct: float
    """Convexity correction: +0.5 × convexity × Δy² × 100 (in %)."""

    total_pct: float
    """Sum of all four components, as % of initial price."""


def total_return_decomposition(
    bond: Bond,
    spot_curve: SpotCurve,
    repo_rate: float,
    holding_period_yrs: float = HOLD_3M,
    yield_change: float = 0.0,
    modified_duration: float | None = None,
    convexity: float | None = None,
) -> TotalReturnDecomposition:
    """Full P&L attribution split into carry, roll, duration, and convexity.

    This decomposition is how fixed income risk managers report position
    performance. Each component is independently controllable:

      Carry       → hedged via repo rate (repo-funded long duration)
      Roll-down   → hedged by selling forward (locking in the forward yield)
      Duration P&L → hedged via futures DV01 overlay
      Convexity   → hedged via options (vega / gamma)

    Args:
        bond: Bond specification.
        spot_curve: Current spot curve (assumed static for carry + roll).
        repo_rate: Overnight / term repo rate for financing the position.
        holding_period_yrs: Horizon in years.
        yield_change: Parallel yield shift in decimal over the holding period
            (e.g. +0.005 = +50bps). Default 0 = carry-only scenario.
        modified_duration: If None, estimated numerically from the spot curve.
        convexity: If None, estimated numerically from the spot curve.

    Returns:
        :class:`TotalReturnDecomposition` NamedTuple.
    """
    from core.risk import modified_duration as _md, convexity as _cvx

    rd = roll_down_return(bond, spot_curve, holding_period_yrs)
    price_now = rd.price_now

    # Financing cost over holding period
    financing_pct = repo_rate * holding_period_yrs * 100.0
    carry_pct = rd.coupon_accrual_pct - financing_pct

    # Duration and convexity — use supplied values or compute from YTM
    md = modified_duration if modified_duration is not None else _md(
        bond.face_value, bond.coupon_rate, bond.years_to_maturity, bond.ytm, bond.frequency
    )
    cvx = convexity if convexity is not None else _cvx(
        bond.face_value, bond.coupon_rate, bond.years_to_maturity, bond.ytm, bond.frequency
    )

    duration_pnl_pct = -md * yield_change * 100.0
    convexity_pnl_pct = 0.5 * cvx * yield_change**2 * 100.0
    total_pct = carry_pct + rd.roll_down_pct + duration_pnl_pct + convexity_pnl_pct

    return TotalReturnDecomposition(
        carry_pct=round(carry_pct, 4),
        roll_down_pct=round(rd.roll_down_pct, 4),
        duration_pnl_pct=round(duration_pnl_pct, 4),
        convexity_pnl_pct=round(convexity_pnl_pct, 4),
        total_pct=round(total_pct, 4),
    )


# ── Curve spread metrics ──────────────────────────────────────────────────────

def curve_spreads(curve: dict[str, float]) -> dict[str, float]:
    """Calculate standard US Treasury yield curve spread metrics.

    These spreads are the primary relative value signals for macro fixed income
    and are referenced directly in conversations about curve trades:

      2s10s (basis)     — The most-watched recession indicator. Negative
                          (inverted) when the Fed is hiking and the front end
                          rises faster than the long end. Turned negative in
                          2022 and drove carry + roll negative for 2Y holders.

      5s30s (basis)     — Long-end steepness. Driven by term premium and
                          fiscal supply dynamics. Capula uses this sector for
                          positive carry + roll trades on a steep curve.

      2s5s10s butterfly  — Mid-curve richness. Positive = 5Y belly is cheap vs
                          the 2Y/10Y wings. A long butterfly (long belly, short
                          wings) profits when curvature increases. The standard
                          expression for a β₂ view in Nelson-Siegel terms.

    Args:
        curve: Mapping of maturity label to decimal yield.
            Must contain keys "2Y", "5Y", "10Y", and "30Y".

    Returns:
        Dict with "2s10s_bps", "5s30s_bps", "2s5s10s_fly_bps", all in
        basis points. Negative 2s10s indicates a yield curve inversion.

    Raises:
        KeyError: If any required maturity is missing from ``curve``.
    """
    required = {"2Y", "5Y", "10Y", "30Y"}
    missing = required - curve.keys()
    if missing:
        raise KeyError(f"curve is missing required maturities: {missing}")

    to_bps = 10_000.0
    return {
        "2s10s_bps":       (curve["10Y"] - curve["2Y"]) * to_bps,
        "5s30s_bps":       (curve["30Y"] - curve["5Y"]) * to_bps,
        "2s5s10s_fly_bps": (2 * curve["5Y"] - curve["2Y"] - curve["10Y"]) * to_bps,
    }
