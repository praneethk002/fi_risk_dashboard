def parallel_shift(curve, shift_bps):
    shift = shift_bps / 10000
    return {maturity: rate + shift for maturity, rate in curve.items()}

def bear_steepening(curve, shift_bps):
    shift = shift_bps / 10000
    maturities = list(curve.keys())
    n = len(maturities)
    return {
        maturity: rate + shift * (i / (n - 1))
        for i, (maturity, rate) in enumerate(curve.items())
    }

def bear_flattening(curve, shift_bps):
    shift = shift_bps / 10000
    maturities = list(curve.keys())
    n = len(maturities)
    return {
        maturity: rate + shift * (1 - i / (n - 1))
        for i, (maturity, rate) in enumerate(curve.items())
    }

def custom_shift(curve, shifts_bps):
    return {
        maturity: rate + shifts_bps.get(maturity, 0) / 10000
        for maturity, rate in curve.items()
    }

if __name__ == "__main__":
    curve = {
        "3M": 0.040, "2Y": 0.043, "5Y": 0.044,
        "10Y": 0.046, "30Y": 0.048
    }

    print("Original:       ", curve)
    print("Parallel +50bps:", parallel_shift(curve, 50))
    print("Bear steepening:", bear_steepening(curve, 100))
    print("Bear flattening:", bear_flattening(curve, 100))
    print("Custom:         ", custom_shift(curve, {"2Y": 25, "10Y": 50, "30Y": 100}))