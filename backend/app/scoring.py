"""
Weighted rule-engine scorer. Deliberately simple (per spec: "don't over-engineer
the ML here, it's not the differentiator") — every weight lives in the policy
store so the conversational agent has something real to edit.
"""

SEGMENT_MATCHERS = {
    # scope name -> predicate over a transaction's features
    "cod_international": lambda f: f["is_cod"] and f["is_international"],
    "cod": lambda f: f["is_cod"],
    "international": lambda f: f["is_international"],
    "new_device": lambda f: f["device_seen_count"] == 0,
    "high_value": lambda f: f["amount_inr"] >= 15000,
}


def matching_segments(features: dict):
    return [name for name, pred in SEGMENT_MATCHERS.items() if pred(features)]


def _effective_weights(policy: dict, features: dict):
    """Merge global weights with any matching segment overrides (last one wins,
    in the fixed order of SEGMENT_MATCHERS so behavior is deterministic)."""
    weights = dict(policy["global"])
    for seg in matching_segments(features):
        overrides = policy.get("segments", {}).get(seg)
        if overrides:
            weights.update(overrides)
    return weights


def score_transaction(features: dict, policy: dict):
    w = _effective_weights(policy, features)
    contributions = {}

    base = 100.0

    # --- Behavioral ---
    if features["device_seen_count"] == 0:
        contributions["new_device"] = -w["device_new_weight"]
    else:
        bonus = w["device_history_bonus"] * min(features["device_seen_count"], 10)
        contributions["device_history"] = bonus

    retries = min(features["retry_count"], 5)
    if retries:
        contributions["retry_count"] = -w["retry_weight"] * retries

    if features["typing_anomaly"]:
        contributions["typing_anomaly"] = -w["typing_anomaly_weight"]

    # --- Contextual ---
    if features["geo_mismatch"]:
        distance_factor = min(features["geo_distance_km"] / 500.0, 1.0)
        contributions["geo_mismatch"] = -w["geo_mismatch_weight"] * max(distance_factor, 0.3)

    if features["time_anomaly"]:
        contributions["time_anomaly"] = -w["time_anomaly_weight"]

    # --- Historical ---
    blocked = min(features["past_blocked_count"], 5)
    if blocked:
        contributions["past_blocked"] = -w["blocked_history_weight"] * blocked

    chargebacks = min(features["chargeback_count"], 3)
    if chargebacks:
        contributions["chargebacks"] = -w["chargeback_weight"] * chargebacks

    age_bonus = w["account_age_bonus_max"] * min(features["account_age_days"] / 365.0, 1.0)
    contributions["account_age"] = age_bonus

    total = base + sum(contributions.values())
    total = max(0.0, min(100.0, total))

    thresholds = policy["thresholds"]
    if total >= thresholds["green"]:
        band = "green"
    elif total >= thresholds["yellow"]:
        band = "yellow"
    else:
        band = "red"

    return round(total, 1), band, contributions


def apply_delta(policy: dict, delta: dict):
    """Mutate a policy dict in place given a structured delta from the LLM
    agent. Returns (old_value, new_value) for the changed weight so callers
    can show a clean before/after."""
    signal = delta["signal"]
    scope = delta.get("scope", "global")
    direction = delta["direction"]
    magnitude = delta.get("magnitude", "moderate")

    from .database import MAGNITUDE_MULTIPLIERS

    mult = MAGNITUDE_MULTIPLIERS.get(magnitude, MAGNITUDE_MULTIPLIERS["moderate"])
    sign = 1 if direction == "increase" else -1

    if scope == "global":
        target = policy["global"]
        base_value = target.get(signal)
        if base_value is None:
            raise ValueError(f"Unknown signal '{signal}'")
        new_value = round(base_value * (1 + sign * mult), 2)
        target[signal] = new_value
        return signal, "global", base_value, new_value

    # Segment-scoped: inherit current effective value from global unless
    # already overridden for this segment.
    segments = policy.setdefault("segments", {})
    seg_overrides = segments.setdefault(scope, {})
    base_value = seg_overrides.get(signal, policy["global"].get(signal))
    if base_value is None:
        raise ValueError(f"Unknown signal '{signal}'")
    new_value = round(base_value * (1 + sign * mult), 2)
    seg_overrides[signal] = new_value
    return signal, scope, base_value, new_value
