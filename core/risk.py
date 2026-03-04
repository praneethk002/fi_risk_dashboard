"""
Bond risk metrics: modified duration, DV01, and convexity.

All metrics are derived numerically via central finite differences so they
remain consistent regardless of the underlying pricing model.
"""

from __future__ import annotations

from core.pricing import price_bond

_BUMP = 1e-4  # 1 basis point


def modified_duration(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    yield_rate: float,
    frequency: int = 2,
) -> float:
    """Modified duration: percentage price sensitivity to a 1-unit yield move.

    Uses a central finite difference (±1bp) for numerical accuracy.

    Args:
        face_value: Principal amount.
        coupon_rate: Annual coupon rate as a decimal.
        years_to_maturity: Remaining life in years.
        yield_rate: Current annual yield as a decimal.
        frequency: Coupon payments per year.

    Returns:
        Modified duration in years.
    """
    price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    price_up = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate + _BUMP, frequency)
    price_down = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate - _BUMP, frequency)
    return (price_down - price_up) / (2 * _BUMP * price)


def dv01(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    yield_rate: float,
    frequency: int = 2,
) -> float:
    """Dollar value of a 1 basis point move in yield (DV01 / PVBP).

    Args:
        face_value: Principal amount.
        coupon_rate: Annual coupon rate as a decimal.
        years_to_maturity: Remaining life in years.
        yield_rate: Current annual yield as a decimal.
        frequency: Coupon payments per year.

    Returns:
        Absolute price change for a +1bp yield increase, in the same currency
        as face_value.
    """
    price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    dur = modified_duration(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    return price * dur * _BUMP


def convexity(
    face_value: float,
    coupon_rate: float,
    years_to_maturity: float,
    yield_rate: float,
    frequency: int = 2,
) -> float:
    """Convexity: second-order price sensitivity to yield.

    A positive value means the bond outperforms its duration estimate for
    large yield moves in either direction.

    Args:
        face_value: Principal amount.
        coupon_rate: Annual coupon rate as a decimal.
        years_to_maturity: Remaining life in years.
        yield_rate: Current annual yield as a decimal.
        frequency: Coupon payments per year.

    Returns:
        Convexity (dimensionless, units of years²).
    """
    price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    price_up = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate + _BUMP, frequency)
    price_down = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate - _BUMP, frequency)
    return (price_up + price_down - 2 * price) / (price * _BUMP**2)
