"""Tests for core.pricing — bond price, accrued interest, dirty price."""

import pytest
from core.pricing import price_bond, accrued_interest, dirty_price


class TestPriceBond:
    def test_par_bond(self):
        """When coupon rate equals yield, price should equal face value."""
        price = price_bond(1000, 0.05, 10, 0.05)
        assert abs(price - 1000.0) < 1e-6

    def test_premium_bond(self):
        """Coupon > yield ⟹ price > par."""
        price = price_bond(1000, 0.05, 10, 0.03)
        assert price > 1000

    def test_discount_bond(self):
        """Coupon < yield ⟹ price < par."""
        price = price_bond(1000, 0.05, 10, 0.07)
        assert price < 1000

    def test_zero_coupon_bond(self):
        """Zero-coupon bond price = PV of face value."""
        price = price_bond(1000, 0.0, 10, 0.05)
        expected = 1000 / (1 + 0.05 / 2) ** 20
        assert abs(price - expected) < 1e-6

    def test_annual_frequency(self):
        """Annual coupon bond priced correctly."""
        price = price_bond(1000, 0.05, 10, 0.05, frequency=1)
        assert abs(price - 1000.0) < 1e-6

    def test_pull_to_par(self):
        """Price converges to face value as maturity approaches zero."""
        price_1yr = price_bond(1000, 0.05, 1, 0.05)
        price_short = price_bond(1000, 0.05, 0.5, 0.05)
        assert abs(price_1yr - 1000.0) < 1e-6
        assert abs(price_short - 1000.0) < 1e-6


class TestAccruedInterest:
    def test_zero_days(self):
        """Accrued interest on a coupon date should be zero."""
        ai = accrued_interest(1000, 0.05, 2, 0, 182)
        assert ai == 0.0

    def test_half_period(self):
        """Halfway through a coupon period accrues half a coupon payment."""
        coupon_payment = 1000 * 0.05 / 2  # = 25
        ai = accrued_interest(1000, 0.05, 2, 91, 182)
        assert abs(ai - coupon_payment * 0.5) < 0.01

    def test_full_period(self):
        """At end of period accrued ≈ full coupon payment."""
        coupon_payment = 1000 * 0.05 / 2
        ai = accrued_interest(1000, 0.05, 2, 182, 182)
        assert abs(ai - coupon_payment) < 1e-6


class TestDirtyPrice:
    def test_dirty_equals_clean_on_coupon_date(self):
        """On a coupon date (days_since=0) dirty price = clean price."""
        clean = price_bond(1000, 0.05, 10, 0.05)
        dirty = dirty_price(1000, 0.05, 10, 0.05, 0, 182)
        assert abs(dirty - clean) < 1e-6

    def test_dirty_greater_than_clean_mid_period(self):
        """Between coupon dates dirty price > clean price."""
        dirty = dirty_price(1000, 0.05, 10, 0.05, 91, 182)
        clean = price_bond(1000, 0.05, 10, 0.05)
        assert dirty > clean
