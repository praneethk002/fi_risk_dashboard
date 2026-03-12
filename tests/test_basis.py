"""
Basis tests — prints what's happening so you can read and interpret the output.
Run with: pytest tests/test_basis.py -v -s
"""

from datetime import date
from core.basket import get_basket
from core.basis import gross_basis, carry, net_basis, implied_repo, find_ctd, basket_analysis


# ---------------------------------------------------------------------------
# Shared inputs used across multiple tests
# ---------------------------------------------------------------------------

FUTURES_PRICE    = 108.50
REPO_RATE        = 0.053   # 5.3% repo
DAYS_TO_DELIVERY = 110


def test_gross_basis_intuition():
    """Show gross basis for bonds priced above, at, and below invoice price."""
    print("\n--- Gross Basis = cash_price - futures_price × conv_factor ---")
    print(f"  Futures price: {FUTURES_PRICE}  Conv factor: 0.9750")
    print(f"  Invoice price = {FUTURES_PRICE} × 0.9750 = {FUTURES_PRICE * 0.9750:.4f}")
    print()

    cases = [
        (100.00, "cash above invoice → positive basis (bond rich vs futures)"),
        (105.79, "cash equals invoice → zero basis"),
        (95.00,  "cash below invoice → negative basis (bond cheap vs futures)"),
    ]
    print(f"  {'Cash price':>12}  {'Gross basis':>12}  Interpretation")
    for price, note in cases:
        gb = gross_basis(price, FUTURES_PRICE, 0.9750)
        print(f"  {price:>12.4f}  {gb:>12.6f}  {note}")


def test_carry_intuition():
    """Show carry decomposition: coupon income minus financing cost."""
    price, coupon, repo, days = 99.50, 0.045, REPO_RATE, DAYS_TO_DELIVERY

    coupon_income   = price * coupon * (days / 365)
    financing_cost  = price * repo   * (days / 360)
    net_carry       = carry(price, coupon, repo, days)

    print("\n--- Carry over the holding period ---")
    print(f"  Cash price:       {price}")
    print(f"  Coupon rate:      {coupon*100:.2f}%  (ACT/365)")
    print(f"  Repo rate:        {repo*100:.2f}%   (ACT/360)")
    print(f"  Days to delivery: {days}")
    print()
    print(f"  Coupon income  = {price} × {coupon} × ({days}/365) = {coupon_income:.4f}")
    print(f"  Financing cost = {price} × {repo} × ({days}/360) = {financing_cost:.4f}")
    print(f"  Net carry      = {coupon_income:.4f} - {financing_cost:.4f} = {net_carry:.4f}")
    print()
    if net_carry > 0:
        print("  Positive carry: coupon income > financing cost, position earns money")
    else:
        print("  Negative carry: financing cost > coupon income, position costs money")


def test_net_basis_decomposition():
    """Show that net_basis = gross_basis - carry, and what each component means."""
    price, coupon, cf = 99.50, 0.045, 0.9195

    gb = gross_basis(price, FUTURES_PRICE, cf)
    c  = carry(price, coupon, REPO_RATE, DAYS_TO_DELIVERY)
    nb = net_basis(price, FUTURES_PRICE, cf, coupon, REPO_RATE, DAYS_TO_DELIVERY)

    print("\n--- Net Basis Decomposition ---")
    print(f"  Gross basis  = {gb:>8.4f}  (raw gap between cash and futures invoice)")
    print(f"  Carry        = {c:>8.4f}  (coupon income minus repo cost)")
    print(f"  Net basis    = {nb:>8.4f}  = gross_basis - carry")
    print(f"  Check:         {gb - c:>8.4f}  (should match net basis exactly)")
    print()
    print("  Net basis near zero → bond fairly priced vs futures")
    print("  Net basis > zero    → bond rich, or delivery option has value")


