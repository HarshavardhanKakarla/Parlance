from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config, data_generator, database, llm_agent, scoring

app = FastAPI(title="Risk Sentinel API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    database.init_db()


# ---------- Transactions ----------

class GenerateBatchRequest(BaseModel):
    count: int = 60


@app.post("/api/transactions/generate")
def generate_batch(req: GenerateBatchRequest):
    policy = database.get_policy()
    created = []
    for scenario, features in data_generator.generate_batch(req.count):
        score, band, contributions = scoring.score_transaction(features, policy)
        tx_id = database.insert_transaction(scenario, features, score, band, contributions)
        created.append(database.get_transaction(tx_id))
    database.add_audit_entry("batch_generated", {"count": len(created)})
    return {"created": len(created), "transactions": created}


@app.post("/api/transactions/probe")
def generate_probe():
    """Generates a single cod_international-shaped transaction near the
    Yellow/Green boundary — used to demo the live before/after of a policy
    change (spec section 8, step 5)."""
    policy = database.get_policy()
    scenario, features = data_generator.make_cod_international_probe()
    score, band, contributions = scoring.score_transaction(features, policy)
    tx_id = database.insert_transaction(scenario, features, score, band, contributions)
    tx = database.get_transaction(tx_id)
    database.add_audit_entry("probe_transaction", {"transaction_id": tx_id, "score": score, "band": band})
    return tx


@app.get("/api/transactions")
def list_transactions(limit: int = 200):
    return database.list_transactions(limit)


@app.get("/api/transactions/{tx_id}")
def get_transaction(tx_id: int):
    tx = database.get_transaction(tx_id)
    if not tx:
        raise HTTPException(404, "transaction not found")
    return tx


@app.post("/api/transactions/{tx_id}/explain")
def explain_transaction(tx_id: int):
    tx = database.get_transaction(tx_id)
    if not tx:
        raise HTTPException(404, "transaction not found")
    if tx["explanation"]:
        return {"explanation": tx["explanation"], "cached": True}
    explanation = llm_agent.explain_decision(tx["features"], tx["score"], tx["band"], tx["contributions"])
    database.set_transaction_explanation(tx_id, explanation)
    database.add_audit_entry("decision_explained", {"transaction_id": tx_id, "explanation": explanation})
    return {"explanation": explanation, "cached": False}


@app.post("/api/transactions/rescore_all")
def rescore_all():
    """Re-scores every stored transaction under the current policy — this is
    what makes a policy change visibly ripple through the whole feed."""
    policy = database.get_policy()
    txs = database.list_transactions(10_000)
    changed = 0
    for tx in txs:
        score, band, contributions = scoring.score_transaction(tx["features"], policy)
        if band != tx["band"] or abs(score - tx["score"]) > 0.01:
            changed += 1
        database.rescore_transaction(tx["id"], score, band, contributions)
    database.add_audit_entry("rescored_all", {"total": len(txs), "changed": changed})
    return {"total": len(txs), "changed": changed}


# ---------- Policy ----------

@app.get("/api/policy")
def get_policy():
    return database.get_policy()


@app.post("/api/policy/preset/rigid")
def apply_rigid_preset():
    """Demo helper for the failure story (spec section 9): swaps in a
    deliberately too-strict policy so a rescore visibly pushes legitimate
    transactions into Yellow. Pair with /api/transactions/rescore_all."""
    import copy
    database.save_policy(copy.deepcopy(database.RIGID_DEMO_POLICY))
    database.add_audit_entry("rigid_preset_applied", {"note": "Thresholds intentionally tightened for failure-story demo"})
    return database.get_policy()


@app.post("/api/policy/preset/reset")
def reset_policy():
    """Resets to the sane default policy — the 'adaptive correction' half of
    the failure story."""
    import copy
    database.save_policy(copy.deepcopy(database.DEFAULT_POLICY))
    database.add_audit_entry("policy_reset", {"note": "Reset to default policy"})
    return database.get_policy()


# ---------- Conversational agent ----------

class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    policy = database.get_policy()
    parsed = llm_agent.parse_instruction(req.message, policy)

    if parsed.get("action") != "adjust_threshold" or parsed.get("clarification_needed") or parsed.get("confidence", 0) < config.CONFIDENCE_THRESHOLD:
        pc_id = database.insert_pending_change(
            req.message, parsed, parsed.get("confidence", 0), parsed.get("human_summary", "")
        )
        database.add_audit_entry(
            "manual_review_flagged",
            {"pending_change_id": pc_id, "instruction": req.message, "parsed": parsed},
        )
        return {
            "status": "needs_confirmation",
            "pending_change_id": pc_id,
            "summary": parsed.get("human_summary"),
            "parsed": parsed,
        }

    signal, scope, old_value, new_value = scoring.apply_delta(policy, parsed)
    database.save_policy(policy)
    database.add_audit_entry(
        "policy_changed",
        {
            "instruction": req.message,
            "signal": signal,
            "scope": scope,
            "old_value": old_value,
            "new_value": new_value,
            "confidence": parsed.get("confidence"),
            "summary": parsed.get("human_summary"),
        },
    )
    return {
        "status": "applied",
        "summary": parsed.get("human_summary"),
        "signal": signal,
        "scope": scope,
        "old_value": old_value,
        "new_value": new_value,
    }


class ConfirmRequest(BaseModel):
    approve: bool


@app.post("/api/chat/confirm/{pc_id}")
def confirm_pending_change(pc_id: int, req: ConfirmRequest):
    pending = database.get_pending_change(pc_id)
    if not pending:
        raise HTTPException(404, "pending change not found")
    if pending["status"] != "pending":
        raise HTTPException(400, f"already {pending['status']}")

    if not req.approve:
        database.set_pending_change_status(pc_id, "rejected")
        database.add_audit_entry("manual_review_rejected", {"pending_change_id": pc_id})
        return {"status": "rejected"}

    delta = pending["proposed_delta"]
    if delta.get("action") != "adjust_threshold" or not delta.get("signal"):
        database.set_pending_change_status(pc_id, "rejected")
        raise HTTPException(400, "this proposal has no concrete signal to apply; please rephrase the instruction")

    policy = database.get_policy()
    signal, scope, old_value, new_value = scoring.apply_delta(policy, delta)
    database.save_policy(policy)
    database.set_pending_change_status(pc_id, "approved")
    database.add_audit_entry(
        "policy_changed",
        {
            "instruction": pending["instruction"],
            "signal": signal,
            "scope": scope,
            "old_value": old_value,
            "new_value": new_value,
            "confidence": pending["confidence"],
            "manual_review": True,
        },
    )
    return {"status": "applied", "signal": signal, "scope": scope, "old_value": old_value, "new_value": new_value}


@app.get("/api/chat/pending")
def list_pending():
    return database.list_pending_changes("pending")


# ---------- Audit trail ----------

@app.get("/api/audit")
def audit(limit: int = 200):
    return database.list_audit_entries(limit)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_configured": bool(config.GEMINI_API_KEY), "model": config.GEMINI_MODEL}
