"""
CTD (cheapest-to-deliver) analytics for Treasury bond futures.

Three functions:

  rank_basket()              – ranks the full delivery basket by implied repo;
                               the CTD is rank 1.

  ctd_transition_threshold() – solves for the futures price F* at which bond B
                               overtakes bond A as CTD (implied_repo_A = implied_repo_B).
                               This is derived analytically from the cost-of-carry
                               no-arbitrage equation and verified numerically in the
                               test suite.

  basis_dv01()               – DV01 of a long cash / short futures basis position:
                                   DV01_basis = DV01_cash − DV01_futures_CTD / CF_CTD
                               The futures DV01 is the CTD's DV01 divided by its
                               conversion factor because futures_price = CTD_price / CF.

Reference: Burghardt et al., "The Treasury Bond Basis" (the standard text).
"""

from __future__ import annotations

import pandas as pd

from core.basket import bond_label
from core.carry import carry, gross_basis, implied_repo, net_basis


def rank_basket(
    basket: list[dict],
    futures_price: float,
    bond_prices: dict[str, float],
    repo_rate: float,
    days_to_delivery: int,
) -> pd.DataFrame:
    """Rank the delivery basket by implied repo rate (CTD = rank 1).

    The CTD is the bond that maximises the implied repo rate — it is the
    cheapest for the futures short to acquire and deliver against the contract.

    Args:
        basket:           List of bond dicts from core.basket.get_basket().
                          Required keys: cusip, coupon, maturity, conv_factor.
        futures_price:    Quoted futures price as % of par.
        bond_prices:      Dict mapping cusip → clean cash price (% of par).
        repo_rate:        Financing rate as a decimal (e.g. 0.053).
        days_to_delivery: Calendar days to the futures delivery date.

    Returns:
        DataFrame sorted by implied_repo descending (CTD first), with
        index starting at 1 (rank). Columns: cusip, label, maturity,
        coupon, cash_price, conv_factor, gross_basis, carry, net_basis,
        implied_repo, is_ctd.

    Raises:
        ValueError: If basket is empty, bond_prices is empty, or no bond
                    in basket has a matching price.
    """
    if not basket:
        raise ValueError("basket must not be empty")
    if not bond_prices:
        raise ValueError("bond_prices must not be empty")

    rows = []
    for bond in basket:
        cusip = bond["cusip"]
        price = bond_prices.get(cusip)
        if price is None:
            continue

        cf     = bond["conv_factor"]
        coupon = bond["coupon"]

        rows.append({
            "cusip":        cusip,
            "label":        bond_label(bond),
            "maturity":     bond["maturity"],
            "coupon":       coupon,
            "cash_price":   price,
            "conv_factor":  cf,
            "gross_basis":  gross_basis(price, futures_price, cf),
            "carry":        carry(price, coupon, repo_rate, days_to_delivery),
            "net_basis":    net_basis(price, futures_price, cf, coupon, repo_rate, days_to_delivery),
            "implied_repo": implied_repo(price, futures_price, cf, coupon, days_to_delivery),
        })

    if not rows:
        raise ValueError("No bonds in basket had a matching price in bond_prices.")

    df = pd.DataFrame(rows).sort_values("implied_repo", ascending=False)
    df = df.reset_index(drop=True)
    df.index += 1
    df.index.name = "rank"
    df["is_ctd"] = df.index == 1
    return df


