"""Tests for core.scenarios — yield curve shift functions."""

import pytest
from core.scenarios import parallel_shift, bear_steepening, bear_flattening, custom_shift

CURVE = {
    "3M": 0.040,
    "2Y": 0.043,
    "5Y": 0.044,
    "10Y": 0.046,
    "30Y": 0.048,
}


class TestParallelShift:
    def test_all_maturities_shift_equally(self):
        shifted = parallel_shift(CURVE, 50)
        for maturity, rate in CURVE.items():
            assert abs(shifted[maturity] - (rate + 0.005)) < 1e-10

    def test_negative_shift(self):
        shifted = parallel_shift(CURVE, -100)
        for maturity, rate in CURVE.items():
            assert abs(shifted[maturity] - (rate - 0.01)) < 1e-10

    def test_zero_shift_unchanged(self):
        shifted = parallel_shift(CURVE, 0)
        assert shifted == CURVE

    def test_original_curve_unchanged(self):
        parallel_shift(CURVE, 50)
        assert CURVE["10Y"] == 0.046  # original must be immutable


class TestBearSteepening:
    def test_short_end_unchanged(self):
        """First maturity receives 0 shift in bear steepening."""
        shifted = bear_steepening(CURVE, 100)
        first_maturity = list(CURVE.keys())[0]
        assert abs(shifted[first_maturity] - CURVE[first_maturity]) < 1e-10

    def test_long_end_receives_full_shift(self):
        """Last maturity receives the full shift."""
        shifted = bear_steepening(CURVE, 100)
        last_maturity = list(CURVE.keys())[-1]
        assert abs(shifted[last_maturity] - (CURVE[last_maturity] + 0.01)) < 1e-10

    def test_monotonically_increasing_shifts(self):
        """Shift applied to each maturity should be non-decreasing."""
        shifted = bear_steepening(CURVE, 100)
        original_rates = list(CURVE.values())
        shifted_rates = list(shifted.values())
        increments = [s - o for s, o in zip(shifted_rates, original_rates)]
        for i in range(len(increments) - 1):
            assert increments[i] <= increments[i + 1]


class TestBearFlattening:
    def test_short_end_receives_full_shift(self):
        """First maturity receives the full shift in bear flattening."""
        shifted = bear_flattening(CURVE, 100)
        first_maturity = list(CURVE.keys())[0]
        assert abs(shifted[first_maturity] - (CURVE[first_maturity] + 0.01)) < 1e-10

    def test_long_end_unchanged(self):
        """Last maturity receives 0 shift."""
        shifted = bear_flattening(CURVE, 100)
        last_maturity = list(CURVE.keys())[-1]
        assert abs(shifted[last_maturity] - CURVE[last_maturity]) < 1e-10

    def test_monotonically_decreasing_shifts(self):
        shifted = bear_flattening(CURVE, 100)
        original_rates = list(CURVE.values())
        shifted_rates = list(shifted.values())
        increments = [s - o for s, o in zip(shifted_rates, original_rates)]
        for i in range(len(increments) - 1):
            assert increments[i] >= increments[i + 1]


class TestCustomShift:
    def test_specified_maturities_shift(self):
        shifted = custom_shift(CURVE, {"2Y": 25, "10Y": 50})
        assert abs(shifted["2Y"] - (CURVE["2Y"] + 0.0025)) < 1e-10
        assert abs(shifted["10Y"] - (CURVE["10Y"] + 0.005)) < 1e-10

    def test_unspecified_maturities_unchanged(self):
        shifted = custom_shift(CURVE, {"10Y": 50})
        assert shifted["3M"] == CURVE["3M"]
        assert shifted["30Y"] == CURVE["30Y"]

    def test_empty_shifts_unchanged(self):
        shifted = custom_shift(CURVE, {})
        assert shifted == CURVE
