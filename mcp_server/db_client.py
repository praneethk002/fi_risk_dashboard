"""
Read-only SQL query layer for the CTD basis monitor.

The MCP tools in server.py import from this module exclusively — they never
instantiate BasisDB or write SQL directly.  This separation keeps the tools
thin and ensures the SQL with window functions lives in one testable place.

The BasisDB.get_transition_proximity() method has a known issue: mixing
NTH_VALUE() with GROUP BY causes the window to collapse to one row per
partition, making NTH_VALUE(implied_repo, 2) always NULL.  The correct
approach — implemented here — uses ROW_NUMBER() in a CTE.

Unit conventions
----------------
  implied_repo  : percentage  (e.g. 5.23 for 5.23%)
  net_basis     : price points (1 point = 32 ticks for TY)
  net_basis_ticks: 32nds (tick convention for TY futures)
  spread_bps    : basis points
  coupon        : percentage
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from data.db import DEFAULT_DB_PATH

_NO_DATA = (
    "No data found. Run `python -m data.seed` (synthetic demo) "
    "or `python -m data.ingest` (live FRED data) first."
)


def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a read-optimised connection; raises FileNotFoundError if DB is absent."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. {_NO_DATA}"
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # non-blocking reads during ingest
    return conn


# ---------------------------------------------------------------------------
# Basket snapshot
# ---------------------------------------------------------------------------

def query_basket_snapshot(contract: str) -> list[dict] | str:
    """Latest snapshot for all bonds, ranked by implied_repo DESC (CTD first).

    carry is derived on the fly as gross_basis − net_basis (exact by definition).
    net_basis_ticks converts price points to 32nds (1 TY point = 32 ticks).
    """
    sql = """
        WITH latest_dt AS (
            SELECT MAX(snapshot_dt) AS max_dt
            FROM basis_snapshots
            WHERE contract = ?
        )
        SELECT bs.*
        FROM basis_snapshots bs
        JOIN latest_dt ON bs.snapshot_dt = latest_dt.max_dt
        WHERE bs.contract = ?
        ORDER BY bs.implied_repo DESC
    """
    try:
        conn = _connect()
    except FileNotFoundError as e:
        return str(e)

    try:
        rows = conn.execute(sql, (contract, contract)).fetchall()
    finally:
        conn.close()

    if not rows:
        return _NO_DATA

    result = []
    for i, row in enumerate(rows):
        gross_b = float(row["gross_basis"])
        net_b   = float(row["net_basis"])
        carry   = gross_b - net_b   # carry = gross_basis − net_basis by definition
        result.append({
            "rank":              i + 1,
            "cusip":             str(row["cusip"]),
            "coupon_pct":        round(float(row["coupon"]) * 100, 4),
            "maturity":          str(row["maturity"]),
            "cash_price":        round(float(row["cash_price"]), 4),
            "futures_price":     round(float(row["futures_price"]), 4),
            "conv_factor":       round(float(row["conv_factor"]), 4),
            "gross_basis_pts":   round(gross_b, 4),
            "carry_pts":         round(carry, 4),
            # Coupon accrual ACT/365; repo financing ACT/360 (US Treasury convention)
            "net_basis_pts":     round(net_b, 4),
            "net_basis_ticks":   round(net_b * 32, 2),  # 1 pt = 32 ticks (TY)
            "implied_repo_pct":  round(float(row["implied_repo"]) * 100, 4),
            "is_ctd":            bool(row["is_ctd"]),
            "repo_rate_pct":     round(float(row["repo_rate"]) * 100, 4),
            "days_to_delivery":  int(row["days_to_delivery"]),
            "snapshot_dt":       str(row["snapshot_dt"]),
        })
    return result


# ---------------------------------------------------------------------------
# Basis history for one bond
# ---------------------------------------------------------------------------

def query_basis_history(
    cusip: str,
    contract: str,
    lookback_days: int = 90,
) -> dict | str:
    """Time series of net basis and implied repo, with rolling 20-day MA.

    Returns the most recent `lookback_days` snapshots for the given CUSIP.
    PERCENT_RANK() over net_basis gives the current percentile (0–1).
    Requires SQLite >= 3.25.0 (ships with Python 3.10+).
    """
    sql = """
        WITH history AS (
            SELECT snapshot_dt, net_basis, implied_repo, is_ctd
            FROM basis_snapshots
            WHERE cusip = ? AND contract = ?
            ORDER BY snapshot_dt DESC
            LIMIT ?
        ),
        windowed AS (
            SELECT
                snapshot_dt,
                net_basis,
                implied_repo,
                is_ctd,
                AVG(net_basis) OVER (
                    ORDER BY snapshot_dt
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS ma_20d,
                PERCENT_RANK() OVER (ORDER BY net_basis) AS pct_rank
            FROM history
            ORDER BY snapshot_dt
        )
        SELECT * FROM windowed ORDER BY snapshot_dt
    """
    try:
        conn = _connect()
    except FileNotFoundError as e:
        return str(e)

    try:
        rows = conn.execute(sql, (cusip, contract, lookback_days)).fetchall()
    finally:
        conn.close()

    if not rows:
        return _NO_DATA

    series = [
        {
            "date":                  str(r["snapshot_dt"]),
            "net_basis_pts":         round(float(r["net_basis"]), 4),
            "net_basis_ticks":       round(float(r["net_basis"]) * 32, 2),
            "net_basis_20d_ma_pts":  round(float(r["ma_20d"]), 4)
                                     if r["ma_20d"] is not None else None,
            "implied_repo_pct":      round(float(r["implied_repo"]) * 100, 4),
        }
        for r in rows
    ]

    last = rows[-1]
    return {
        "cusip":                      cusip,
        "contract":                   contract,
        "lookback_days":              lookback_days,
        "current_net_basis_pts":      round(float(last["net_basis"]), 4),
        "current_net_basis_ticks":    round(float(last["net_basis"]) * 32, 2),
        "current_implied_repo_pct":   round(float(last["implied_repo"]) * 100, 4),
        "current_net_basis_pctile":   round(float(last["pct_rank"]) * 100, 1),
        "units": {
            "net_basis": "price_points",
            "net_basis_ticks": "32nds (1 TY point = 32 ticks)",
            "implied_repo": "percentage",
        },
        "series": series,
    }


# ---------------------------------------------------------------------------
# CTD proximity  (corrected — uses ROW_NUMBER(), not NTH_VALUE + GROUP BY)
# ---------------------------------------------------------------------------

def query_ctd_proximity(contract: str) -> dict | str:
    """Implied repo spread between CTD (rank 1) and runner-up (rank 2) per day.

    Returns the last 21 days so callers can compute 5d/10d/20d trend.

    The earlier BasisDB.get_transition_proximity() mixed NTH_VALUE() with
    GROUP BY, collapsing each PARTITION BY snapshot_dt to a single row and
    making NTH_VALUE(implied_repo, 2) always NULL.  This query uses
    ROW_NUMBER() in a CTE to correctly identify rank-1 and rank-2 per day.
    """
    sql = """
        WITH ranked AS (
            SELECT
                snapshot_dt,
                cusip,
                implied_repo,
                ROW_NUMBER() OVER (
                    PARTITION BY snapshot_dt
                    ORDER BY implied_repo DESC
                ) AS rnk
            FROM basis_snapshots
            WHERE contract = ?
        ),
        spread AS (
            SELECT
                ctd.snapshot_dt,
                ctd.cusip    AS ctd_cusip,
                runner.cusip AS runner_cusip,
                (ctd.implied_repo - runner.implied_repo) * 10000 AS spread_bps
            FROM ranked ctd
            JOIN ranked runner
                ON  ctd.snapshot_dt  = runner.snapshot_dt
                AND ctd.rnk          = 1
                AND runner.rnk       = 2
        )
        SELECT * FROM spread
        ORDER BY snapshot_dt DESC
        LIMIT 21
    """
    try:
        conn = _connect()
    except FileNotFoundError as e:
        return str(e)

    try:
        rows = conn.execute(sql, (contract,)).fetchall()
    finally:
        conn.close()

    if not rows:
        return _NO_DATA

    def _bps(idx: int) -> float | None:
        if idx < len(rows):
            v = rows[idx]["spread_bps"]
            return round(float(v), 2) if v is not None else None
        return None

    current = _bps(0)
    spread_5d  = _bps(5)
    spread_10d = _bps(10)
    spread_20d = _bps(20)

    # Trend: compare current to 5 days ago
    if current is not None and spread_5d is not None:
        delta = current - spread_5d
        trend = "NARROWING" if delta < -2 else "WIDENING" if delta > 2 else "STABLE"
    else:
        trend = "UNKNOWN"

    # Risk flag and human-readable description
    if current is None:
        risk_flag = "UNKNOWN"
        risk_desc = "Insufficient data to assess CTD transition risk."
    elif current < 5:
        risk_flag = "CRITICAL"
        risk_desc = (
            f"Spread has collapsed to {current:.1f}bps. CTD switch is imminent — "
            "the futures short is near-indifferent between bonds."
        )
    elif current < 15:
        risk_flag = "ELEVATED"
        risk_desc = (
            f"Spread has narrowed to {current:.1f}bps. "
            "Monitor for CTD switch around data releases or yield moves."
        )
    else:
        risk_flag = "LOW"
        risk_desc = (
            f"CTD is dominant with {current:.1f}bps spread. "
            "Delivery option value is low; CTD switch not imminent."
        )

    return {
        "contract":            contract,
        "ctd_cusip":           str(rows[0]["ctd_cusip"]),
        "runner_up_cusip":     str(rows[0]["runner_cusip"]),
        "current_spread_bps":  current,
        "spread_5d_ago_bps":   spread_5d,
        "spread_10d_ago_bps":  spread_10d,
        "spread_20d_ago_bps":  spread_20d,
        "trend":               trend,
        "risk_flag":           risk_flag,
        "risk_description":    risk_desc,
        "recent_snapshots": [
            {
                "date":       str(r["snapshot_dt"]),
                "spread_bps": round(float(r["spread_bps"]), 2),
            }
            for r in rows[:10]
        ],
    }