def ctd_transition_threshold(
    price_a: float,
    price_b: float,
    cf_a: float,
    cf_b: float,
    coupon_a: float,
    coupon_b: float,
    days_to_delivery: int,
) -> float:
    """Futures price F* at which bond B overtakes bond A as CTD.

    Derived by setting implied_repo_A(F*) = implied_repo_B(F*) and
    solving for F.  Starting from the implied repo formula:

        IR_x(F) = [F·CF_x + P_x·c_x·(days/365) − P_x] / P_x · (360/days)

    Setting IR_A = IR_B and cancelling (360/days):

        [F·CF_A + CA_A − P_A] / P_A  =  [F·CF_B + CA_B − P_B] / P_B

    where CA_x = P_x · coupon_x · (days/365) is the coupon accrual.

    Rearranging:

        F* = (CA_B·P_A − CA_A·P_B) / (CF_A·P_B − CF_B·P_A)

    This is an exact closed-form solution (not an approximation).
    The denominator is non-zero whenever the bonds have different
    implied-repo sensitivities to F (i.e. CF_A/P_A ≠ CF_B/P_B).

    Args:
        price_a:          Clean cash price of bond A (current CTD), % of par.
        price_b:          Clean cash price of bond B (runner-up), % of par.
        cf_a:             Conversion factor of bond A.
        cf_b:             Conversion factor of bond B.
        coupon_a:         Annual coupon rate of bond A as a decimal.
        coupon_b:         Annual coupon rate of bond B as a decimal.
        days_to_delivery: Calendar days to futures delivery.

    Returns:
        Futures price F* (% of par) at which bond B becomes CTD.

    Raises:
        ZeroDivisionError: If CF_A/P_A == CF_B/P_B (bonds have identical
                           implied-repo slope; no unique switch point exists).
    """
    ca_a = price_a * coupon_a * (days_to_delivery / 365)
    ca_b = price_b * coupon_b * (days_to_delivery / 365)
    numerator   = ca_b * price_a - ca_a * price_b
    denominator = cf_a * price_b - cf_b * price_a
    if abs(denominator) < 1e-12:
        raise ZeroDivisionError(
            "Bonds have identical implied-repo slope (CF_A/P_A ≈ CF_B/P_B); "
            "no unique transition futures price exists."
        )
    return numerator / denominator


def switch_direction(f_star: float, current_futures_price: float) -> str:
    """Classify the market direction needed to trigger a CTD transition.

    After computing F* via ctd_transition_threshold(), this helper
    translates the raw number into an actionable signal:

    - ``"RALLY"``        – futures must rise above F* for the switch to occur.
    - ``"SELLOFF"``      – futures must fall below F* for the switch to occur.
    - ``"AT_THRESHOLD"`` – current price is already at F* (switch is live).

    The 1e-5 tolerance (roughly 1/32 of a tick on TY) avoids spurious
    ``"AT_THRESHOLD"`` classifications from floating-point noise.

    Args:
        f_star:               Transition futures price from ctd_transition_threshold().
        current_futures_price: Today's quoted futures price.

    Returns:
        One of ``"RALLY"``, ``"SELLOFF"``, or ``"AT_THRESHOLD"``.
    """
    diff = f_star - current_futures_price
    if abs(diff) < 1e-5:
        return "AT_THRESHOLD"
    return "RALLY" if diff > 0 else "SELLOFF"


