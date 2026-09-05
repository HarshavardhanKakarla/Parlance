import json
import logging
import re

from . import config

logger = logging.getLogger("risk_sentinel.llm_agent")

_client_configured = False
_genai_module = None


def _get_client():
    """Lazily configure the Gemini client. Returns None (demo/offline mode)
    if no API key is configured, so the app still runs end-to-end without one.

    Unlike the Anthropic SDK, google-generativeai doesn't hand back a
    per-call client object — `genai.configure(...)` sets a module-level API
    key and `genai.GenerativeModel(...)` is constructed per call. We still
    return a truthy/falsy sentinel here (the configured `genai` module, or
    None) so callers can keep the same "if client is None: fallback" shape."""
    global _client_configured, _genai_module
    if _client_configured:
        return _genai_module
    _client_configured = True
    if not config.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — LLM agent running in offline fallback mode.")
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=config.GEMINI_API_KEY)
        _genai_module = genai
    except Exception:
        # Previously swallowed silently, which made a real configuration/import
        # error look identical to "no key set" — logged now so it shows up in
        # uvicorn's console instead of masquerading as the offline fallback.
        logger.exception("Failed to configure google-generativeai client; falling back to offline mode.")
        _genai_module = None
    return _genai_module


# Gemini's function-calling schema is the same OpenAPI-subset JSON Schema
# Anthropic's tool_use uses (type/properties/enum/required), so this is a
# near-verbatim port of the old POLICY_TOOL — just nested under
# "function_declarations" the way google-generativeai expects, with
# "input_schema" renamed to "parameters".
POLICY_TOOL = {
    "function_declarations": [
        {
            "name": "apply_policy_change",
            "description": (
                "Translate a merchant's free-text steering instruction into a structured "
                "policy delta for the risk-scoring engine. If the instruction is too vague "
                "to map onto a specific signal confidently, set clarification_needed=true "
                "and explain why in human_summary instead of guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["adjust_threshold", "no_op"],
                        "description": "adjust_threshold to change a weight, no_op if nothing should change.",
                    },
                    "signal": {
                        "type": "string",
                        "enum": [
                            "device_new_weight",
                            "retry_weight",
                            "typing_anomaly_weight",
                            "geo_mismatch_weight",
                            "time_anomaly_weight",
                            "blocked_history_weight",
                            "chargeback_weight",
                        ],
                        "description": (
                            "Which RISK weight to change. These are all deduction weights, so "
                            "'increase' always means stricter/more-suspicious and 'decrease' "
                            "always means more lenient — never propose a signal outside this "
                            "list (e.g. trust bonuses aren't merchant-adjustable, to avoid "
                            "inverted-sign mistakes)."
                        ),
                    },
                    "scope": {
                        "type": "string",
                        "enum": [
                            "global",
                            "cod_international",
                            "cod",
                            "international",
                            "new_device",
                            "high_value",
                        ],
                        "description": "global applies everywhere; other values apply only to that transaction segment.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["increase", "decrease"],
                    },
                    "magnitude": {
                        "type": "string",
                        "enum": ["slight", "moderate", "strong"],
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0-1 confidence that this delta correctly captures the merchant's intent.",
                    },
                    "clarification_needed": {
                        "type": "boolean",
                        "description": "true if the instruction was too ambiguous to map confidently.",
                    },
                    "human_summary": {
                        "type": "string",
                        "description": "One or two plain-language sentences confirming what changed (or what's unclear), for the merchant chat.",
                    },
                },
                "required": ["action", "human_summary", "confidence", "clarification_needed"],
            },
        }
    ]
}


