from core.pricing import modified_duration, dv01, convexity

def test_duration_par_bond():
    assert abs(modified_duration(1000, 0.05, 10, 0.05) - 7.79) < 0.01

def test_dv01_par_bond():
    assert abs(dv01(1000, 0.05, 10, 0.05) - 0.779) < 0.001

def test_convexity_positive():
    assert convexity(1000, 0.05, 10, 0.05) > 0

def test_convexity_longer_maturity_higher():
    assert convexity(1000, 0.05, 30, 0.05) > convexity(1000, 0.05, 10, 0.05)