def basket_switch_map(
    ranked_df: pd.DataFrame,
    futures_price: float,
) -> list[dict]:
    """Transition thresholds for every consecutive pair in the ranked basket.

    For each adjacent pair (rank *i*, rank *i+1*) this function computes
    the futures price F* at which the lower-ranked bond overtakes the
    higher-ranked one and classifies the required market move.  The list
    is sorted by ``|distance_pts|`` ascending so the nearest potential
    switch appears first.

    This gives a complete *switch map* of the basket — not just the CTD
    vs. runner-up — which is useful when the second-ranked bond is close
    to the third, or when monitoring a potential double switch.

    Args:
        ranked_df:     Output of :func:`rank_basket`, sorted by implied_repo
                       descending (rank 1 = CTD).  Required columns:
                       ``cusip``, ``label``, ``cash_price``, ``conv_factor``,
                       ``coupon``, ``implied_repo``.  If a ``days_to_delivery``
                       column is present it will be used directly; otherwise
                       it is estimated from the CTD row via the implied repo
                       formula inversion.
        futures_price: Current quoted futures price (% of par).

    Returns:
        List of dicts, one per consecutive pair, sorted by
        ``|distance_pts|`` ascending (nearest switch first).  Each dict:

        .. code-block:: python

            {
                "higher_rank":   int,    # e.g. 1
                "lower_rank":    int,    # e.g. 2
                "higher_cusip":  str,
                "lower_cusip":   str,
                "higher_label":  str,
                "lower_label":   str,
                "higher_ir":     float,  # implied repo at current F (decimal)
                "lower_ir":      float,
                "spread_bps":    float,  # (higher_ir - lower_ir) * 10_000
                "f_star":        float,  # futures price where lower overtakes higher
                "distance_pts":  float,  # f_star - futures_price (+ = rally needed)
                "direction":     str,    # "RALLY" | "SELLOFF" | "AT_THRESHOLD"
            }

    Raises:
        ValueError: If ``ranked_df`` has fewer than 2 rows.
        ZeroDivisionError: Propagated from :func:`ctd_transition_threshold`
                           if any pair has identical implied-repo slopes.
    """
    if len(ranked_df) < 2:
        raise ValueError(
            "ranked_df must contain at least 2 bonds to compute a switch map."
        )

    # Recover days_to_delivery from the DataFrame if the column is present
    # (written by BasisDB.write_snapshot), otherwise estimate it from the
    # CTD row by inverting the implied repo formula:
    #   IR = [F·CF + P·c·(d/365) − P] / P · (360/d)
    #   → d = (F·CF − P) / (P·IR/360 − P·c/365)
    if "days_to_delivery" in ranked_df.columns:
        days = int(ranked_df.iloc[0]["days_to_delivery"])
    else:
        ctd   = ranked_df.iloc[0]
        p, cf, c, ir = ctd["cash_price"], ctd["conv_factor"], ctd["coupon"], ctd["implied_repo"]
        denom = p * ir / 360 - p * c / 365
        days  = int(round((futures_price * cf - p) / denom)) if abs(denom) > 1e-12 else 90

    rows_list = ranked_df.reset_index().to_dict("records")
    result: list[dict] = []

    for i in range(len(rows_list) - 1):
        high = rows_list[i]
        low  = rows_list[i + 1]

        f_star = ctd_transition_threshold(
            price_a=high["cash_price"],
            price_b=low["cash_price"],
            cf_a=high["conv_factor"],
            cf_b=low["conv_factor"],
            coupon_a=high["coupon"],
            coupon_b=low["coupon"],
            days_to_delivery=days,
        )

        distance   = f_star - futures_price
        spread_bps = (high["implied_repo"] - low["implied_repo"]) * 10_000

        result.append({
            "higher_rank":  high.get("rank", i + 1),
            "lower_rank":   low.get("rank", i + 2),
            "higher_cusip": high["cusip"],
            "lower_cusip":  low["cusip"],
            "higher_label": high["label"],
            "lower_label":  low["label"],
            "higher_ir":    high["implied_repo"],
            "lower_ir":     low["implied_repo"],
            "spread_bps":   round(spread_bps, 2),
            "f_star":       round(f_star, 4),
            "distance_pts": round(distance, 4),
            "direction":    switch_direction(f_star, futures_price),
        })

    result.sort(key=lambda x: abs(x["distance_pts"]))
    return result


def basis_dv01(
    cash_dv01: float,
    futures_dv01: float,
    cf: float,
) -> float:
    """DV01 of a long cash / short futures basis position.

    A basis trader who is long the cash bond and short futures is
    exposed to yield changes through both legs.  The futures DV01 is
    the CTD's DV01 divided by its conversion factor, because:

        futures_price ≈ CTD_clean_price / CF

    Therefore:
        ∂(futures_price)/∂y ≈ (∂CTD_price/∂y) / CF = DV01_cash / CF

    The net DV01 of the basis position is:

        DV01_basis = DV01_cash − DV01_futures_CTD / CF

    A positive DV01_basis means the position loses money when yields
    rise (long duration via the cash bond dominates).

    Args:
        cash_dv01:    DV01 of the cash bond position (positive, in $).
        futures_dv01: DV01 of the CTD bond underlying the futures (positive, in $).
        cf:           Conversion factor of the CTD bond.

    Returns:
        Net DV01 of the basis position in the same currency as the inputs.
    """
    return cash_dv01 - futures_dv01 / cf
