import os
import requests
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED series IDs for US Treasury rates
TREASURY_SERIES = {
    "3M": "DGS3MO",
    "2Y": "DGS2",
    "5Y": "DGS5",
    "10Y": "DGS10",
    "30Y": "DGS30"
}

def fetch_latest_rate(series_id):
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5
    }
    response = requests.get(FRED_BASE_URL, params=params)
    observations = response.json()["observations"]
    # FRED sometimes returns "." for missing data, skip those
    for obs in observations:
        if obs["value"] != ".":
            return float(obs["value"]) / 100  # Convert from % to decimal
    return None

def get_yield_curve():
    curve = {}
    for maturity, series_id in TREASURY_SERIES.items():
        rate = fetch_latest_rate(series_id)
        if rate is not None:
            curve[maturity] = rate
    return curve

if __name__ == "__main__":
    print(get_yield_curve())