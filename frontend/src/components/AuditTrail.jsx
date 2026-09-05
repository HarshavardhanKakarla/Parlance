const TYPE_LABELS = {
  batch_generated: "Batch generated",
  probe_transaction: "Probe transaction scored",
  decision_explained: "Decision explained",
  policy_changed: "Policy changed",
  manual_review_flagged: "Flagged for manual review",
  manual_review_rejected: "Manual review discarded",
  rescored_all: "Re-scored all transactions",
  rigid_preset_applied: "Rigid demo policy applied",
  policy_reset: "Policy reset to default",
};

function summarize(entry) {
  const p = entry.payload;
  switch (entry.type) {
    case "batch_generated":
      return `${p.count} transactions generated`;
    case "probe_transaction":
      return `#${p.transaction_id} scored ${p.score} (${p.band})`;
    case "decision_explained":
      return `#${p.transaction_id}: ${p.explanation}`;
    case "policy_changed":
      return `${p.signal} (${p.scope}) ${p.old_value} \u2192 ${p.new_value}${p.manual_review ? " · via manual review" : ""}`;
    case "manual_review_flagged":
      return `"${p.instruction}" — ${p.parsed.human_summary}`;
    case "manual_review_rejected":
      return `Pending change #${p.pending_change_id} discarded`;
    case "rescored_all":
      return `${p.changed} of ${p.total} transactions moved bands`;
    case "rigid_preset_applied":
    case "policy_reset":
      return p.note;
    default:
      return JSON.stringify(p);
  }
}

export default function AuditTrail({ entries }) {
  if (!entries.length) {
    return <div className="empty-state">No activity logged yet.</div>;
  }
  return (
    <div className="audit-list">
      {entries.map((e) => (
        <div className="audit-row" key={e.id}>
          <div className="audit-time">{new Date(e.timestamp).toLocaleTimeString()}</div>
          <div className="audit-type">{TYPE_LABELS[e.type] || e.type}</div>
          <div className="audit-detail">{summarize(e)}</div>
        </div>
      ))}
    </div>
  );
}
