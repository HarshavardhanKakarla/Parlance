import { useState } from "react";
import { FEATURE_LABELS, fmtValue } from "./TransactionLedger.jsx";

const CONTRIB_LABELS = {
  new_device: "New device",
  device_history: "Device history",
  retry_count: "Retry count",
  typing_anomaly: "Cadence anomaly",
  geo_mismatch: "Geo mismatch",
  time_anomaly: "Time anomaly",
  past_blocked: "Past blocked attempts",
  chargebacks: "Chargeback history",
  account_age: "Account age",
};

export default function TransactionDetail({ tx, onExplain, explaining }) {
  if (!tx) {
    return (
      <div className="detail-empty">
        Select a transaction from the ledger to see its feature values, score
        breakdown, and — for Yellow or Red decisions — a plain-language
        explanation from the agent.
      </div>
    );
  }

  const maxAbs = Math.max(
    1,
    ...Object.values(tx.contributions).map((v) => Math.abs(v))
  );

  return (
    <div className="detail">
      <div className="detail-score-row">
        <span className={`detail-score ${tx.band}`}>{tx.score}</span>
        <span className={`band-badge ${tx.band}`}>{tx.band}</span>
      </div>
      <div className="detail-sub">
        Transaction #{tx.id} · {tx.scenario} scenario · {new Date(tx.created_at).toLocaleString()}
      </div>

      <div className="feature-grid">
        {Object.entries(tx.features)
          .filter(([k]) => FEATURE_LABELS[k])
          .map(([k, v]) => (
            <div className="feature-cell" key={k}>
              <div className="feature-label">{FEATURE_LABELS[k]}</div>
              <div className={`feature-value ${v === true ? "flag-true" : ""}`}>
                {fmtValue(k, v)}
              </div>
            </div>
          ))}
      </div>

      <div className="contrib-list">
        {Object.entries(tx.contributions).map(([k, v]) => (
          <div className="contrib-row" key={k}>
            <span className="contrib-label">{CONTRIB_LABELS[k] || k}</span>
            <span className="contrib-bar-track">
              <span
                className={`contrib-bar-fill ${v >= 0 ? "pos" : "neg"}`}
                style={{ width: `${(Math.abs(v) / maxAbs) * 100}%` }}
              />
            </span>
            <span className="contrib-value">{v > 0 ? "+" : ""}{v.toFixed(1)}</span>
          </div>
        ))}
      </div>

      {tx.explanation ? (
        <div className="explain-box">
          <span className="label">Agent explanation</span>
          {tx.explanation}
        </div>
      ) : (
        <button className="btn primary" onClick={() => onExplain(tx.id)} disabled={explaining}>
          {explaining ? "Explaining…" : "Explain this decision"}
        </button>
      )}
    </div>
  );
}
