"""Tests for core.basket — deliverable basket and conversion factor."""

import pytest
from datetime import date
from core.basket import (
    conversion_factor,
    get_basket,
    bond_label,
    MIN_MATURITY,
    MAX_MATURITY,
    DELIVERY_DATE,
)


class TestConversionFactor:
    def test_below_par_for_low_coupon(self):
        """Bond with coupon < 6% should have CF < 1."""
        cf = conversion_factor(0.04375, date(2034, 11, 15))
        assert cf < 1.0

    def test_above_par_for_high_coupon(self):
        """Bond with coupon > 6% should have CF > 1."""
        cf = conversion_factor(0.07, date(2034, 11, 15))
        assert cf > 1.0

    def test_six_percent_near_one(self):
        """Bond with 6% coupon should have CF close to 1."""
        cf = conversion_factor(0.06, date(2034, 5, 15))
        assert abs(cf - 1.0) < 0.05

    def test_rounded_to_four_decimals(self):
        """CF must be rounded to 4 decimal places (CME convention)."""
        cf = conversion_factor(0.04375, date(2034, 11, 15))
        assert cf == round(cf, 4)

    def test_longer_maturity_lower_cf_for_low_coupon(self):
        """For sub-6% bonds, longer maturity → lower CF (more discounting)."""
        cf_near = conversion_factor(0.04, date(2033, 2, 15))
        cf_far  = conversion_factor(0.04, date(2036, 2, 15))
        assert cf_near > cf_far

    def test_positive(self):
        """CF must always be positive."""
        cf = conversion_factor(0.04375, date(2034, 11, 15))
        assert cf > 0


class TestGetBasket:
    def setup_method(self):
        self.basket = get_basket(use_api=False)

    def test_returns_list(self):
        assert isinstance(self.basket, list)

    def test_non_empty(self):
        assert len(self.basket) > 0

    def test_bond_keys(self):
        """Every bond must have the required keys."""
        required = {"cusip", "coupon", "maturity", "conv_factor"}
        for bond in self.basket:
            assert required.issubset(bond.keys()), f"Missing keys in {bond}"

    def test_sorted_by_maturity(self):
        maturities = [b["maturity"] for b in self.basket]
        assert maturities == sorted(maturities)

    def test_maturities_in_eligibility_window(self):
        """All bonds must mature within the TYM26 eligibility window."""
        for bond in self.basket:
            assert MIN_MATURITY <= bond["maturity"] <= MAX_MATURITY, (
                f"{bond['cusip']} maturity {bond['maturity']} outside window"
            )

    def test_coupons_are_positive(self):
        for bond in self.basket:
            assert bond["coupon"] > 0

    def test_conv_factors_attached(self):
        for bond in self.basket:
            assert isinstance(bond["conv_factor"], float)
            assert 0 < bond["conv_factor"] < 2


class TestBondLabel:
    def test_format(self):
        bond = {"coupon": 0.04375, "maturity": date(2034, 11, 15)}
        label = bond_label(bond)
        assert "4.38" in label or "4.375" in label
        assert "Nov-34" in label

    def test_returns_string(self):
        bond = {"coupon": 0.04, "maturity": date(2033, 2, 15)}
        assert isinstance(bond_label(bond), str)
