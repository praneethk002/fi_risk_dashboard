from core.pricing import price_bond
BUMP = 0.0001

def modified_duration(face_value, coupon_rate, years_to_maturity, yield_rate, frequency=2):
    price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    price_up = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate + BUMP, frequency)
    price_down = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate - BUMP, frequency)
    return (price_down - price_up) / (2 * BUMP * price)

def dv01(face_value, coupon_rate, years_to_maturity, yield_rate, frequency=2):
    price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    duration = modified_duration(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    return price * duration * 0.0001

def convexity(face_value, coupon_rate, years_to_maturity, yield_rate, frequency=2):
    price = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate, frequency)
    price_up = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate + BUMP, frequency)
    price_down = price_bond(face_value, coupon_rate, years_to_maturity, yield_rate - BUMP, frequency)
    return (price_up + price_down - 2 * price) / (price * BUMP ** 2)

if __name__ == "__main__":
    # How much does convexity correct duration for a large move?
    price = price_bond(1000, 0.05, 10, 0.05)
    duration = modified_duration(1000, 0.05, 10, 0.05)
    cvx = convexity(1000, 0.05, 10, 0.05)

    shock = 0.01  # 100bp move

    duration_estimate = -duration * shock * price
    convexity_correction = 0.5 * cvx * shock**2 * price

    print("Price change duration only:", duration_estimate)
    print("Convexity correction:", convexity_correction)
    print("Total estimated change:", duration_estimate + convexity_correction)

    # Actual price change
    actual = price_bond(1000, 0.05, 10, 0.06) - price
    print("Actual price change:", actual)