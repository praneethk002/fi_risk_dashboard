def price_bond(face_value, coupon_rate,years_to_maturity,discount_rate,frequency = 2):
    coupon_payment  = face_value*coupon_rate/frequency
    periods = years_to_maturity*frequency
    price = 0
    for periods in range(1,periods+1):
        price += coupon_payment/(1+discount_rate / frequency)**periods
    price += face_value/(1 + discount_rate/frequency)**periods
    return price


