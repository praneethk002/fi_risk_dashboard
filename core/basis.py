def gross_basis(cash_price, futures_price, conversion_factor):
    return cash_price - futures_price * conversion_factor

def carry(cash_price, coupon_rate, repo_rate, days_to_delivery):
    coupon_income = cash_price * coupon_rate * (days_to_delivery / 365)
    financing_cost = cash_price * repo_rate * (days_to_delivery / 360)
    return coupon_income - financing_cost

def net_basis(cash_price, futures_price, conversion_factor, coupon_rate, repo_rate, days_to_delivery):
    gb = gross_basis(cash_price, futures_price, conversion_factor)
    c = carry(cash_price, coupon_rate, repo_rate, days_to_delivery)
    return gb - c

def implied_repo(cash_price, futures_price, conversion_factor, coupon_rate, days_to_delivery):
    numerator = (futures_price * conversion_factor + cash_price * coupon_rate * (days_to_delivery / 365)) - cash_price
    return (numerator / cash_price) * (360 / days_to_delivery)

def find_ctd(bonds, futures_price, days_to_delivery):
    # bonds = list of dicts with cash_price, conversion_factor, coupon_rate
    results = []
    for bond in bonds:
        ir = implied_repo(
            bond["cash_price"],
            futures_price,
            bond["conversion_factor"],
            bond["coupon_rate"],
            days_to_delivery
        )
        results.append({**bond, "implied_repo": ir})
    return max(results, key=lambda x: x["implied_repo"])

if __name__ == "__main__":
    # Single bond tests
    # More realistic inputs - cash and futures closer together
    cash_price = 95.50
    futures_price = 97.00
    conversion_factor = 0.9750
    coupon_rate = 0.045
    days_to_delivery = 90

    print("Futures implied:", 97.00 * 0.9750)  # Should be close to cash price
    print("Implied repo:", implied_repo(cash_price, futures_price, conversion_factor, coupon_rate, days_to_delivery))


#fredapi = 6b7d1e80e07184ec932224819620d112