import { useState, useRef, useEffect } from "react";

export default function ChatPanel({ messages, onSend, onConfirm, sending }) {
  const [text, setText] = useState("");
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  function submit(e) {
    e.preventDefault();
    const t = text.trim();
    if (!t || sending) return;
    onSend(t);
    setText("");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="chat-hint">
        Try: "increase the geo mismatch weight for international cash on
        delivery orders" (reliably applies) or "this customer is trusted,
        stop flagging them"
      </div>
      <div className="chat-log" ref={logRef} style={{ flex: 1, overflowY: "auto" }}>
        {messages.length === 0 && (
          <div className="spinner-text">
            No messages yet — steer the policy by typing an instruction below.
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "merchant" ? (
            <div className="chat-msg merchant" key={i}>{m.text}</div>
          ) : (
            <div className={`chat-msg agent ${m.status || ""}`} key={i}>
              {m.text}
              {m.delta && (
                <div className="chat-delta">
                  {m.delta.signal} · {m.delta.scope} · {m.delta.old_value} → {m.delta.new_value}
                </div>
              )}
              {m.status === "needs_confirmation" && !m.resolved && (
                <div className="chat-confirm-actions">
                  <button className="btn" onClick={() => onConfirm(m.pendingId, true, i)}>
                    Apply anyway
                  </button>
                  <button className="btn" onClick={() => onConfirm(m.pendingId, false, i)}>
                    Discard
                  </button>
                </div>
              )}
              {m.resolved && (
                <div className="chat-delta">{m.resolved}</div>
              )}
            </div>
          )
        )}
        {sending && <div className="spinner-text">Agent is thinking…</div>}
      </div>
      <form className="chat-input-row" onSubmit={submit}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type an instruction to steer the policy…"
          disabled={sending}
        />
        <button className="btn primary" type="submit" disabled={sending}>
          Send
        </button>
      </form>
    </div>
  );
}
