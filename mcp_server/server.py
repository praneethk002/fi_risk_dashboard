from mcp_server.fred_client import get_yield_curve

def get_live_curve():
    return get_yield_curve()

if __name__ == "__main__":
    curve = get_live_curve()
    print("Live yield curve:")
    for maturity, rate in curve.items():
        print(f"  {maturity}: {rate:.4f} ({rate*100:.2f}%)")