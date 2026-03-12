"""
Cash-futures basis analytics for Treasury bond futures.

Key concepts:
  - Gross basis  = cash price − futures price × conversion factor
  - Carry        = coupon income − repo financing cost over the holding period
  - Net basis    = gross basis − carry
  - Implied repo = the financing rate implied by the cash-futures relationship
  - CTD          = the bond in the delivery basket with the highest implied repo
                   (cheapest for the short to acquire and deliver)

Price conventions
-----------------
Cash and futures prices are expressed as a percentage of face value
(e.g. 98.50 means 98.50% of par).

Day count conventions
---------------------
Coupon accrual uses ACT/365; repo financing uses ACT/360 (US market convention).
"""

from __future__ import annotations

import pandas as pd


def gross_basis(
    cash_price: float,
    futures_price: float,
    conversion_factor: float,
) -> float:
    """Gross basis: difference between cash price and futures invoice price.

    Args:
        cash_price: Clean cash price as a percentage of par.
        futures_price: Quoted futures price as a percentage of par.
        conversion_factor: CBOT/CME conversion factor for the specific bond.

    Returns:
        Gross basis in price points.
    """
    return cash_price - futures_price * conversion_factor


def carry(
    cash_price: float,
    coupon_rate: float,
    repo_rate: float,
    days_to_delivery: int,
) -> float:
    """Carry: net income from holding the bond and financing via repo.

    Carry = coupon accrual (ACT/365) − repo financing cost (ACT/360).
    A positive carry means the position generates income.

    Args:
        cash_price: Clean cash price as a percentage of par.
        coupon_rate: Annual coupon rate as a decimal.
        repo_rate: Overnight/term repo rate as a decimal.
        days_to_delivery: Calendar days to futures delivery.

    Returns:
        Carry in price points.
    """
    coupon_income = cash_price * coupon_rate * (days_to_delivery / 365)
    financing_cost = cash_price * repo_rate * (days_to_delivery / 360)
    return coupon_income - financing_cost


def net_basis(
    cash_price: float,
    futures_price: float,
    conversion_factor: float,
    coupon_rate: float,
    repo_rate: float,
    days_to_delivery: int,
) -> float:
    """Net basis: gross basis minus carry.

    For the CTD bond, net basis ≈ 0 in a fair-value world; any residual
    reflects the embedded delivery option and other frictions.

    Args:
        cash_price: Clean cash price as a percentage of par.
        futures_price: Quoted futures price as a percentage of par.
        conversion_factor: Conversion factor for the bond.
        coupon_rate: Annual coupon rate as a decimal.
        repo_rate: Repo rate as a decimal.
        days_to_delivery: Calendar days to futures delivery.

    Returns:
        Net basis in price points.
    """
    gb = gross_basis(cash_price, futures_price, conversion_factor)
    c = carry(cash_price, coupon_rate, repo_rate, days_to_delivery)
    return gb - c


def implied_repo(
    cash_price: float,
    futures_price: float,
    conversion_factor: float,
    coupon_rate: float,
    days_to_delivery: int,
) -> float:
    """Implied repo rate from the cash-futures cost-of-carry relationship.

    Derived by inverting the carry formula:
        implied_repo = [(invoice_price + coupon_accrual − cash_price)
                        / cash_price] × (360 / days)

    where invoice_price = futures_price × conversion_factor.

    Args:
        cash_price: Clean cash price as a percentage of par.
        futures_price: Quoted futures price as a percentage of par.
        conversion_factor: Conversion factor for the bond.
        coupon_rate: Annual coupon rate as a decimal.
        days_to_delivery: Calendar days to futures delivery.

    Returns:
        Implied repo rate as a decimal.
    """
    invoice_price = futures_price * conversion_factor
    coupon_accrual = cash_price * coupon_rate * (days_to_delivery / 365)
    numerator = invoice_price + coupon_accrual - cash_price
    return (numerator / cash_price) * (360 / days_to_delivery)


def find_ctd(
    bonds: list[dict],
    futures_price: float,
    days_to_delivery: int,
) -> dict:
    """Identify the cheapest-to-deliver (CTD) bond.

    The CTD is the bond the futures short will choose to deliver because it
    maximises the implied repo rate (equivalently, minimises the cost of
    acquiring the bond relative to the futures invoice received).

    Args:
        bonds: List of dicts, each with keys:
               - "cash_price" (float): clean price as % of par
               - "conversion_factor" (float): CME/CBOT conversion factor
               - "coupon_rate" (float): annual coupon as a decimal
               - "label" (str, optional): human-readable identifier
        futures_price: Quoted futures price as a percentage of par.
        days_to_delivery: Calendar days to futures delivery.

    Returns:
        The entry from ``bonds`` with the highest implied repo rate, augmented
        with an "implied_repo" key.

    Raises:
        ValueError: If ``bonds`` is empty.
    """
    if not bonds:
        raise ValueError("bonds list must not be empty")

    results = [
        {
            **bond,
            "implied_repo": implied_repo(
                bond["cash_price"],
                futures_price,
                bond["conversion_factor"],
                bond["coupon_rate"],
                days_to_delivery,
            ),
        }
        for bond in bonds
    ]
    return max(results, key=lambda b: b["implied_repo"])


def basket_analysis(
    basket: list[dict],
    cash_prices: dict[str, float],
    futures_price: float,
    repo_rate: float,
    days_to_delivery: int,
) -> pd.DataFrame:
    """Run full basis analytics across the deliverable basket.

    Bridges the basket dicts from core.basket (keys: cusip, coupon,
    maturity, conv_factor) with the basis functions, then returns a
    DataFrame ranked by implied repo (CTD first).

    Args:
        basket:           List of bond dicts from core.basket.get_basket().
        cash_prices:      Dict mapping cusip → clean cash price (% of par).
        futures_price:    Quoted futures price (% of par).
        repo_rate:        Financing rate as a decimal (e.g. 0.053).
        days_to_delivery: Calendar days to futures delivery date.

    Returns:
        DataFrame with one row per bond, sorted by implied_repo descending.
        Columns: cusip, label, maturity, coupon, cash_price, conv_factor,
                 gross_basis, carry, net_basis, implied_repo, is_ctd.

    Raises:
        ValueError: If basket is empty or no cash prices are provided.
    """
    from core.basket import bond_label

    if not basket:
        raise ValueError("basket must not be empty")
    if not cash_prices:
        raise ValueError("cash_prices must not be empty")

    rows = []
    for bond in basket:
        cusip = bond["cusip"]
        price = cash_prices.get(cusip)
        if price is None:
            continue  # skip bonds with no market price

        cf     = bond["conv_factor"]
        coupon = bond["coupon"]

        gb = gross_basis(price, futures_price, cf)
        c  = carry(price, coupon, repo_rate, days_to_delivery)
        nb = net_basis(price, futures_price, cf, coupon, repo_rate, days_to_delivery)
        ir = implied_repo(price, futures_price, cf, coupon, days_to_delivery)

        rows.append({
            "cusip":        cusip,
            "label":        bond_label(bond),
            "maturity":     bond["maturity"],
            "coupon":       coupon,
            "cash_price":   price,
            "conv_factor":  cf,
            "gross_basis":  gb,
            "carry":        c,
            "net_basis":    nb,
            "implied_repo": ir,
        })

    if not rows:
        raise ValueError("No bonds had matching cash prices.")

    df = pd.DataFrame(rows).sort_values("implied_repo", ascending=False)
    df = df.reset_index(drop=True)
    df.index += 1
    df.index.name = "rank"
    df["is_ctd"] = df.index == 1
    return df