def test_implied_repo_vs_actual():
    """Compare implied repo against the actual repo rate to assess richness/cheapness."""
    cases = [
        (99.50, 0.9195, 0.045, "high-coupon bond"),
        (99.00, 0.9014, 0.040, "low-coupon bond"),
        (99.25, 0.8808, 0.0425,"mid-coupon bond"),
    ]

    print("\n--- Implied Repo vs Actual Repo ---")
    print(f"  Actual repo rate: {REPO_RATE*100:.2f}%")
    print()
    print(f"  {'Bond':<20} {'Implied repo':>14} {'vs actual':>12}  Signal")
    for price, cf, coupon, label in cases:
        ir = implied_repo(price, FUTURES_PRICE, cf, coupon, DAYS_TO_DELIVERY)
        diff_bps = (ir - REPO_RATE) * 10_000
        signal = "CHEAP (deliver this)" if ir > REPO_RATE else "RICH  (don't deliver)"
        print(f"  {label:<20} {ir*100:>13.3f}%  {diff_bps:>+10.1f}bp  {signal}")


def test_find_ctd():
    """Show which bond is CTD and why."""
    bonds = [
        {"cash_price": 99.375, "conversion_factor": 0.8830, "coupon_rate": 0.04375, "label": "4.375% Nov-34"},
        {"cash_price": 99.625, "conversion_factor": 0.9195, "coupon_rate": 0.04625, "label": "4.625% Feb-35"},
        {"cash_price": 99.000, "conversion_factor": 0.9014, "coupon_rate": 0.04000, "label": "4.0%   Feb-33"},
    ]

    print("\n--- CTD Selection ---")
    print(f"  Futures price: {FUTURES_PRICE}  Days to delivery: {DAYS_TO_DELIVERY}")
    print()
    print(f"  {'Bond':<18} {'Implied repo':>14}  Rank")

    repos = [
        (b["label"], implied_repo(b["cash_price"], FUTURES_PRICE, b["conversion_factor"], b["coupon_rate"], DAYS_TO_DELIVERY))
        for b in bonds
    ]
    repos.sort(key=lambda x: x[1], reverse=True)
    for i, (label, ir) in enumerate(repos, 1):
        tag = "  ← CTD (highest implied repo)" if i == 1 else ""
        print(f"  {label:<18} {ir*100:>13.3f}%  #{i}{tag}")

    ctd = find_ctd(bonds, FUTURES_PRICE, DAYS_TO_DELIVERY)
    print(f"\n  find_ctd() returns: {ctd['label']}  (implied repo = {ctd['implied_repo']*100:.3f}%)")


def test_basket_analysis_full():
    """Run basket_analysis() on the full TYM26 basket and print the ranked table."""
    basket = get_basket(use_api=False)
    cash_prices = {b["cusip"]: round(95.0 + b["coupon"] * 100, 3) for b in basket}

    df = basket_analysis(basket, cash_prices, FUTURES_PRICE, REPO_RATE, DAYS_TO_DELIVERY)

    print(f"\n--- Full Basket Analysis (TYM26, futures={FUTURES_PRICE}, repo={REPO_RATE*100:.2f}%, days={DAYS_TO_DELIVERY}) ---")
    print()
    print(f"  {'Rank':<5} {'Bond':<18} {'Cash px':>8} {'CF':>7} {'Gross':>8} {'Carry':>8} {'Net':>8} {'Impl repo':>10}  CTD?")
    print("  " + "-" * 85)
    for rank, row in df.iterrows():
        ctd_flag = " ← CTD" if row["is_ctd"] else ""
        print(
            f"  {rank:<5} {row['label']:<18} {row['cash_price']:>8.3f} {row['conv_factor']:>7.4f} "
            f"{row['gross_basis']:>8.4f} {row['carry']:>8.4f} {row['net_basis']:>8.4f} "
            f"{row['implied_repo']*100:>9.3f}%{ctd_flag}"
        )

    ctd_row = df[df["is_ctd"]].iloc[0]
    runner  = df[df.index == 2].iloc[0]
    spread  = (ctd_row["implied_repo"] - runner["implied_repo"]) * 10_000
    print(f"\n  CTD:    {ctd_row['label']}")
    print(f"  Runner: {runner['label']}")
    print(f"  CTD/runner spread: {spread:.1f}bp implied repo")
