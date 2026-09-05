# Parlance

### Fraud scoring you can talk to

_(Codebase/repo name: `risk-sentinel` - kept as-is internally; "Parlance" is
the product/brand name used in the pitch and UI.)_

Real-time transaction trust-scoring with a **conversational policy layer** -
merchants don't just see a Green/Yellow/Red decision, they can steer the
engine live in plain English and watch it change behavior on the next
transaction.

Built for Razorpay AI Buildathon 2026 - Track 02: AI Risk Manager.

## Why this, not just "better classifier + dashboard"

Most fraud-scoring demos stop at a classifier and a chart. Parlance's
differentiator is that a merchant can type `"be stricter on international COD
orders"` and:

1. Gemini parses it into a structured policy delta (which signal, which
   segment, which direction, how strong).
2. The delta is applied to a live policy store and logged to an audit trail.
3. The dashboard shows the _next_ matching transaction scored under the new
   policy, in front of you.

If the parse is ambiguous or low-confidence, the change is **not** silently
applied - it's flagged for merchant confirmation instead. That's both a
safety story and the project's answer to the "Failure Recovery" pillar.

## Architecture

```
┌─────────────────┐      ┌───────────────────────┐      ┌────────────────────┐
│  Transaction     │─────▶│  Scoring Service       │─────▶│  Trust Band         │
│  Simulator       │      │  (weighted rule engine) │      │  Green/Yellow/Red   │
└─────────────────┘      └───────────────────────┘      └─────────┬──────────┘
                                                                     │
┌─────────────────┐      ┌───────────────────────┐      ┌─────────▼──────────┐
│  Merchant Chat   │◀────▶│  LLM Reasoning Agent   │◀────▶│  Policy Store       │
│  (React UI)      │      │  (explain + steer)      │      │  (SQLite)           │
└─────────────────┘      └───────────────────────┘      └────────────────────┘
         │                                                          │
         ▼                                                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Dashboard: live ledger, trust bands, audit trail, agent explanations,     │
│  applied policy changes                                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Backend:** FastAPI + SQLite (`backend/app/`)
  - `data_generator.py` - synthetic transaction generator (legit / fraud /
    ambiguous mixes, plus a deterministic "probe" tuned to demo a live
    Yellow→Red crossing)
  - `scoring.py` - weighted rule engine; every weight lives in the policy
    store, not hardcoded, so the agent has something real to edit
  - `llm_agent.py` - two Gemini-backed functions: `explain_decision` and
    `parse_instruction` (forced tool-use for structured output), each with a
    deterministic offline fallback so the app runs end-to-end without an API
    key
  - `database.py` - SQLite schema: transactions, policy, audit log, pending
    (manual-review) changes
  - `main.py` - REST API wiring all of the above
- **Frontend:** React + Vite (`frontend/src/`) - three-pane dashboard: live
  ledger, transaction detail + explanation, agent chat / audit trail

## Setup

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
cp .env.example .env   # then fill in GEMINI_API_KEY (optional - see below)
export $(grep -v '^#' .env | xargs)   # or just `export GEMINI_API_KEY=...`
uvicorn app.main:app --reload --port 8000
```

Health check: `curl http://localhost:8000/api/health`

