"""
Scenario tests — prints readable output showing CTD switching under yield shocks.
Run with: pytest tests/test_scenario.py -v -s
"""

from core.basket import get_basket
from core.basis import ctd_scenario

FUTURES_PRICE    = 108.50
REPO_RATE        = 0.053
DAYS_TO_DELIVERY = 110

# Approximate current 10-year yield for each bond (using a flat 4.5% curve)
def make_base_yields(basket, flat_yield=0.045):
    return {b["cusip"]: flat_yield for b in basket}


def test_ctd_switching():
    """Show which bond is CTD at each yield shift, and where the CTD switches."""
    basket      = get_basket(use_api=False)
    base_yields = make_base_yields(basket)

    summary, _ = ctd_scenario(
        basket, base_yields, FUTURES_PRICE, REPO_RATE, DAYS_TO_DELIVERY,
        shifts_bps=[-100, -75, -50, -25, 0, 25, 50, 75, 100],
    )

    print("\n--- CTD Under Parallel Yield Shifts ---")
    print(f"  Base yield: 4.50%  Futures: {FUTURES_PRICE}  Repo: {REPO_RATE*100:.2f}%  Days: {DAYS_TO_DELIVERY}")
    print()
    print(f"  {'Shift':>8}  {'CTD bond':<18}  {'CTD impl repo':>14}  {'Runner-up':<18}  {'Spread':>8}  Changed?")
    print("  " + "-" * 90)

    for _, row in summary.iterrows():
        changed = "  <-- SWITCH" if row["ctd_changed"] else ""
        print(
            f"  {row['shift_bps']:>+7}bp  {row['ctd_label']:<18}  "
            f"{row['ctd_implied_repo']*100:>13.3f}%  {row['runner_label']:<18}  "
            f"{row['spread_bps']:>7.1f}bp{changed}"
        )

    switches = summary[summary["ctd_changed"]]
    print()
    if switches.empty:
        print("  No CTD switch within this shift range.")
    else:
        print(f"  CTD switches at: {list(switches['shift_bps'].values)} bps")


def test_implied_repo_heatmap():
    """Print the full implied repo grid (all bonds × all shifts)."""
    basket      = get_basket(use_api=False)
    base_yields = make_base_yields(basket)

    _, heatmap = ctd_scenario(
        basket, base_yields, FUTURES_PRICE, REPO_RATE, DAYS_TO_DELIVERY,
        shifts_bps=[-100, -50, 0, 50, 100],
    )

    print("\n--- Implied Repo Heatmap (%) — rows=bond, cols=yield shift ---")
    print(f"  {'Bond':<18}", end="")
    for col in heatmap.columns:
        print(f"  {col:>+7}bp", end="")
    print()
    print("  " + "-" * (18 + len(heatmap.columns) * 11 + 2))

    for bond, row in heatmap.iterrows():
        print(f"  {bond:<18}", end="")
        for val in row:
            print(f"  {val:>9.3f}%", end="")
        print()

    print()
    print("  Interpretation:")
    print("  - Higher implied repo → bond is cheaper to deliver at that yield level")
    print("  - The bond with the highest value in each column is the CTD")
    print("  - As yields fall, longer-duration bonds tend to become CTD")
    print("  - As yields rise, shorter-duration bonds tend to become CTD")
