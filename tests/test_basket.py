"""
Basket tests — prints what's happening so you can read and interpret the output.
Run with: pytest tests/test_basket.py -v -s
"""

from datetime import date
from core.basket import conversion_factor, get_basket, bond_label, MIN_MATURITY, MAX_MATURITY


def test_conversion_factor_by_coupon():
    """Show how CF changes as coupon moves above and below the 6% base rate."""
    cases = [
        (0.03,   date(2034, 11, 15), "low coupon  → CF well below 1"),
        (0.04375,date(2034, 11, 15), "typical TY bond coupon"),
        (0.06,   date(2034, 11, 15), "6% base rate → CF should be ~1"),
        (0.07,   date(2034, 11, 15), "high coupon → CF above 1"),
    ]
    print("\n--- Conversion Factor vs Coupon (same maturity Nov-34) ---")
    print(f"  {'Coupon':>8}  {'CF':>8}  Note")
    for coupon, mat, note in cases:
        cf = conversion_factor(coupon, mat)
        print(f"  {coupon*100:>7.2f}%  {cf:>8.4f}  {note}")


def test_conversion_factor_by_maturity():
    """Show how CF changes as maturity extends (for a fixed sub-6% coupon)."""
    coupon = 0.04375
    maturities = [
        date(2033,  2, 15),
        date(2034,  5, 15),
        date(2035,  2, 15),
        date(2036,  5, 15),
    ]
    print(f"\n--- Conversion Factor vs Maturity (coupon={coupon*100:.3g}%) ---")
    print(f"  {'Maturity':<14}  {'CF':>8}  Note")
    for mat in maturities:
        cf = conversion_factor(coupon, mat)
        note = "longer maturity → more discounting → lower CF" if mat == maturities[-1] else ""
        print(f"  {mat.strftime('%b %Y'):<14}  {cf:>8.4f}  {note}")


def test_basket_contents():
    """Print the full TYM26 deliverable basket with eligibility check."""
    basket = get_basket(use_api=False)

    print(f"\n--- TYM26 Deliverable Basket ({len(basket)} bonds) ---")
    print(f"  Eligibility window: {MIN_MATURITY} to {MAX_MATURITY}")
    print()
    print(f"  {'#':<4} {'Label':<18} {'CUSIP':<12} {'Coupon':>8} {'Maturity':<14} {'CF':>8} {'In window?'}")
    print("  " + "-" * 78)

    for i, bond in enumerate(basket, 1):
        in_window = MIN_MATURITY <= bond["maturity"] <= MAX_MATURITY
        flag = "YES" if in_window else "NO  <-- PROBLEM"
        print(
            f"  {i:<4} {bond_label(bond):<18} {bond['cusip']:<12} "
            f"{bond['coupon']*100:>7.3f}%  {bond['maturity'].strftime('%Y-%m-%d'):<14} "
            f"{bond['conv_factor']:>8.4f}  {flag}"
        )


def test_bond_label_format():
    """Show what bond_label() produces for a few bonds."""
    examples = [
        {"cusip": "AAA", "coupon": 0.04375, "maturity": date(2034, 11, 15)},
        {"cusip": "BBB", "coupon": 0.04000, "maturity": date(2033,  2, 15)},
        {"cusip": "CCC", "coupon": 0.06000, "maturity": date(2035,  5, 15)},
    ]
    print("\n--- Bond Label Format ---")
    for b in examples:
        print(f"  coupon={b['coupon']*100:.3g}%  maturity={b['maturity']}  →  label='{bond_label(b)}'")
