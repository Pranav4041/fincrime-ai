def extract_signals(transaction, features=None):
    signals = {
        "high_amount": transaction.get("amount", 0) > 50000,
        "odd_hour": transaction.get("hour", 12) < 5,
        "new_device": transaction.get("is_new_device", False),
        "location_mismatch": transaction.get("distance_km", 0) > 500,
        "high_velocity": transaction.get("tx_last_10min", 0) > 5
    }

    active_signals = [k for k, v in signals.items() if v]
    return active_signals