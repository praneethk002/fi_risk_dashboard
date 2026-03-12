"""CTD Basis Monitor — MCP Server

Exposes six basis-desk tools so that Claude can synthesize a structured
morning brief from the historical basis database.

The genuine value here is not computation — that lives in core/ and data/.
It is synthesis: Claude reads the database via these tools and translates
quantitative signals (percentile rank, CTD transition proximity, scenario
output) into a narrative that would take a junior analyst 20 minutes to write.

Available tools
---------------
get_current_basket      Full delivery basket with implied repos, CTD flagged
get_basis_history       90-day net basis time-series for a specific bond
get_basis_percentile    Where today's CTD net basis sits in its 90-day range
get_ctd_transitions     Log of CTD switches + implied repo spread at switch
get_transition_proximity Current implied repo spread — CTD vs runner-up
run_scenario_grid       Basket re-ranking under parallel yield shifts

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
from core.basket import get_basket, bond_label
from core.scenario import scenario_grid as _scenario_grid

_db = BasisDB()
_db.init_schema()

mcp = FastMCP("ctd-basis-monitor")


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
    """Current implied repo spread between the CTD and the runner-up.

    A narrowing spread signals elevated CTD transition risk. Below 25bps
    is noteworthy; below 10bps warrants close monitoring.

    Args:
        contract: Futures contract identifier (e.g. "TYM26").

    Returns:
        {snapshot_dt, ctd_label, runner_label,
         ctd_implied_repo_pct, runner_implied_repo_pct,
         spread_bps, risk_level: "low"|"elevated"|"high"}
        or {"error": "..."} if insufficient data.
    """
    df = _db.get_transition_proximity(contract)
    if df.empty:
        return {"error": "Proximity data requires at least 2 bonds per snapshot."}

    latest = df.iloc[-1]
    spread = float(latest.get("spread_to_second_bps", 0) or 0)

    if spread < 10:
        risk = "high"
    elif spread < 25:
        risk = "elevated"
    else:
        risk = "low"

    basket = get_basket(use_api=False)
    label_map = {b["cusip"]: bond_label(b) for b in basket}

    # Get CTD and runner-up from current basket
    current = _db.get_current_basket(contract)
    ctd_label    = "—"
    runner_label = "—"
    ctd_ir       = None
    runner_ir    = None
    if not current.empty:
        ctd_rows = current[current["is_ctd"] == 1]
        if not ctd_rows.empty:
            ctd_cusip = ctd_rows.iloc[0]["cusip"]
            ctd_label = label_map.get(ctd_cusip, ctd_cusip)
            ctd_ir    = round(float(ctd_rows.iloc[0]["implied_repo"]) * 100, 4)
        non_ctd = current[current["is_ctd"] != 1]
        if not non_ctd.empty:
            runner_cusip = non_ctd.iloc[0]["cusip"]
            runner_label = label_map.get(runner_cusip, runner_cusip)
            runner_ir    = round(float(non_ctd.iloc[0]["implied_repo"]) * 100, 4)

    return {
        "snapshot_dt":            str(latest["snapshot_dt"]),
        "ctd_label":              ctd_label,
        "runner_label":           runner_label,
        "ctd_implied_repo_pct":   ctd_ir,
        "runner_implied_repo_pct": runner_ir,
        "spread_bps":             round(spread, 2),
        "risk_level":             risk,
    }


# ── Tool 6: Scenario grid ─────────────────────────────────────────────────────

@mcp.tool()
def run_scenario_grid(
    futures_price: float,
    repo_rate_pct: float,
    days_to_delivery: int,
    flat_yield_pct: float = 4.50,
    shifts_bps: list[int] | None = None,
) -> list[dict]:
    """Re-rank the delivery basket under a range of parallel yield shifts.

    For each shift, returns the CTD identity, its implied repo, the runner-up,
    and the spread. The 0bps row is the base case.

    Args:
        futures_price:      Quoted TY futures price (% of par).
        repo_rate_pct:      Repo financing rate as a percentage.
        days_to_delivery:   Calendar days to the delivery date.
        flat_yield_pct:     Flat yield used to price the basket (default 4.50).
        shifts_bps:         Yield shifts to test. Defaults to
                            [-100, -75, -50, -25, 0, 25, 50, 75, 100].

    Returns:
        List of dicts per shift: shift_bps, ctd_label, ctd_implied_repo_pct,
        runner_label, runner_implied_repo_pct, spread_bps, ctd_changed.
    """
    if shifts_bps is None:
        shifts_bps = [-100, -75, -50, -25, 0, 25, 50, 75, 100]

    basket = get_basket(use_api=False)
    base_yields = {b["cusip"]: flat_yield_pct / 100 for b in basket}

    summary_df, _ = _scenario_grid(
        basket,
        base_yields,
        futures_price,
        repo_rate_pct / 100,
        days_to_delivery,
        shifts_bps=shifts_bps,
    )

    return [
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


if __name__ == "__main__":
    mcp.run()
