"""
Bond pricing module.

All prices are expressed per unit of face value unless face_value is supplied.
Yields and coupon rates are expressed as decimals (e.g. 0.05 for 5%).
This implementation prices bonds on a coupon date (no accrued interest).
For full settlement pricing use price_bond_with_accrued().
"""

from __future__ import annotations

import numpy as np


def price_bond(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    discount_rate: float,
    frequency: int = 2,
) -> float:
    """Price a fixed-coupon bond by discounting cash flows.

    Prices as of a coupon date (accrued interest = 0).

    Implementation uses a vectorised numpy dot product instead of a Python
    loop, which matters when this function is called in tight bootstrap or
    scenario-grid loops (10x–50x speedup for long maturities).

    Args:
        face_value: Principal amount repaid at maturity.
        coupon_rate: Annual coupon rate as a decimal (e.g. 0.05 for 5%).
        years_to_maturity: Remaining life of the bond in years.
        discount_rate: Annual yield (discount rate) as a decimal.
        frequency: Coupon payments per year (1 = annual, 2 = semi-annual).

    Returns:
        Clean / full price (same on a coupon date) in the same currency as
        face_value.
    """
    coupon_payment = face_value * coupon_rate / frequency
    n_periods = int(round(years_to_maturity * frequency))
    periodic_rate = discount_rate / frequency

    periods = np.arange(1, n_periods + 1, dtype=float)
    cfs = np.full(n_periods, coupon_payment)
    cfs[-1] += face_value                               # principal at maturity
    discount_factors = (1.0 + periodic_rate) ** periods

    return float(np.dot(cfs, 1.0 / discount_factors))


def accrued_interest(
    face_value: float,
    coupon_rate: float,
    frequency: int,
    days_since_last_coupon: int,
    days_in_coupon_period: int,
) -> float:
    """Calculate accrued interest using the actual/actual (ICMA) convention.

    US Treasuries use actual/actual; this function is general-purpose.

    Args:
        face_value: Principal amount.
        coupon_rate: Annual coupon rate as a decimal.
        frequency: Coupon payments per year.
        days_since_last_coupon: Calendar days elapsed since the last coupon.
        days_in_coupon_period: Total calendar days in the current coupon period.

    Returns:
        Accrued interest in the same currency as face_value.
    """
    coupon_payment = face_value * coupon_rate / frequency
    accrual_fraction = days_since_last_coupon / days_in_coupon_period
    return coupon_payment * accrual_fraction


def dirty_price(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    discount_rate: float,
    days_since_last_coupon: int,
    days_in_coupon_period: int,
    frequency: int = 2,
) -> float:
    """Full (dirty) price = clean price + accrued interest.

    Args:
        face_value: Principal amount.
        coupon_rate: Annual coupon rate as a decimal.
        years_to_maturity: Remaining life from settlement in years.
        discount_rate: Annual yield as a decimal.
        days_since_last_coupon: Calendar days since the last coupon payment.
        days_in_coupon_period: Total calendar days in the current coupon period.
        frequency: Coupon payments per year.

    Returns:
        Dirty (invoice) price in the same currency as face_value.
    """
    clean = price_bond(face_value, coupon_rate, years_to_maturity, discount_rate, frequency)
    ai = accrued_interest(face_value, coupon_rate, frequency, days_since_last_coupon, days_in_coupon_period)
    return clean + ai
