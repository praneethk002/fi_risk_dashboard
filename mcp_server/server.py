"""CTD Basis Monitor — MCP Server

Exposes eight basis-desk tools so that Claude can synthesize a structured
morning brief from the historical basis database.

The genuine value here is not computation — that lives in core/ and data/.
It is synthesis: Claude reads the database via these tools and translates
quantitative signals (percentile rank, CTD transition proximity, scenario
output) into a narrative that would take a junior analyst 20 minutes to write.

Capula Investment Management is described as "the largest player in futures
basis trades."  These tools are built for exactly that morning workflow.

Available tools
---------------
get_current_basket          Full delivery basket with implied repos, CTD flagged
get_basis_history           90-day net basis time-series for a specific bond
get_basis_percentile        Where today's CTD net basis sits in its 90-day range
get_ctd_transitions         Log of CTD switches + implied repo spread at switch
get_transition_proximity    Current implied repo spread with risk flag + trend
run_scenario_grid           Basket re-ranking under parallel yield shifts (FRED yields)
get_ctd_transition_threshold Futures price at which CTD identity would switch
get_carry_roll              Carry and roll-down for a bond over 3M/6M horizons

Run
---
    python -m mcp_server.server          # stdio transport (default for Claude)
    python mcp_server/server.py          # same
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from data.db import BasisDB
from core.basket import get_basket, bond_label, DELIVERY_DATE
from core.scenario import scenario_grid as _scenario_grid
from core.ctd import ctd_transition_threshold as _ctd_threshold, switch_direction as _switch_direction, basket_switch_map as _basket_switch_map
from core.carry import carry as _carry
from core.pricing import price_bond as _price_bond
from data.fred_client import get_yield_curve as _get_fred_curve
from mcp_server import db_client

_db = BasisDB()
_db.init_schema()

mcp = FastMCP("ctd-basis-monitor")

# ---------------------------------------------------------------------------
# Shared helpers for new tools
# ---------------------------------------------------------------------------

_MATURITY_MAP: dict[str, float] = {
    "3M": 0.25, "2Y": 2.0, "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "30Y": 30.0,
}


def _try_get_fred_curve() -> dict[str, float]:
    """Fetch FRED yield curve, returning empty dict on any network failure."""
    try:
        return _get_fred_curve()
    except Exception:
        return {}


def _interp_yield(years: float, curve: dict[str, float]) -> float:
    """Linearly interpolate / flat-extrapolate the FRED curve to any maturity."""
    pts = sorted(
        [(m, curve[k]) for k, m in _MATURITY_MAP.items() if k in curve],
        key=lambda x: x[0],
    )
    if not pts:
        return 0.045                     # safe fallback
    if years <= pts[0][0]:
        return pts[0][1]
    if years >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        m0, r0 = pts[i]
        m1, r1 = pts[i + 1]
        if m0 <= years <= m1:
            t = (years - m0) / (m1 - m0)
            return r0 + t * (r1 - r0)
    return pts[-1][1]


# ── Tool 1: Current basket snapshot ────────────────────────────────────────

@mcp.tool()
def get_current_basket(contract: str = "TYM26") -> list[dict]:
    """Return the latest delivery basket snapshot from the database.

    Each bond in the basket is returned with its most recent implied repo,
    net basis, gross basis, and CTD flag. Sorted by implied repo descending
    (rank 1 = CTD).

    Args:
        contract: Futures contract identifier (e.g. "TYM26").

    Returns:
        List of dicts with keys: cusip, label, coupon, maturity,
        cash_price, conv_factor, gross_basis, net_basis,
        implied_repo_pct, is_ctd, snapshot_dt.
    """
    df = _db.get_current_basket(contract)
    if df.empty:
        return []

    # Enrich with human-readable label
    basket = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}

    records = []
    for _, row in df.iterrows():
        records.append({
            "cusip":           row["cusip"],
            "label":           label_map.get(row["cusip"], row["cusip"]),
            "coupon":          row.get("coupon"),
            "maturity":        str(row.get("maturity", "")),
            "cash_price":      row.get("cash_price"),
            "conv_factor":     row.get("conv_factor"),
            "gross_basis":     row.get("gross_basis"),
            "net_basis":       row.get("net_basis"),
            "implied_repo_pct": round(float(row["implied_repo"]) * 100, 4)
                                if row.get("implied_repo") is not None else None,
            "is_ctd":          bool(row.get("is_ctd")),
            "snapshot_dt":     str(row.get("snapshot_dt", "")),
        })
    return records


# ── Tool 2: Basis history for one bond ──────────────────────────────────────

@mcp.tool()
def get_basis_history(
    cusip: str,
    contract: str = "TYM26",
    days: int = 90,
) -> list[dict]:
    """Return net basis time-series with rolling 20-day average.

    Args:
        cusip:    Bond CUSIP identifier.
        contract: Futures contract identifier (e.g. "TYM26").
        days:     Number of trailing calendar days to return (default 90).

    Returns:
        List of daily dicts: snapshot_dt, net_basis, ma_20d, pct_rank.
    """
    df = _db.get_basis_history(cusip, contract, days)
    if df.empty:
        return []
    return [
        {
            "snapshot_dt": str(row["snapshot_dt"]),
            "net_basis":   row.get("net_basis"),
            "ma_20d":      row.get("ma_20d"),
            "pct_rank":    row.get("pct_rank"),
        }
        for _, row in df.iterrows()
    ]


# ── Tool 3: Basis percentile for the current CTD ────────────────────────────

@mcp.tool()
def get_basis_percentile(
    contract: str = "TYM26",
    days: int = 90,
) -> dict:
    """Where does today's CTD net basis sit in its historical distribution?

    Reports today's net basis, the 90-day min/max/mean, and the percentile
    rank (0 = historically tight, 1 = historically wide).

    Args:
        contract: Futures contract identifier (e.g. "TYM26").
        days:     Rolling window in calendar days (default 90).

    Returns:
        {cusip, label, snapshot_dt, net_basis, pct_rank,
         range_min, range_max, range_mean}
        or {"error": "..."} if no data.
    """
    df = _db.get_current_basket(contract)
    if df.empty:
        return {"error": "No snapshot data in database."}

    ctd_rows = df[df["is_ctd"] == 1]
    if ctd_rows.empty:
        return {"error": "No CTD bond found in latest snapshot."}

    ctd = ctd_rows.iloc[0]
    cusip = ctd["cusip"]
    history = _db.get_basis_history(cusip, contract, days)

    if history.empty:
        return {"error": f"No history for CTD {cusip}."}

    basket = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}

    latest = history.iloc[-1]
    return {
        "cusip":        cusip,
        "label":        label_map.get(cusip, cusip),
        "snapshot_dt":  str(latest["snapshot_dt"]),
        "net_basis":    latest.get("net_basis"),
        "pct_rank":     latest.get("pct_rank"),
        "range_min":    float(history["net_basis"].min()),
        "range_max":    float(history["net_basis"].max()),
        "range_mean":   float(history["net_basis"].mean()),
    }


# ── Tool 4: CTD transition log ───────────────────────────────────────────────

@mcp.tool()
def get_ctd_transitions(contract: str = "TYM26") -> list[dict]:
    """Return the log of historical CTD identity switches.

    Each record represents a date when the cheapest-to-deliver bond changed,
    with the implied repo spread at the time of the switch (narrower spread
    = the switch was close / unexpected).

    Args:
        contract: Futures contract identifier (e.g. "TYM26").

    Returns:
        List of dicts: change_dt, prev_ctd, new_ctd,
        implied_repo_spread_bps. Sorted newest first.
    """
    df = _db.get_ctd_transitions(contract)
    if df.empty:
        return []

    basket = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}

    records = []
    for _, row in df.iterrows():
        prev_cusip = row.get("prev_ctd_cusip") or ""
        new_cusip  = row.get("new_ctd_cusip")  or ""
        records.append({
            "change_dt":               str(row["change_dt"]),
            "prev_ctd":                label_map.get(prev_cusip, prev_cusip) or "—",
            "new_ctd":                 label_map.get(new_cusip,  new_cusip),
            "implied_repo_spread_bps": row.get("implied_repo_spread_bps"),
        })
    return records


# ── Tool 5: Transition proximity ─────────────────────────────────────────────

@mcp.tool()
def get_transition_proximity(contract: str = "TYM26") -> dict:
    """Implied repo spread between CTD and runner-up, with risk flag and trend.

    A narrowing spread signals elevated CTD transition risk.
    Risk flags: LOW (>15bps) | ELEVATED (5–15bps) | CRITICAL (<5bps).
    Trend compares today's spread to 5 days ago: NARROWING | WIDENING | STABLE.

    Args:
        contract: Futures contract identifier (e.g. "TYM26").

    Returns:
        {contract, ctd_cusip, runner_up_cusip, current_spread_bps,
         spread_5d/10d/20d_ago_bps, trend, risk_flag, risk_description,
         recent_snapshots[]}
        or {"error": "..."} if no data.
    """
    result = db_client.query_ctd_proximity(contract)
    if isinstance(result, str):
        return {"error": result}

    # Enrich with human-readable labels
    basket    = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}
    result["ctd_label"]      = label_map.get(result.get("ctd_cusip", ""), result.get("ctd_cusip", ""))
    result["runner_up_label"] = label_map.get(result.get("runner_up_cusip", ""), result.get("runner_up_cusip", ""))
    return result


# ── Tool 6: Scenario grid ─────────────────────────────────────────────────────

@mcp.tool()
def run_scenario_grid(
    contract: str = "TYM26",
    shifts_bps: list[int] | None = None,
) -> dict:
    """Re-rank the delivery basket under a range of parallel yield shifts.

    Reads the current basket snapshot from the database (futures price, repo
    rate, days to delivery) and uses the live FRED curve — linearly interpolated
    to each bond's remaining maturity — as the base yield for repricing.

    Yield input: FRED curve interpolated per bond maturity (first-order
    approximation; a production system would use bond-specific market yields).
    Futures price is held constant across scenarios — appropriate for a
    sensitivity grid where relative CTD ranking, not absolute price, is the output.

    Args:
        contract:   Futures contract identifier (e.g. "TYM26").
        shifts_bps: Parallel yield shifts to test (bps).
                    Defaults to [-100, -75, -50, -25, 0, 25, 50, 75, 100].

    Returns:
        {contract, base_futures_price, base_ctd_label, scenarios[]}
        Each scenario has shift_bps, ctd_label, ctd_implied_repo_pct,
        runner_label, runner_implied_repo_pct, spread_bps, ctd_changed.
    """
    from datetime import date as _date

    if shifts_bps is None:
        shifts_bps = [-100, -75, -50, -25, 0, 25, 50, 75, 100]

    # Pull current snapshot metadata from DB
    snapshot = db_client.query_basket_snapshot(contract)
    if isinstance(snapshot, str):
        return {"error": snapshot}
    if not snapshot:
        return {"error": f"No snapshot data for {contract}."}

    futures_price    = snapshot[0]["futures_price"]
    repo_rate        = snapshot[0]["repo_rate_pct"] / 100
    days_to_delivery = snapshot[0]["days_to_delivery"]

    if days_to_delivery <= 0:
        return {
            "error": "Contract near delivery — scenario results unreliable.",
            "days_to_delivery": days_to_delivery,
        }

    # Get live FRED curve for per-bond yield interpolation
    fred_curve = _try_get_fred_curve()
    if not fred_curve:
        return {"error": "FRED data unavailable — cannot run scenario grid."}

    basket    = get_basket(use_api=False)
    today     = _date.today()
    db_cusips = {r["cusip"] for r in snapshot}
    basket_subset = [b for b in basket if b["cusip"] in db_cusips]

    if not basket_subset:
        return {"error": "No basket bonds match the DB snapshot."}

    # Derive per-bond base yields from FRED curve
    base_yields: dict[str, float] = {}
    for bond in basket_subset:
        years_left = (bond["maturity"] - today).days / 365.25
        if years_left > 0:
            base_yields[bond["cusip"]] = _interp_yield(years_left, fred_curve)

    if not base_yields:
        return {"error": "Could not derive yields from FRED curve."}

    try:
        summary_df, _ = _scenario_grid(
            basket_subset,
            base_yields,
            futures_price,
            repo_rate,
            days_to_delivery,
            shifts_bps=shifts_bps,
            as_of=today,
        )
    except Exception as e:
        return {"error": f"Scenario grid failed: {e}"}

    scenarios = [
        {
            "shift_bps":               int(row["shift_bps"]),
            "ctd_label":               row["ctd_label"],
            "ctd_implied_repo_pct":    round(float(row["ctd_implied_repo"]) * 100, 4),
            "runner_label":            row["runner_label"],
            "runner_implied_repo_pct": round(float(row["runner_implied_repo"]) * 100, 4),
            "spread_bps":              round(float(row["spread_bps"]), 2),
            "ctd_changed":             bool(row["ctd_changed"]),
        }
        for _, row in summary_df.iterrows()
    ]

    base_row = next((s for s in scenarios if s["shift_bps"] == 0), scenarios[0])
    return {
        "contract":          contract,
        "base_futures_price": futures_price,
        "base_ctd_label":    base_row["ctd_label"],
        "note": (
            "Yields derived from FRED curve interpolated per bond maturity. "
            "Futures price held constant across scenarios (first-order approximation)."
        ),
        "scenarios": scenarios,
    }


# ── Tool 7: CTD transition threshold ─────────────────────────────────────────

@mcp.tool()
def get_ctd_transition_threshold(contract: str = "TYM26") -> dict:
    """Futures price at which the CTD identity would switch to the runner-up.

    Derived analytically from the cost-of-carry no-arbitrage equation by
    setting implied_repo_CTD(F*) = implied_repo_runner_up(F*) and solving
    for F* in closed form (see core.ctd.ctd_transition_threshold docstring).

    This is the most operationally important signal on a basis desk: it tells
    the short how far the futures price must move before the cheapest bond to
    deliver changes — affecting the hedge ratio and the delivery option value.

    Args:
        contract: Futures contract identifier (e.g. "TYM26").

    Returns:
        {contract, current_futures_price, ctd_label, runner_up_label,
         transition_threshold_futures_price, distance_to_threshold_pts,
         ctd_implied_repo_pct, runner_up_implied_repo_pct, spread_bps}
        or {"error": "..."} if insufficient data.
    """
    snapshot = db_client.query_basket_snapshot(contract)
    if isinstance(snapshot, str):
        return {"error": snapshot}
    if len(snapshot) < 2:
        return {"error": "Need at least 2 bonds to compute transition threshold."}

    ctd    = snapshot[0]
    runner = snapshot[1]

    basket    = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}

    try:
        threshold = _ctd_threshold(
            price_a=ctd["cash_price"],
            price_b=runner["cash_price"],
            cf_a=ctd["conv_factor"],
            cf_b=runner["conv_factor"],
            coupon_a=ctd["coupon_pct"] / 100,
            coupon_b=runner["coupon_pct"] / 100,
            days_to_delivery=ctd["days_to_delivery"],
        )
    except ZeroDivisionError:
        return {
            "error": (
                "Bonds have identical implied-repo slope (CF_A/P_A ≈ CF_B/P_B); "
                "no unique transition price exists."
            )
        }

    current_f   = ctd["futures_price"]
    distance    = round(threshold - current_f, 4)
    spread_bps  = round(
        (ctd["implied_repo_pct"] - runner["implied_repo_pct"]) * 100, 2
    )

    return {
        "contract":                          contract,
        "snapshot_dt":                       ctd["snapshot_dt"],
        "current_futures_price":             round(current_f, 4),
        "ctd_label":                         label_map.get(ctd["cusip"],    ctd["cusip"]),
        "runner_up_label":                   label_map.get(runner["cusip"], runner["cusip"]),
        "ctd_implied_repo_pct":              ctd["implied_repo_pct"],
        "runner_up_implied_repo_pct":        runner["implied_repo_pct"],
        "spread_bps":                        spread_bps,
        "transition_threshold_futures_price": round(threshold, 4),
        "distance_to_threshold_pts":         distance,
        "direction":                         _switch_direction(threshold, current_f),
        "note": (
            "threshold = F* at which implied_repo_CTD(F*) = implied_repo_runner_up(F*). "
            "Derived in closed form from the cost-of-carry no-arbitrage equation. "
            "direction: RALLY = futures must rise to trigger switch; "
            "SELLOFF = futures must fall; AT_THRESHOLD = switch is live now."
        ),
    }


# ── Tool 8: Carry and roll-down ───────────────────────────────────────────────

@mcp.tool()
def get_carry_roll(
    cusip: str,
    contract: str = "TYM26",
    repo_rate_pct: float | None = None,
) -> dict:
    """Carry and roll-down for a specific bond over 3M and 6M horizons.

    Carry = coupon accrual (ACT/365) minus repo financing cost (ACT/360).
    Roll-down = price appreciation as the bond rolls down the FRED yield
    curve over the holding period (price_bond at shorter maturity / rolled
    yield minus current price, as % of par).

    Yield inputs use the FRED curve linearly interpolated to each bond's
    remaining maturity — a first-order proxy appropriate for daily monitoring.

    Args:
        cusip:          Bond CUSIP identifier.
        contract:       Futures contract (e.g. "TYM26").
        repo_rate_pct:  Repo rate as a percentage (e.g. 5.3).
                        If None, uses the rate stored in the latest DB snapshot.

    Returns:
        {cusip, label, contract, coupon_pct, maturity, ytm_pct, repo_rate_pct,
         repo_source, current_net_basis_pts, current_net_basis_ticks,
         is_ctd, horizons: {"3M": {...}, "6M": {...}}}
    """
    from datetime import date as _date

    snapshot = db_client.query_basket_snapshot(contract)
    if isinstance(snapshot, str):
        return {"error": snapshot}

    bond_row = next((r for r in snapshot if r["cusip"] == cusip), None)
    if bond_row is None:
        return {"error": f"CUSIP {cusip} not found in latest {contract} snapshot."}

    basket   = get_basket(use_api=False)
    bond_def = next((b for b in basket if b["cusip"] == cusip), None)
    if bond_def is None:
        return {"error": f"CUSIP {cusip} not found in basket definition."}

    today      = _date.today()
    years_left = (bond_def["maturity"] - today).days / 365.25
    if years_left <= 0:
        return {"error": "Bond has matured."}

    # Derive current YTM from FRED curve (linearly interpolated)
    fred_curve = _try_get_fred_curve()
    if not fred_curve:
        return {"error": "FRED data unavailable — cannot compute carry/roll."}
    ytm = _interp_yield(years_left, fred_curve)

    # Repo rate: use parameter if provided, else DB snapshot value
    if repo_rate_pct is not None:
        repo_rate   = repo_rate_pct / 100
        repo_source = "param"
    else:
        repo_rate   = bond_row["repo_rate_pct"] / 100
        repo_source = "db"

    coupon     = bond_def["coupon"]
    cash_price = bond_row["cash_price"]

    horizons: dict[str, dict] = {}
    for label, days_held in [("3M", 91), ("6M", 182)]:
        hp_years = days_held / 365.0
        if hp_years >= years_left:
            continue

        # Carry: coupon accrual (ACT/365) minus repo financing (ACT/360)
        coupon_accrual_pct = coupon * (days_held / 365.0) * 100
        financing_cost_pct = repo_rate * (days_held / 360.0) * 100
        net_carry_pct      = coupon_accrual_pct - financing_cost_pct

        # Roll-down: reprice bond at (years_left − hp) using the rolled-down
        # FRED yield.  Price change is expressed as % of par (100 face).
        future_years = years_left - hp_years
        try:
            future_ytm    = _interp_yield(future_years, fred_curve)
            current_price = _price_bond(100.0, coupon, years_left, ytm)
            future_price  = _price_bond(100.0, coupon, future_years, future_ytm)
            roll_down_pct = future_price - current_price   # % of par
        except Exception:
            future_ytm    = ytm
            roll_down_pct = 0.0

        horizons[label] = {
            "coupon_accrual_pct":        round(coupon_accrual_pct, 4),
            "financing_cost_pct":        round(financing_cost_pct, 4),
            "net_carry_pct":             round(net_carry_pct, 4),
            "roll_down_pct":             round(roll_down_pct, 4),
            "total_carry_roll_pct":      round(net_carry_pct + roll_down_pct, 4),
            "forward_breakeven_ytm_pct": round(future_ytm * 100, 4),
        }

    label_map = {b["cusip"]: bond_label(b) for b in basket}
    return {
        "cusip":                   cusip,
        "label":                   label_map.get(cusip, cusip),
        "contract":                contract,
        "coupon_pct":              round(coupon * 100, 4),
        "maturity":                bond_def["maturity"].isoformat(),
        "years_to_maturity":       round(years_left, 4),
        "ytm_pct":                 round(ytm * 100, 4),
        "repo_rate_pct":           round(repo_rate * 100, 4),
        "repo_source":             repo_source,
        "current_net_basis_pts":   bond_row["net_basis_pts"],
        "current_net_basis_ticks": bond_row["net_basis_ticks"],
        "is_ctd":                  bond_row["is_ctd"],
        "horizons":                horizons,
        "note": (
            "YTM from FRED curve interpolated to bond maturity. "
            "Coupon accrual: ACT/365. Repo financing: ACT/360. "
            "Roll-down uses FRED curve interpolation (first-order approx)."
        ),
    }


# ── Tool 9: Full basket switch map ───────────────────────────────────────────

@mcp.tool()
def get_basket_switch_map(contract: str = "TYM26") -> list[dict] | dict:
    """Transition thresholds for every consecutive pair in the ranked basket.

    Unlike get_ctd_transition_threshold (which only covers CTD vs runner-up),
    this tool returns F* for *all* adjacent pairs — rank 1→2, 2→3, 3→4, etc.
    Results are sorted by |distance_pts| ascending so the nearest potential
    switch always appears first.

    This is useful for detecting compound risk: e.g. if bonds 2 and 3 are
    very close to switching while bond 1 is already near its threshold, a
    large yield move could cascade through the basket.

    Args:
        contract: Futures contract identifier (e.g. "TYM26").

    Returns:
        List of dicts sorted by |distance_pts| ascending, each containing:
            higher_rank, lower_rank, higher_cusip, lower_cusip,
            higher_label, lower_label, higher_ir (%), lower_ir (%),
            spread_bps, f_star, distance_pts, direction
        or {"error": "..."} if insufficient data.
    """
    snapshot = db_client.query_basket_snapshot(contract)
    if isinstance(snapshot, str):
        return {"error": snapshot}
    if len(snapshot) < 2:
        return {"error": "Need at least 2 bonds to compute switch map."}

    basket    = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}

    import pandas as pd
    df = pd.DataFrame(snapshot)
    # db_client stores implied_repo as percentage; convert to decimal for core functions
    df["implied_repo"]     = df["implied_repo_pct"] / 100
    df["coupon"]           = df["coupon_pct"] / 100
    df["days_to_delivery"] = df["days_to_delivery"].astype(int)
    df["label"]            = df["cusip"].map(label_map)
    df = df.drop(columns=["rank"], errors="ignore")
    df.index               = range(1, len(df) + 1)
    df.index.name          = "rank"

    try:
        switch_map = _basket_switch_map(df, float(df.iloc[0]["futures_price"]))
    except (ValueError, ZeroDivisionError) as exc:
        return {"error": str(exc)}

    # Replace raw cusips with human-readable labels in output
    for entry in switch_map:
        entry["higher_label"] = label_map.get(entry["higher_cusip"], entry["higher_label"])
        entry["lower_label"]  = label_map.get(entry["lower_cusip"],  entry["lower_label"])
        # Convert implied_repo back to percentage for consistency with other tools
        entry["higher_ir_pct"] = round(entry.pop("higher_ir") * 100, 4)
        entry["lower_ir_pct"]  = round(entry.pop("lower_ir")  * 100, 4)

    return switch_map


if __name__ == "__main__":
    mcp.run()
