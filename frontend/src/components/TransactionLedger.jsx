const FEATURE_LABELS = {
  device_seen_count: "Device seen",
  retry_count: "Retries (10m)",
  typing_anomaly: "Cadence anomaly",
  geo_mismatch: "Geo mismatch",
  geo_distance_km: "Distance (km)",
  time_anomaly: "Time anomaly",
  past_blocked_count: "Past blocked",
  chargeback_count: "Chargebacks",
  account_age_days: "Account age (d)",
  is_cod: "Cash on delivery",
  is_international: "International",
  amount_inr: "Amount",
  billing_city: "Billing city",
  counterparty_city: "Sign-in city",
};

function fmtValue(key, value) {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (key === "amount_inr") return `\u20b9${value.toLocaleString("en-IN")}`;
  return value;
}

export default function TransactionLedger({ transactions, selectedId, onSelect }) {
  if (!transactions.length) {
    return (
      <div className="empty-state">
        No transactions yet. Click <strong>Generate batch</strong> above to feed
        in a set of synthetic transactions.
      </div>
    );
  }

  return (
    <div>
      {transactions.map((tx) => (
        <div
          key={tx.id}
          className={`ledger-item band-${tx.band} ${tx.id === selectedId ? "selected" : ""}`}
          onClick={() => onSelect(tx.id)}
        >
          <div className="ledger-main">
            <div className="ledger-id">#{tx.id} · {tx.scenario}</div>
            <div className="ledger-amount">
              {fmtValue("amount_inr", tx.features.amount_inr)}
            </div>
            <div className="ledger-meta">
              {tx.features.billing_city}
              {tx.features.is_international ? " · intl" : ""}
              {tx.features.is_cod ? " · COD" : ""}
            </div>
          </div>
          <div className="ledger-score">{tx.score}</div>
        </div>
      ))}
    </div>
  );
}

export { FEATURE_LABELS, fmtValue };
