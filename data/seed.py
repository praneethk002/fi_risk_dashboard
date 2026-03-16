"""
Synthetic history seeder for the CTD basis monitor.

Generates 90 business days of simulated TYM26 basket snapshots using a
seeded random walk on the 10-year Treasury yield, then writes them to the
SQLite database.

This is a development/demo tool — production data comes from data/ingest.py.
Use this to pre-populate the database when no FRED API key is available or
when you want a fully reproducible demo dataset.

Usage
-----
    python -m data.seed              # seed 90 days (default)
    python -m data.seed --days 120   # seed 120 days
    python -m data.seed --reset      # clear existing TYM26 data then re-seed
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from core.basket import get_basket, DELIVERY_DATE
from core.ctd import rank_basket
from core.pricing import price_bond
from data.db import BasisDB, DEFAULT_DB_PATH

# ---------------------------------------------------------------------------
# Representative market parameters (realistic for TYM26 as of early 2026)
# At 4.50% yield, TY futures fair-value is ~112.00.
# Repo rate reflects the prevailing GC repo rate.
# ---------------------------------------------------------------------------

_BASE_10Y_YIELD: float = 0.0450     # 4.50% — base 10-year yield
_REPO_RATE: float     = 0.0530      # 5.30% — overnight GC repo
# Fair-value futures price at base yield (4.5%) with 107 days to delivery:
# F_fair = (cash_price + coupon_accrual - repo_cost) / CF
#        ≈ (97.0 + 1.1 - 1.5) / 0.902 ≈ 108.0
# With repo > coupon, gross basis is slightly negative at fair value.
_BASE_FUTURES_PRICE: float = 108.00

# Random walk parameters
_RNG_SEED: int   = 42
_DAILY_STD_BPS   = 7.0   # std dev of daily yield change — large enough to
                          # produce a handful of CTD transitions over 90 days
_MAX_DRIFT_BPS   = 60.0  # clamp cumulative drift so yields stay plausible

# TY futures DV01: ~0.085 price points per basis point of yield.
# Used to scale the futures price with yield changes.
_TY_DV01_PER_BP: float = 0.085


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _business_days_back(n: int, reference: date = date.today()) -> list[date]:
    """Return a list of n business days ending the day before reference."""
    days: list[date] = []
    d = reference - timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:  # Mon–Fri
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def _yield_series(n_days: int, rng: np.random.Generator) -> np.ndarray:
    """Generate a mean-reverting random walk ending at the base yield.

    Returns an array of shape (n_days,) of 10-year yields (decimal),
    oldest first.  The final value equals _BASE_10Y_YIELD exactly so
    that the "today" snapshot always reflects the configured base.
    """
    increments = rng.normal(0.0, _DAILY_STD_BPS, n_days)
    cumulative = np.cumsum(increments)
    # Clamp to avoid extreme yields
    cumulative = np.clip(cumulative, -_MAX_DRIFT_BPS, +_MAX_DRIFT_BPS)
    # Shift so the last day has zero offset (= base yield)
    cumulative -= cumulative[-1]
    return _BASE_10Y_YIELD + cumulative / 10_000


def _price_bond_simple(
    coupon: float,
    maturity: date,
    as_of: date,
    yield_: float,
) -> float | None:
    """Price a bond using core.pricing.price_bond, returning None on failure."""
    years_left = (maturity - as_of).days / 365.25
    if years_left <= 0.1:
        return None
    try:
        return price_bond(100.0, coupon, years_left, yield_)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core seeder
# ---------------------------------------------------------------------------

def _clear_contract(db_path: Path, contract: str) -> None:
    """Delete all rows for a contract from both tables."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM basis_snapshots WHERE contract = ?", (contract,))
        conn.execute("DELETE FROM ctd_log WHERE contract = ?", (contract,))
        conn.commit()
        print(f"Cleared existing {contract} data from {db_path}.")
    finally:
        conn.close()


def seed(
    days: int = 90,
    contract: str = "TYM26",
    reset: bool = False,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Seed the database with synthetic basis history.

    Args:
        days:     Number of business days of history to generate.
        contract: Futures contract label (default "TYM26").
        reset:    If True, delete existing rows for this contract first.
        db_path:  Path to the SQLite database.

    Returns:
        Total number of snapshot rows written.
    """
    db = BasisDB(db_path)
    db.init_schema()

    if reset:
        _clear_contract(db_path, contract)

    basket = get_basket(use_api=False)
    rng    = np.random.default_rng(seed=_RNG_SEED)

    business_days  = _business_days_back(days)
    yield_series   = _yield_series(len(business_days), rng)

    total_rows   = 0
    prev_ctd     = None  # track for transition detection (handled inside BasisDB)

    print(f"Seeding {len(business_days)} days of {contract} history → {db_path}")

    for i, snapshot_date in enumerate(business_days):
        ten_y = float(yield_series[i])
        yield_shift_bps = (ten_y - _BASE_10Y_YIELD) * 10_000

        # Scale futures price with yield (negative relationship)
        futures_price = _BASE_FUTURES_PRICE - _TY_DV01_PER_BP * yield_shift_bps

        days_to_deliv = max(1, (DELIVERY_DATE - snapshot_date).days)

        # Price each bond at the current yield.
        # All basket bonds are 6.5–10 years to the delivery month, so using
        # the single 10Y yield as the discount rate is a reasonable proxy.
        bond_prices: dict[str, float] = {}
        for bond in basket:
            p = _price_bond_simple(bond["coupon"], bond["maturity"], snapshot_date, ten_y)
            if p is not None:
                bond_prices[bond["cusip"]] = p

        if not bond_prices:
            continue

        try:
            ranked_df = rank_basket(
                basket,
                futures_price,
                bond_prices,
                _REPO_RATE,
                days_to_deliv,
            )
        except ValueError:
            continue

        n = db.write_snapshot(
            snapshot_date,
            contract,
            ranked_df,
            _REPO_RATE,
            days_to_deliv,
            futures_price,
        )
        total_rows += n

        # Print progress every 10 days and on CTD changes
        ctd_cusip = ranked_df[ranked_df["is_ctd"]]["cusip"].iloc[0]
        if ctd_cusip != prev_ctd:
            label = ranked_df[ranked_df["is_ctd"]]["label"].iloc[0]
            print(
                f"  {snapshot_date}  CTD → {label}  "
                f"(10Y={ten_y*100:.3f}%  F={futures_price:.3f})"
            )
            prev_ctd = ctd_cusip
        elif i % 10 == 0:
            ir = ranked_df[ranked_df["is_ctd"]]["implied_repo"].iloc[0]
            print(
                f"  {snapshot_date}  10Y={ten_y*100:.3f}%  "
                f"implied_repo={ir*100:.3f}%"
            )

    print(f"\nDone. Wrote {total_rows} snapshot rows.")
    return total_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the CTD basis database with synthetic TYM26 history.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--days", type=int, default=90,
        help="Number of business days to seed (default: 90)",
    )
    parser.add_argument(
        "--contract", default="TYM26",
        help="Futures contract label (default: TYM26)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear existing rows for this contract before seeding",
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH,
        metavar="PATH",
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )

    args = parser.parse_args()
    seed(days=args.days, contract=args.contract, reset=args.reset, db_path=args.db)


if __name__ == "__main__":
    main()