**No API key?** The app still runs completely - `llm_agent.py` falls back to
deterministic, rule-based explanations and a keyword-based instruction parser
so you can demo the whole flow offline. The dashboard shows an "offline demo
mode" badge when this is active. For the real Gemini-powered explanations and
free-text policy parsing (the actual differentiator), set `GEMINI_API_KEY` -
get one free, no billing required, from
[Google AI Studio](https://aistudio.google.com).

### Frontend

```bash
cd frontend
npm install
npm run dev       # dev server on http://localhost:5173
# or: npm run build && npm run preview
```

The frontend talks to `http://localhost:8000` by default; override with
`VITE_API_BASE` if needed.

## Gemini integration notes (learned the hard way)

If you're setting up a fresh key and hit issues, these were all real,
confirmed problems during development - check them in this order:

1. **`403 PermissionDenied` / "project has been denied access"** on every
   model despite a valid key that can list models - this is an account/project-level
   restriction on Google's side, not a code or model-name issue. Generating a
   fresh key from a plain personal Google account via
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (rather
   than a manually-configured Cloud Console project) resolved this in
   testing.
2. **`404 ... no longer available to new users`** - model names get
   deprecated; the error message itself names the current replacement, which
   is more reliable than any hardcoded default (including this repo's).
3. **Forced function-calling (`parse_instruction`) silently returns no
   function call, with no error** - `tool_config` passed as a plain Python
   dict is not reliably honored by `google-generativeai`; it must be built
   with typed `genai.protos.ToolConfig`/`FunctionCallingConfig` objects (see
   `llm_agent.py`), or the model silently falls back to default `AUTO` mode.
4. **Explanations/responses truncate mid-sentence** - Gemini 3.x models
   spend part of `max_output_tokens` on hidden "thinking" tokens before
   visible output; 300–400 tokens (fine for older Gemini generations) isn't
   enough headroom. `llm_agent.py` uses 4096 for free-text explanations and
   1024 for structured tool-call output.
5. **`--reload` doesn't pick up `.env` changes** - uvicorn's `--reload` only
   re-executes code on file changes; environment variables are read once at
   process start. Always fully stop/restart (not just save-and-reload) after
   editing `.env`.

## Demo script (matches the scored pitch video)

1. Click **Generate batch** - ~60 synthetic transactions land in the ledger,
   color-coded Green / Yellow / Red.
2. Click a Yellow transaction, then **Explain this decision** - the agent
   cites the specific features that drove the score, not a generic readout.
3. In the chat panel, type: `increase the geo mismatch weight for
international cash on delivery orders`. (The spec's own phrasing, `be
stricter on international COD orders`, also works but has occasionally
   asked for clarification instead of applying directly - Gemini's judgment
   call on an implicit instruction, not a bug. The more explicit phrasing
   above reliably applies on the first try, which matters for a one-take
   demo recording. The agent confirms what it changed (`geo_mismatch_weight`,
   scope `cod_international`, old → new value) and it's logged to the audit
   trail.
4. Click **Run cod_intl probe** - this generates a transaction shaped exactly
   for that segment. Before your chat instruction it would have scored
   Yellow (~40.3); after it, it scores Red (~34.7) under the exact same
   feature values. Re-run the probe before/after to see the live shift.
5. **Failure story:** click **Simulate rigid policy** - an intentionally
   over-tuned policy is applied and the whole ledger is rescored; a batch of
   genuinely legitimate transactions (an occasional retry, a new device while
   traveling domestically) get incorrectly pushed to Yellow/Red. Click
   **Reset policy** to correct it live. The audit trail shows both events and
   the real before/after false-positive counts.
6. Try an ambiguous instruction like `make things better somehow` - the agent
   won't guess; it flags the proposal for manual confirmation (Apply
   anyway / Discard) rather than silently mutating policy.

## Evaluation pillars

- **Problem Taste:** static/black-box scoring gives merchants no lever
  between "trust the model" and "turn it off." The conversational layer is
  that lever, applied live, not on a retraining cycle.
- **Build Quality:** clean separation of scoring, policy store, and LLM
  layer; audit-logged everything; offline fallback so the app is never
  Gemini-API-dependent for a demo.
- **AI Judgment:** simple weighted rule engine on purpose (no over-engineered
  ML); Gemini is reserved for the two things an LLM is actually good at here
  - natural-language explanation and free-text-to-structured-policy parsing
  - via forced tool use, not freeform code/logic edits.
- **Failure Recovery:** low-confidence parses are never auto-applied - they
  go to a manual-review queue the merchant must confirm. The rigid→reset
  preset pair demonstrates, with real numbers from the synthetic run, both a
  concrete failure (over-tuned policy mis-flagging legitimate transactions)
  and its correction.

## What's intentionally simulated (per spec)

No real device fingerprinting, geolocation APIs, or payment integration -
all inputs are synthetic. The anomaly detection is a transparent weighted
rule engine, not a black-box model, since the scoring approach isn't the
differentiator here.
