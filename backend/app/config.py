import os

# The Gemini model used for both the explanation and policy-parsing calls.
# Override with GEMINI_MODEL if you want to point at a different model.
#
# As of Sept 2026, confirmed by live testing: gemini-2.5-flash and
# gemini-2.0-flash both 404 for new API keys ("no longer available to new
# users"). gemini-3.6-flash and gemini-3.5-flash both listed as available and
# generate content successfully, but forced function-calling (used by
# parse_instruction) was only confirmed reliable on gemini-3.5-flash in
# testing with google-generativeai==0.8.3 — see llm_agent.py for the specific
# fixes (typed ToolConfig, raised token budgets) this required. If this
# default 404s/misbehaves again in the future, check the live error text
# (more reliable than any doc snapshot) before hardcoding a replacement.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# If no GEMINI_API_KEY is set, the LLM agent falls back to deterministic
# rule-based stand-ins so the whole app still runs/demos offline.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

DB_PATH = os.environ.get("RISK_SENTINEL_DB", os.path.join(os.path.dirname(__file__), "..", "risk_sentinel.db"))

# Confidence below this triggers the manual-review fallback path instead of
# auto-applying a policy change.
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.6"))