def explain_decision(features: dict, score: float, band: str, contributions: dict) -> str:
    genai = _get_client()
    if genai is None:
        return _fallback_explanation(features, score, band, contributions)

    ranked = sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
    prompt = (
        "You are a fraud-risk analyst assistant for an Indian merchant dashboard. "
        "Explain this transaction's trust-score decision in 2-3 plain sentences, "
        "in the merchant's language (no jargon), citing the SPECIFIC feature values "
        "that drove it (not a generic score readout). Mention any mitigating factors too.\n\n"
        f"Score: {score}/100, Band: {band.upper()}\n"
        f"Feature values: {json.dumps(features)}\n"
        f"Ranked contributions (signal: points added/subtracted): {json.dumps(dict(ranked))}\n"
    )
    try:
        model = genai.GenerativeModel(config.GEMINI_MODEL)
        resp = model.generate_content(
            prompt,
            # Gemini 3.x models spend part of the output budget on hidden
            # "thinking" tokens before producing visible text; 300 was fine
            # for older Gemini generations but truncated 3.x free-text output
            # mid-sentence. 4096 gives enough room for both.
            generation_config=genai.types.GenerationConfig(max_output_tokens=4096),
        )
        text = (resp.text or "").strip()
        return text or _fallback_explanation(features, score, band, contributions)
    except Exception as e:
        return _fallback_explanation(features, score, band, contributions) + f" (LLM unavailable: {e})"


