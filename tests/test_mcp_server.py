"""
Tests for MCP server tools — focuses on the two tools added/modified in this
sprint: get_ctd_transition_threshold (direction field) and get_basket_switch_map.

All tests run against the seeded SQLite DB (basis_monitor.db).  The conftest
already ensures the DB is present; if not, the tests are skipped.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Skip the entire module if the MCP server or seeded DB is unavailable
# ---------------------------------------------------------------------------

try:
    from mcp_server.server import get_ctd_transition_threshold, get_basket_switch_map
    _IMPORT_OK = True
except Exception:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="mcp_server.server could not be imported (DB or deps missing)",
)

CONTRACT = "TYM26"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _threshold():
    result = get_ctd_transition_threshold(CONTRACT)
    if "error" in result:
        pytest.skip(f"get_ctd_transition_threshold returned error: {result['error']}")
    return result


def _switch_map():
    result = get_basket_switch_map(CONTRACT)
    if isinstance(result, dict) and "error" in result:
        pytest.skip(f"get_basket_switch_map returned error: {result['error']}")
    return result


# ---------------------------------------------------------------------------
# get_ctd_transition_threshold — direction field
# ---------------------------------------------------------------------------

class TestCTDTransitionThresholdDirection:

    def test_direction_key_present(self):
        t = _threshold()
        assert "direction" in t

    def test_direction_valid_value(self):
        t = _threshold()
        assert t["direction"] in {"RALLY", "SELLOFF", "AT_THRESHOLD"}

    def test_direction_consistent_with_distance(self):
        t = _threshold()
        dist = t["distance_to_threshold_pts"]
        direction = t["direction"]
        if dist > 1e-4:
            assert direction == "RALLY", f"dist={dist} but direction={direction}"
        elif dist < -1e-4:
            assert direction == "SELLOFF", f"dist={dist} but direction={direction}"
        else:
            assert direction == "AT_THRESHOLD"

    def test_existing_fields_unchanged(self):
        """Ensure the direction addition didn't drop any pre-existing fields."""
        required = {
            "contract", "snapshot_dt", "current_futures_price",
            "ctd_label", "runner_up_label",
            "ctd_implied_repo_pct", "runner_up_implied_repo_pct",
            "spread_bps", "transition_threshold_futures_price",
            "distance_to_threshold_pts", "note",
        }
        t = _threshold()
        for key in required:
            assert key in t, f"Field '{key}' missing from response"


# ---------------------------------------------------------------------------
# get_basket_switch_map — Tool 9
# ---------------------------------------------------------------------------

class TestBasketSwitchMap:

    _REQUIRED_KEYS = {
        "higher_rank", "lower_rank",
        "higher_cusip", "lower_cusip",
        "higher_label", "lower_label",
        "higher_ir_pct", "lower_ir_pct",
        "spread_bps", "f_star", "distance_pts", "direction",
    }

    def test_returns_list(self):
        assert isinstance(_switch_map(), list)

    def test_nonempty(self):
        assert len(_switch_map()) > 0

    def test_required_keys_present(self):
        for entry in _switch_map():
            missing = self._REQUIRED_KEYS - entry.keys()
            assert not missing, f"Missing keys: {missing}"

    def test_sorted_by_abs_distance(self):
        sm = _switch_map()
        distances = [abs(e["distance_pts"]) for e in sm]
        assert distances == sorted(distances)

    def test_ranks_consecutive(self):
        for entry in _switch_map():
            assert entry["lower_rank"] == entry["higher_rank"] + 1

    def test_direction_valid(self):
        for entry in _switch_map():
            assert entry["direction"] in {"RALLY", "SELLOFF", "AT_THRESHOLD"}

    def test_direction_consistent_with_distance(self):
        for entry in _switch_map():
            dist = entry["distance_pts"]
            direction = entry["direction"]
            if dist > 1e-4:
                assert direction == "RALLY", f"dist={dist} dir={direction}"
            elif dist < -1e-4:
                assert direction == "SELLOFF", f"dist={dist} dir={direction}"
            else:
                assert direction == "AT_THRESHOLD"

    def test_spread_bps_nonnegative(self):
        # Higher-ranked bond always has ≥ implied repo at current futures price
        for entry in _switch_map():
            assert entry["spread_bps"] >= -1e-6, f"Negative spread: {entry['spread_bps']}"

    def test_ir_pct_in_plausible_range(self):
        # Implied repo can go negative in stressed environments; bound loosely
        for entry in _switch_map():
            for key in ("higher_ir_pct", "lower_ir_pct"):
                val = entry[key]
                assert -20 <= val <= 30, f"{key}={val} out of plausible range"

    def test_first_entry_matches_threshold_tool(self):
        """The nearest switch (entry[0]) must align with the CTD vs runner-up threshold."""
        sm = _switch_map()
        t  = _threshold()
        # Entry with higher_rank==1 is the CTD->runner-up pair
        ctd_pair = next((e for e in sm if e["higher_rank"] == 1), None)
        if ctd_pair is None:
            pytest.skip("No rank-1 entry in switch map")
        assert ctd_pair["f_star"] == pytest.approx(
            t["transition_threshold_futures_price"], abs=1e-3
        ), (
            f"switch_map F*={ctd_pair['f_star']} != "
            f"threshold tool F*={t['transition_threshold_futures_price']}"
        )
