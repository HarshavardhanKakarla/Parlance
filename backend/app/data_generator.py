import random

CITIES = [
    ("Delhi", 28.6139, 77.2090),
    ("Mumbai", 19.0760, 72.8777),
    ("Bengaluru", 12.9716, 77.5946),
    ("Chennai", 13.0827, 80.2707),
    ("Kolkata", 22.5726, 88.3639),
    ("Pune", 18.5204, 73.8567),
    ("Jaipur", 26.9124, 75.7873),
]

FOREIGN_CITIES = [
    ("Dubai", 25.2048, 55.2708),
    ("Singapore", 1.3521, 103.8198),
    ("Lagos", 6.5244, 3.3792),
    ("Bangkok", 13.7563, 100.5018),
]


def _dist_km(a, b):
    # rough flat-earth approximation, plenty for synthetic demo data
    return round((((a[0] - b[0]) * 111) ** 2 + ((a[1] - b[1]) * 111) ** 2) ** 0.5, 1)


def _gen_legit():
    """Mostly squeaky-clean, but ~30% of the time modeled with the kind of
    ordinary messiness real customers produce (a retry on a slow connection,
    checking out on a new device while traveling domestically) — these stay
    Green under sane weights but are exactly what an over-tuned rigid policy
    ends up mis-flagging (see the failure-story preset)."""
    home = random.choice(CITIES)
    edge_case = random.random() < 0.3

    if edge_case:
        other = random.choice(CITIES)
        distance = _dist_km((home[1], home[2]), (other[1], other[2])) if other != home else 0.0
        return {
            "device_seen_count": random.choice([0, 0, 1]),
            "retry_count": random.choice([1, 1, 2]),
            "typing_anomaly": False,
            "geo_mismatch": distance > 100,
            "geo_distance_km": distance,
            "time_anomaly": False,
            "past_blocked_count": 0,
            "chargeback_count": 0,
            "account_age_days": random.randint(200, 1500),
            "is_cod": random.random() < 0.3,
            "is_international": False,
            "amount_inr": random.randint(300, 8000),
            "billing_city": home[0],
        }

    return {
        "device_seen_count": random.randint(3, 40),
        "retry_count": random.choice([0, 0, 0, 1]),
        "typing_anomaly": False,
        "geo_mismatch": False,
        "geo_distance_km": 0.0,
        "time_anomaly": False,
        "past_blocked_count": 0,
        "chargeback_count": 0,
        "account_age_days": random.randint(120, 1500),
        "is_cod": random.random() < 0.3,
        "is_international": False,
        "amount_inr": random.randint(300, 8000),
        "billing_city": home[0],
    }


def _gen_fraud():
    home = random.choice(CITIES)
    away = random.choice(FOREIGN_CITIES)
    return {
        "device_seen_count": 0,
        "retry_count": random.randint(3, 8),
        "typing_anomaly": True,
        "geo_mismatch": True,
        "geo_distance_km": _dist_km((home[1], home[2]), (away[1], away[2])),
        "time_anomaly": True,
        "past_blocked_count": random.randint(1, 4),
        "chargeback_count": random.randint(0, 2),
        "account_age_days": random.randint(0, 10),
        "is_cod": random.random() < 0.5,
        "is_international": True,
        "amount_inr": random.randint(5000, 60000),
        "billing_city": home[0],
    }


def _gen_ambiguous():
    home = random.choice(CITIES)
    other = random.choice(CITIES + FOREIGN_CITIES)
    is_intl = other in FOREIGN_CITIES
    distance = _dist_km((home[1], home[2]), (other[1], other[2])) if other != home else round(random.uniform(0, 40), 1)
    return {
        "device_seen_count": random.choice([0, 1, 2]),
        "retry_count": random.randint(1, 3),
        "typing_anomaly": random.random() < 0.4,
        "geo_mismatch": distance > 100,
        "geo_distance_km": distance,
        "time_anomaly": random.random() < 0.5,
        "past_blocked_count": random.choice([0, 0, 1]),
        "chargeback_count": 0,
        "account_age_days": random.randint(5, 120),
        "is_cod": random.random() < 0.5,
        "is_international": is_intl,
        "amount_inr": random.randint(1000, 20000),
        "billing_city": home[0],
    }


GENERATORS = {
    "legit": _gen_legit,
    "fraud": _gen_fraud,
    "ambiguous": _gen_ambiguous,
}


def generate_batch(n: int = 60, weights=(0.45, 0.25, 0.30)):
    """Returns a list of (scenario_label, features) tuples with a realistic
    mix of clearly-legit, clearly-fraud, and ambiguous-edge-case transactions."""
    scenarios = random.choices(list(GENERATORS.keys()), weights=weights, k=n)
    return [(s, GENERATORS[s]()) for s in scenarios]


def generate_one(scenario: str = None):
    scenario = scenario or random.choices(
        list(GENERATORS.keys()), weights=[0.45, 0.25, 0.30]
    )[0]
    return scenario, GENERATORS[scenario]()


def make_cod_international_probe():
    """A transaction deliberately tuned to sit right at the Yellow/Red boundary
    under the DEFAULT policy for the cod_international segment (score ~40.3,
    just inside Yellow). A single 'moderate' tightening of geo-mismatch weight
    for that segment (the spec's own worked example) drops it to ~34.7 (Red) —
    this is the live before/after moment for the demo script in section 8.
    Distance and retry/device/age values are fixed (not randomized) so the
    crossing is reliable every run; only the display city varies."""
    home = random.choice(CITIES)
    away = random.choice(FOREIGN_CITIES)
    return "probe", {
        "device_seen_count": 0,
        "retry_count": 5,
        "typing_anomaly": False,
        "geo_mismatch": True,
        "geo_distance_km": 3200.0,  # fixed, well past the 500km factor cap
        "time_anomaly": False,
        "past_blocked_count": 0,
        "chargeback_count": 0,
        "account_age_days": 10,
        "is_cod": True,
        "is_international": True,
        "amount_inr": 4200,
        "billing_city": home[0],
        "counterparty_city": away[0],
    }