def _fallback_explanation(features, score, band, contributions):
    ranked = sorted(contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
    negatives = [k for k, v in ranked if v < 0][:2]
    positives = [k for k, v in ranked if v > 0][:1]
    label_map = {
        "new_device": "this is a device that's never been seen before",
        "geo_mismatch": f"the billing city is {features.get('billing_city')} but the transaction is {features.get('geo_distance_km')}km away",
        "retry_count": f"there were {features.get('retry_count')} retries recently",
        "typing_anomaly": "interaction cadence looked automated/unusual",
        "time_anomaly": "the timing is unusual for this customer",
        "past_blocked": f"there's a history of {features.get('past_blocked_count')} blocked attempts",
        "chargebacks": f"there have been {features.get('chargeback_count')} chargebacks",
        "device_history": f"this device has {features.get('device_seen_count')} prior clean transactions",
        "account_age": f"the account is {features.get('account_age_days')} days old",
    }
    reasons = "; ".join(label_map.get(k, k) for k in negatives) or "no strong risk signals"
    mitigant = f" However, {label_map.get(positives[0], positives[0])}, which offset some risk." if positives else ""
    return f"Flagged {band.capitalize()} ({score}/100): {reasons}.{mitigant}"


def parse_instruction(instruction: str, current_policy: dict) -> dict:
    """Returns a dict with the tool's structured fields, always including
    confidence and clarification_needed so the caller can gate auto-apply."""
    genai = _get_client()
    if genai is None:
        return _fallback_parse(instruction)

    prompt = (
        "A merchant is steering a live fraud-risk scoring policy via chat. "
        "Map their instruction to the apply_policy_change function. If the instruction "
        "names a general theme (e.g. 'international orders', 'COD') without naming an "
        "exact signal, pick the single most relevant signal rather than asking for "
        "clarification — for cross-border/COD risk, geo_mismatch_weight is typically "
        "the most relevant. Only set clarification_needed=true if the instruction gives "
        "no usable signal at all (e.g. 'make it better'). Current global "
        f"weights: {json.dumps(current_policy['global'])}. "
        f"Merchant instruction: \"{instruction}\""
    )
    try:
        # Plain dicts are NOT reliably honored for tool_config by this SDK —
        # passing one is silently ignored, leaving the model in default AUTO
        # mode where it can just answer in plain text instead of calling the
        # function. Typed proto objects are required to actually force it.
        tool_config = genai.protos.ToolConfig(
            function_calling_config=genai.protos.FunctionCallingConfig(
                mode=genai.protos.FunctionCallingConfig.Mode.ANY,
                allowed_function_names=["apply_policy_change"],
            )
        )
        model = genai.GenerativeModel(
            config.GEMINI_MODEL,
            tools=[POLICY_TOOL],
            tool_config=tool_config,
        )
        resp = model.generate_content(
            prompt,
            # Same hidden-thinking-token consideration as explain_decision,
            # though structured tool-call output needs less headroom than
            # free text — 1024 has been sufficient in testing.
            generation_config=genai.types.GenerationConfig(max_output_tokens=1024),
        )
        candidates = resp.candidates or []
        if candidates:
            for part in candidates[0].content.parts:
                fc = getattr(part, "function_call", None)
                if fc and fc.name == "apply_policy_change":
                    result = dict(fc.args)
                    result.setdefault("scope", "global")
                    result.setdefault("direction", "increase")
                    result.setdefault("magnitude", "moderate")
                    return result
        # Reached if Gemini responded but didn't emit a function_call (e.g.
        # empty candidates/parts) — previously this branch was nested inside
        # the for-loop and could fall through returning None on an empty
        # `parts` list, causing a 500 in main.py's `.get()` calls downstream.
        fallback = _fallback_parse(instruction)
        fallback["human_summary"] = f"{fallback['human_summary']} (LLM returned no policy function call)"
        return fallback
    except Exception as e:
        fallback = _fallback_parse(instruction)
        fallback["human_summary"] = f"{fallback['human_summary']} (LLM unavailable: {e})"
        return fallback


_SIGNAL_KEYWORDS = {
    "geo_mismatch_weight": ["geo", "location", "distance", "international", "abroad", "country"],
    "device_new_weight": ["device", "new device", "unrecognized device"],
    "retry_weight": ["retry", "retries", "attempt"],
    "typing_anomaly_weight": ["typing", "cadence", "bot", "automation"],
    "time_anomaly_weight": ["time of day", "odd hours", "timing"],
    "blocked_history_weight": ["blocked", "declined before"],
    "chargeback_weight": ["chargeback", "refund", "dispute"],
}
_SCOPE_KEYWORDS = {
    "cod_international": ["international cod", "cod international"],
    "cod": ["cod", "cash on delivery"],
    "international": ["international", "abroad", "overseas", "foreign"],
    "new_device": ["new device"],
    "high_value": ["high value", "large order", "big ticket"],
}


def _fallback_parse(instruction: str) -> dict:
    """Deterministic keyword-based stand-in used when no GEMINI_API_KEY is
    set, so the demo still works offline. Intentionally conservative: anything
    it can't confidently match gets flagged for manual review."""
    text = instruction.lower()

    signal = next((s for s, kws in _SIGNAL_KEYWORDS.items() if any(k in text for k in kws)), None)
    scope = "global"
    for s, kws in _SCOPE_KEYWORDS.items():
        if any(k in text for k in kws):
            scope = s
            break

    direction = "increase"
    if any(w in text for w in ["strict", "increase", "harder", "tighter", "more cautious", "flag more"]):
        direction = "increase"
    elif any(w in text for w in ["loosen", "decrease", "relax", "less strict", "trust", "stop flagging", "ease up"]):
        direction = "decrease"

    magnitude = "moderate"
    if any(w in text for w in ["much", "significantly", "a lot", "aggressively"]):
        magnitude = "strong"
    elif any(w in text for w in ["slightly", "a little", "bit"]):
        magnitude = "slight"

    if signal is None:
        return {
            "action": "no_op",
            "signal": None,
            "scope": scope,
            "direction": direction,
            "magnitude": magnitude,
            "confidence": 0.25,
            "clarification_needed": True,
            "human_summary": (
                "I couldn't confidently map that instruction to a specific scoring "
                "signal (offline/no-API-key mode). Could you name the factor, e.g. "
                "'geo mismatch', 'new devices', 'retries', or 'chargebacks'?"
            ),
        }

    confidence = 0.8 if scope != "global" or len(text.split()) > 3 else 0.55
    return {
        "action": "adjust_threshold",
        "signal": signal,
        "scope": scope,
        "direction": direction,
        "magnitude": magnitude,
        "confidence": confidence,
        "clarification_needed": False,
        "human_summary": (
            f"{'Increased' if direction == 'increase' else 'Decreased'} {signal.replace('_', ' ')} "
            f"({magnitude}) for scope '{scope}'."
        ),
    }
