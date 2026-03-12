"""Tests for core.basis — gross basis, carry, net basis, implied repo, CTD."""

import pytest
import pandas as pd
from datetime import date
from core.basis import gross_basis, carry, net_basis, implied_repo, find_ctd, basket_analysis


class TestGrossBasis:
    def test_positive_gross_basis(self):
        """Cash price > invoice ⟹ positive gross basis."""
        gb = gross_basis(98.50, 97.00, 0.9750)
        assert gb > 0

    def test_zero_gross_basis(self):
        """When cash price equals invoice price, gross basis is zero."""
        gb = gross_basis(94.575, 97.00, 0.9750)
        assert abs(gb) < 1e-9

    def test_negative_gross_basis(self):
        """Cash price < invoice ⟹ negative gross basis."""
        gb = gross_basis(90.00, 97.00, 0.9750)
        assert gb < 0


class TestCarry:
    def test_positive_carry_high_coupon(self):
        """High coupon relative to repo ⟹ positive carry."""
        c = carry(100.0, 0.06, 0.02, 90)
        assert c > 0

    def test_negative_carry_high_repo(self):
        """Low coupon relative to high repo ⟹ negative carry."""
        c = carry(100.0, 0.01, 0.06, 90)
        assert c < 0

    def test_zero_days(self):
        """Zero days to delivery ⟹ zero carry."""
        c = carry(100.0, 0.05, 0.04, 0)
        assert c == 0.0

    def test_day_count_convention(self):
        """Coupon accrues on ACT/365; financing on ACT/360."""
        coupon_income = 100.0 * 0.05 * (90 / 365)
        financing_cost = 100.0 * 0.04 * (90 / 360)
        expected = coupon_income - financing_cost
        assert abs(carry(100.0, 0.05, 0.04, 90) - expected) < 1e-10


class TestNetBasis:
    def test_net_basis_less_than_gross(self):
        """Net basis < gross basis when carry is positive."""
        gb = gross_basis(98.50, 97.00, 0.9750)
        nb = net_basis(98.50, 97.00, 0.9750, 0.05, 0.04, 90)
        assert nb < gb

    def test_decomposition(self):
        """net_basis = gross_basis - carry."""
        gb = gross_basis(98.50, 97.00, 0.9750)
        c = carry(98.50, 0.05, 0.04, 90)
        nb = net_basis(98.50, 97.00, 0.9750, 0.05, 0.04, 90)
        assert abs(nb - (gb - c)) < 1e-10


class TestImpliedRepo:
    def test_returns_float(self):
        ir = implied_repo(98.50, 97.00, 0.9750, 0.045, 90)
        assert isinstance(ir, float)

    def test_reasonable_range(self):
        """Implied repo for realistic inputs should be in a sensible range."""
        ir = implied_repo(98.50, 97.00, 0.9750, 0.045, 90)
        assert -0.20 < ir < 0.20


class TestFindCTD:
    BONDS = [
        {"cash_price": 98.50, "conversion_factor": 0.9750, "coupon_rate": 0.045, "label": "Bond A"},
        {"cash_price": 95.00, "conversion_factor": 0.9400, "coupon_rate": 0.040, "label": "Bond B"},
        {"cash_price": 102.00, "conversion_factor": 1.0100, "coupon_rate": 0.055, "label": "Bond C"},
    ]

    def test_returns_one_bond(self):
        ctd = find_ctd(self.BONDS, 97.00, 90)
        assert isinstance(ctd, dict)
        assert "implied_repo" in ctd

    def test_ctd_has_max_implied_repo(self):
        ctd = find_ctd(self.BONDS, 97.00, 90)
        all_repos = [
            implied_repo(b["cash_price"], 97.00, b["conversion_factor"], b["coupon_rate"], 90)
            for b in self.BONDS
        ]
        assert abs(ctd["implied_repo"] - max(all_repos)) < 1e-10

    def test_empty_bonds_raises(self):
        with pytest.raises(ValueError, match="empty"):
            find_ctd([], 97.00, 90)


class TestBasketAnalysis:
    BASKET = [
        {"cusip": "AAA", "coupon": 0.04375, "maturity": date(2034, 11, 15), "conv_factor": 0.8830},
        {"cusip": "BBB", "coupon": 0.04625, "maturity": date(2035,  2, 15), "conv_factor": 0.9195},
        {"cusip": "CCC", "coupon": 0.04000, "maturity": date(2033,  2, 15), "conv_factor": 0.9014},
    ]
    PRICES     = {"AAA": 99.375, "BBB": 99.625, "CCC": 99.000}
    FUT_PRICE  = 108.50
    REPO       = 0.053
    DAYS       = 110

    def _run(self):
        return basket_analysis(self.BASKET, self.PRICES, self.FUT_PRICE, self.REPO, self.DAYS)

    def test_returns_dataframe(self):
        assert isinstance(self._run(), pd.DataFrame)

    def test_row_count_matches_priced_bonds(self):
        assert len(self._run()) == len(self.BASKET)

    def test_ranked_by_implied_repo(self):
        df = self._run()
        repos = df["implied_repo"].tolist()
        assert repos == sorted(repos, reverse=True)

    def test_exactly_one_ctd(self):
        df = self._run()
        assert df["is_ctd"].sum() == 1

    def test_ctd_is_rank_1(self):
        df = self._run()
        assert df.loc[df["is_ctd"]].index[0] == 1

    def test_net_basis_decomposition(self):
        """net_basis == gross_basis - carry for every row."""
        df = self._run()
        diff = (df["gross_basis"] - df["carry"] - df["net_basis"]).abs()
        assert (diff < 1e-9).all()

    def test_skips_bonds_with_no_price(self):
        prices = {"AAA": 99.375}   # only one bond priced
        df = basket_analysis(self.BASKET, prices, self.FUT_PRICE, self.REPO, self.DAYS)
        assert len(df) == 1

    def test_empty_basket_raises(self):
        with pytest.raises(ValueError, match="empty"):
            basket_analysis([], self.PRICES, self.FUT_PRICE, self.REPO, self.DAYS)

    def test_no_prices_raises(self):
        with pytest.raises(ValueError, match="empty"):
            basket_analysis(self.BASKET, {}, self.FUT_PRICE, self.REPO, self.DAYS)
