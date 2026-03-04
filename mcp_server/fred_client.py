"""
FRED API client for live US Treasury yield curve data.

Series used
-----------
DGS3MO  3-month Treasury constant maturity rate
DGS2    2-year  Treasury constant maturity rate
DGS5    5-year  Treasury constant maturity rate
DGS10   10-year Treasury constant maturity rate
DGS30   30-year Treasury constant maturity rate

All rates are returned as decimals (e.g. 0.045 for 4.5%).
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY: Optional[str] = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

TREASURY_SERIES: dict[str, str] = {
    "3M": "DGS3MO",
    "2Y": "DGS2",
    "5Y": "DGS5",
    "10Y": "DGS10",
    "30Y": "DGS30",
}

# Simple in-process cache: (data, timestamp)
_cache: dict[str, tuple[Optional[float], float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def fetch_latest_rate(series_id: str) -> Optional[float]:
    """Fetch the most recent non-missing observation for a FRED series.

    Results are cached for 5 minutes to avoid hammering the API.

    Args:
        series_id: FRED series identifier (e.g. "DGS10").

    Returns:
        Latest rate as a decimal, or ``None`` if unavailable.

    Raises:
        RuntimeError: If the FRED API returns a non-200 status code.
    """
    now = time.monotonic()
    cached_value, cached_at = _cache.get(series_id, (None, 0.0))
    if now - cached_at < _CACHE_TTL_SECONDS and cached_value is not None:
        return cached_value

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5,
    }
    response = requests.get(FRED_BASE_URL, params=params, timeout=10)
    if response.status_code != 200:
        raise RuntimeError(
            f"FRED API error {response.status_code} for series {series_id}"
        )

    observations = response.json().get("observations", [])
    for obs in observations:
        if obs["value"] != ".":
            rate = float(obs["value"]) / 100
            _cache[series_id] = (rate, now)
            return rate

    return None


def get_yield_curve() -> dict[str, float]:
    """Fetch the full US Treasury yield curve from FRED.

    Returns:
        Mapping of maturity label (e.g. "10Y") to decimal yield.
        Missing maturities are omitted rather than set to None.
    """
    curve: dict[str, float] = {}
    for maturity, series_id in TREASURY_SERIES.items():
        rate = fetch_latest_rate(series_id)
        if rate is not None:
            curve[maturity] = rate
    return curve
