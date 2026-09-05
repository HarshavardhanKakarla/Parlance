import { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";
import TransactionLedger from "./components/TransactionLedger.jsx";
import TransactionDetail from "./components/TransactionDetail.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import AuditTrail from "./components/AuditTrail.jsx";

export default function App() {
  const [transactions, setTransactions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [explaining, setExplaining] = useState(false);
  const [rightTab, setRightTab] = useState("chat");
  const [chatMessages, setChatMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const [audit, setAudit] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState(null);

  const refreshTransactions = useCallback(async () => {
    setTransactions(await api.listTransactions());
  }, []);

  const refreshAudit = useCallback(async () => {
    setAudit(await api.listAudit());
  }, []);

  useEffect(() => {
    refreshTransactions();
    refreshAudit();
    api.health().then((h) => setLlmConfigured(h.llm_configured)).catch(() => {});
  }, [refreshTransactions, refreshAudit]);

  async function handleGenerate() {
    setGenerating(true);
    try {
      await api.generateBatch(60);
      await refreshTransactions();
      await refreshAudit();
    } finally {
      setGenerating(false);
    }
  }

  async function handleRigidPreset() {
    setGenerating(true);
    try {
      await api.applyRigidPreset();
      await api.rescoreAll();
      await refreshTransactions();
      await refreshAudit();
    } finally {
      setGenerating(false);
    }
  }

  async function handleResetPolicy() {
    setGenerating(true);
    try {
      await api.resetPolicy();
      await api.rescoreAll();
      await refreshTransactions();
      await refreshAudit();
    } finally {
      setGenerating(false);
    }
  }

  async function handleProbe() {
    setGenerating(true);
    try {
      const tx = await api.runProbe();
      await refreshTransactions();
      await refreshAudit();
      setSelectedId(tx.id);
    } finally {
      setGenerating(false);
    }
  }

  async function handleSelect(id) {
    setSelectedId(id);
  }

  async function handleExplain(id) {
    setExplaining(true);
    try {
      await api.explain(id);
      await refreshTransactions();
    } finally {
      setExplaining(false);
    }
  }

  async function handleSendChat(message) {
    setChatMessages((m) => [...m, { role: "merchant", text: message }]);
    setSending(true);
    try {
      const res = await api.sendChat(message);
      if (res.status === "applied") {
        setChatMessages((m) => [
          ...m,
          {
            role: "agent",
            status: "applied",
            text: res.summary,
            delta: { signal: res.signal, scope: res.scope, old_value: res.old_value, new_value: res.new_value },
          },
        ]);
        await api.rescoreAll();
        await refreshTransactions();
      } else {
        setChatMessages((m) => [
          ...m,
          {
            role: "agent",
            status: "needs_confirmation",
            text: res.summary,
            pendingId: res.pending_change_id,
          },
        ]);
      }
      await refreshAudit();
    } catch (e) {
      setChatMessages((m) => [...m, { role: "agent", text: `Error: ${e.message}` }]);
    } finally {
      setSending(false);
    }
  }

  async function handleConfirm(pendingId, approve, msgIndex) {
    try {
      const res = await api.confirmPending(pendingId, approve);
      setChatMessages((m) =>
        m.map((msg, i) =>
          i === msgIndex
            ? {
                ...msg,
                resolved: approve
                  ? `Applied: ${res.signal} (${res.scope}) ${res.old_value} \u2192 ${res.new_value}`
                  : "Discarded — no policy change made.",
              }
            : msg
        )
      );
      if (approve) {
        await api.rescoreAll();
        await refreshTransactions();
      }
      await refreshAudit();
    } catch (e) {
      setChatMessages((m) =>
        m.map((msg, i) => (i === msgIndex ? { ...msg, resolved: `Error: ${e.message}` } : msg))
      );
    }
  }

  const counts = transactions.reduce(
    (acc, t) => {
      acc[t.band] = (acc[t.band] || 0) + 1;
      return acc;
    },
    { green: 0, yellow: 0, red: 0 }
  );

  const selectedTx = transactions.find((t) => t.id === selectedId) || null;

  return (
    <div className="app">
      <div className="topbar">
        <div>
          <div className="brand">Parlance</div>
          <span className="brand-sub">
            Fraud scoring you can talk to{llmConfigured === false ? " · offline demo mode (no GEMINI_API_KEY)" : ""}
          </span>
        </div>
        <div className="topbar-counts">
          <span className="count-pill"><span className="dot green" />{counts.green}</span>
          <span className="count-pill"><span className="dot yellow" />{counts.yellow}</span>
          <span className="count-pill"><span className="dot red" />{counts.red}</span>
        </div>
        <div className="topbar-actions">
          <button className="btn" onClick={handleRigidPreset} disabled={generating} title="Failure story: intentionally too-strict policy">
            Simulate rigid policy
          </button>
          <button className="btn" onClick={handleResetPolicy} disabled={generating} title="Correct the rigid policy back to default">
            Reset policy
          </button>
          <button className="btn" onClick={handleProbe} disabled={generating}>
            Run cod_intl probe
          </button>
          <button className="btn primary" onClick={handleGenerate} disabled={generating}>
            {generating ? "Working…" : "Generate batch"}
          </button>
        </div>
      </div>

      <div className="workbench">
        <div className="pane">
          <div className="pane-header">Ledger</div>
          <div className="pane-body">
            <TransactionLedger
              transactions={transactions}
              selectedId={selectedId}
              onSelect={handleSelect}
            />
          </div>
        </div>

        <div className="pane">
          <div className="pane-header">Transaction detail</div>
          <div className="pane-body">
            <TransactionDetail tx={selectedTx} onExplain={handleExplain} explaining={explaining} />
          </div>
        </div>

        <div className="pane">
          <div className="pane-header">
            <span>Agent</span>
            <div className="tabs">
              <span className={`tab ${rightTab === "chat" ? "active" : ""}`} onClick={() => setRightTab("chat")}>
                Chat
              </span>
              <span className={`tab ${rightTab === "audit" ? "active" : ""}`} onClick={() => setRightTab("audit")}>
                Audit trail
              </span>
            </div>
          </div>
          <div className="pane-body" style={{ display: "flex" }}>
            {rightTab === "chat" ? (
              <ChatPanel
                messages={chatMessages}
                onSend={handleSendChat}
                onConfirm={handleConfirm}
                sending={sending}
              />
            ) : (
              <AuditTrail entries={audit} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
