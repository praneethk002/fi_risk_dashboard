"""
Tests for core.ctd: rank_basket(), ctd_transition_threshold(), basis_dv01(),
switch_direction(), basket_switch_map().
"""

from __future__ import annotations

from datetime import date

import pytest

from core.carry import implied_repo
from core.ctd import (
    basis_dv01,
    basket_switch_map,
    ctd_transition_threshold,
    rank_basket,
    switch_direction,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

FUTURES = 108.50
REPO    = 0.053
DAYS    = 110

# ---------------------------------------------------------------------------
# Minimal basket fixture used across TestRankBasket
# ---------------------------------------------------------------------------

_BASKET = [
    {
        "cusip":       "AAA111",
        "coupon":      0.04375,
        "maturity":    date(2034, 11, 15),
        "conv_factor": 0.8830,
    },
    {
        "cusip":       "BBB222",
        "coupon":      0.04000,
        "maturity":    date(2033,  2, 15),
        "conv_factor": 0.8650,
    },
    {
        "cusip":       "CCC333",
        "coupon":      0.04500,
        "maturity":    date(2035,  5, 15),
        "conv_factor": 0.8950,
    },
]

_PRICES = {
    "AAA111": 99.375,
    "BBB222": 98.750,
    "CCC333": 99.875,
}

_REQUIRED_COLUMNS = (
    "cusip",
    "label",
    "cash_price",
    "conv_factor",
    "gross_basis",
    "carry",
    "net_basis",
    "implied_repo",
    "is_ctd",
)


class TestRankBasket:

    def _df(self):
        """Return a fresh ranked DataFrame using the module-level fixtures."""
        return rank_basket(_BASKET, FUTURES, _PRICES, REPO, DAYS)

    def test_rank_1_is_ctd(self):
        df = self._df()
        assert df.loc[1, "is_ctd"] is True or df.loc[1, "is_ctd"] == True  # noqa: E712

    def test_only_one_ctd(self):
        df = self._df()
        assert df["is_ctd"].sum() == 1

    def test_implied_repos_descending(self):
        df = self._df()
        repos = df["implied_repo"].tolist()
        assert repos == sorted(repos, reverse=True)

    def test_required_columns_present(self):
        df = self._df()
        for col in _REQUIRED_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_empty_basket_raises(self):
        with pytest.raises(ValueError, match="basket"):
            rank_basket([], FUTURES, _PRICES, REPO, DAYS)

    def test_empty_prices_raises(self):
        with pytest.raises(ValueError, match="bond_prices"):
            rank_basket(_BASKET, FUTURES, {}, REPO, DAYS)

    def test_missing_all_prices_raises(self):
        """No bond in the basket has a matching key in bond_prices."""
        with pytest.raises(ValueError, match="No bonds"):
            rank_basket(_BASKET, FUTURES, {"ZZZNONE": 100.0}, REPO, DAYS)


# ---------------------------------------------------------------------------
# Constants for ctd_transition_threshold tests
# ---------------------------------------------------------------------------

P_A, CF_A, COUPON_A = 99.375, 0.8830, 0.04375
P_B, CF_B, COUPON_B = 98.750, 0.8650, 0.04000


class TestCTDTransitionThreshold:

    def _f_star(self) -> float:
        return ctd_transition_threshold(
            P_A, P_B, CF_A, CF_B, COUPON_A, COUPON_B, DAYS
        )

    def test_switch_point_verified_numerically(self):
        """At F*, implied_repo_A and implied_repo_B must be equal to 1e-9."""
        f_star = self._f_star()
        ir_a = implied_repo(P_A, f_star, CF_A, COUPON_A, DAYS)
        ir_b = implied_repo(P_B, f_star, CF_B, COUPON_B, DAYS)
        assert abs(ir_a - ir_b) < 1e-9

    def test_f_star_is_finite_for_typical_inputs(self):
        """F* must be a finite float (denominator is non-zero for these inputs)."""
        import math
        f_star = self._f_star()
        assert math.isfinite(f_star)

    def test_bond_a_ctd_above_f_star(self):
        """Above the threshold, bond A should have the higher implied repo."""
        f_star = self._f_star()
        f_high = f_star + 1.0
        ir_a = implied_repo(P_A, f_high, CF_A, COUPON_A, DAYS)
        ir_b = implied_repo(P_B, f_high, CF_B, COUPON_B, DAYS)
        assert ir_a > ir_b

    def test_bond_b_ctd_below_f_star(self):
        """Below the threshold, bond B should have the higher implied repo."""
        f_star = self._f_star()
        f_low = f_star - 1.0
        ir_a = implied_repo(P_A, f_low, CF_A, COUPON_A, DAYS)
        ir_b = implied_repo(P_B, f_low, CF_B, COUPON_B, DAYS)
        assert ir_b > ir_a

    def test_identical_slope_raises(self):
        """CF_A/P_A == CF_B/P_B → denominator is zero → ZeroDivisionError."""
        with pytest.raises(ZeroDivisionError):
            ctd_transition_threshold(
                price_a=100.0,
                price_b=100.0,
                cf_a=1.0,
                cf_b=1.0,
                coupon_a=0.04375,
                coupon_b=0.04000,
                days_to_delivery=DAYS,
            )


class TestBasisDV01:

    def test_zero_when_perfectly_hedged(self):
        result = basis_dv01(cash_dv01=0.09, futures_dv01=0.09, cf=1.0)
        assert result == pytest.approx(0.0)

    def test_positive_when_cash_duration_dominates(self):
        # 0.05 / 0.9 ≈ 0.0556 < 0.09  →  net DV01 > 0
        result = basis_dv01(cash_dv01=0.09, futures_dv01=0.05, cf=0.9)
        assert result > 0

    def test_negative_when_futures_dominates(self):
        # 0.09 / 0.9 = 0.10 > 0.05  →  net DV01 < 0
        result = basis_dv01(cash_dv01=0.05, futures_dv01=0.09, cf=0.9)
        assert result < 0

    def test_formula_exact(self):
        cash, futures, cf = 0.08, 0.08, 0.9
        expected = cash - futures / cf
        assert basis_dv01(cash, futures, cf) == pytest.approx(expected)

    def test_scales_with_cf(self):
        """For the same cash and futures DV01, a higher CF → larger DV01_basis.

        DV01_basis = cash_dv01 − futures_dv01 / CF.
        A higher CF makes the subtracted term (futures_dv01/CF) smaller,
        so the net basis DV01 is larger.
        """
        cash_dv01 = 0.09
        futures_dv01 = 0.07
        result_low_cf  = basis_dv01(cash_dv01, futures_dv01, cf=0.85)
        result_high_cf = basis_dv01(cash_dv01, futures_dv01, cf=0.95)
        assert result_high_cf > result_low_cf


# ---------------------------------------------------------------------------
# switch_direction()
# ---------------------------------------------------------------------------

class TestSwitchDirection:

    def test_rally_when_f_star_above_current(self):
        assert switch_direction(f_star=110.0, current_futures_price=108.5) == "RALLY"

    def test_selloff_when_f_star_below_current(self):
        assert switch_direction(f_star=107.0, current_futures_price=108.5) == "SELLOFF"

    def test_at_threshold_when_equal(self):
        assert switch_direction(f_star=108.5, current_futures_price=108.5) == "AT_THRESHOLD"

    def test_at_threshold_within_tolerance(self):
        # Difference of 5e-6 is below the 1e-5 guard
        assert switch_direction(f_star=108.500005, current_futures_price=108.5) == "AT_THRESHOLD"

    def test_rally_just_outside_tolerance(self):
        # Difference of 2e-5 is above the 1e-5 guard
        assert switch_direction(f_star=108.50002, current_futures_price=108.5) == "RALLY"

    def test_selloff_just_outside_tolerance(self):
        assert switch_direction(f_star=108.49998, current_futures_price=108.5) == "SELLOFF"


# ---------------------------------------------------------------------------
# basket_switch_map()
# ---------------------------------------------------------------------------

# Use the same basket/prices fixtures as TestRankBasket but with an explicit
# days_to_delivery column so basket_switch_map doesn't need to invert IR.

def _ranked_df_with_days():
    df = rank_basket(_BASKET, FUTURES, _PRICES, REPO, DAYS)
    df["days_to_delivery"] = DAYS
    return df


class TestBasketSwitchMap:

    def _map(self):
        return basket_switch_map(_ranked_df_with_days(), FUTURES)

    def test_returns_n_minus_1_entries(self):
        # 3-bond basket → 2 pairs
        result = self._map()
        assert len(result) == 2

    def test_required_keys_present(self):
        required = {
            "higher_rank", "lower_rank",
            "higher_cusip", "lower_cusip",
            "higher_label", "lower_label",
            "higher_ir", "lower_ir",
            "spread_bps", "f_star", "distance_pts", "direction",
        }
        for entry in self._map():
            assert required <= entry.keys()

    def test_sorted_by_abs_distance(self):
        result = self._map()
        distances = [abs(e["distance_pts"]) for e in result]
        assert distances == sorted(distances)

    def test_ranks_are_consecutive(self):
        result = self._map()
        for entry in result:
            assert entry["lower_rank"] == entry["higher_rank"] + 1

    def test_spread_bps_positive(self):
        # Higher-ranked bond always has the higher implied repo at the current F
        for entry in self._map():
            assert entry["spread_bps"] >= 0

    def test_direction_values_valid(self):
        valid = {"RALLY", "SELLOFF", "AT_THRESHOLD"}
        for entry in self._map():
            assert entry["direction"] in valid

    def test_f_star_verified_numerically(self):
        """At each F* the two adjacent bonds should have equal implied repo."""
        df = _ranked_df_with_days()
        result = basket_switch_map(df, FUTURES)
        rows = df.reset_index().to_dict("records")
        for i, entry in enumerate(result):
            high = next(r for r in rows if r["cusip"] == entry["higher_cusip"])
            low  = next(r for r in rows if r["cusip"] == entry["lower_cusip"])
            f_star = entry["f_star"]
            ir_h = implied_repo(high["cash_price"], f_star, high["conv_factor"],
                                high["coupon"], DAYS)
            ir_l = implied_repo(low["cash_price"],  f_star, low["conv_factor"],
                                low["coupon"], DAYS)
            assert abs(ir_h - ir_l) < 1e-6, (
                f"Pair {entry['higher_label']} / {entry['lower_label']}: "
                f"implied repos not equal at F*={f_star}"
            )

    def test_direction_consistent_with_distance(self):
        """direction must be consistent with the sign of distance_pts."""
        for entry in self._map():
            if entry["distance_pts"] > 1e-4:
                assert entry["direction"] == "RALLY"
            elif entry["distance_pts"] < -1e-4:
                assert entry["direction"] == "SELLOFF"
            else:
                assert entry["direction"] == "AT_THRESHOLD"

    def test_single_bond_raises(self):
        df = _ranked_df_with_days().iloc[:1]
        with pytest.raises(ValueError, match="at least 2"):
            basket_switch_map(df, FUTURES)

    def test_two_bond_basket(self):
        """Two-bond basket produces exactly one entry."""
        df = _ranked_df_with_days().iloc[:2]
        result = basket_switch_map(df, FUTURES)
        assert len(result) == 1

    def test_days_inferred_without_column(self):
        """basket_switch_map must not crash when days_to_delivery column is absent."""
        df = _ranked_df_with_days().drop(columns=["days_to_delivery"])
        result = basket_switch_map(df, FUTURES)
        # Result length and direction validity are the key assertions
        assert len(result) == len(df) - 1
        for entry in result:
            assert entry["direction"] in {"RALLY", "SELLOFF", "AT_THRESHOLD"}
