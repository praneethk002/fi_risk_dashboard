from core.pricing import price_bond

# Test 1 — Par bond (when coupon rate = yield, price should = face value)
print(price_bond(1000, 0.05, 10, 0.05))  # Expected: 1000.0

# Test 2 — Premium bond (coupon > yield, price should be > 1000)
print(price_bond(1000, 0.05, 10, 0.03))  # Expected: ~1170

# Test 3 — Discount bond (coupon < yield, price should be < 1000)
print(price_bond(1000, 0.05, 10, 0.07))  # Expected: ~859