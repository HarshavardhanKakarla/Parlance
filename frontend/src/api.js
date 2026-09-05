const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${path}: ${body}`);
  }
  return res.json();
}

export const api = {
  listTransactions: () => request("/api/transactions"),
  generateBatch: (count) =>
    request("/api/transactions/generate", {
      method: "POST",
      body: JSON.stringify({ count }),
    }),
  runProbe: () => request("/api/transactions/probe", { method: "POST" }),
  explain: (id) => request(`/api/transactions/${id}/explain`, { method: "POST" }),
  rescoreAll: () => request("/api/transactions/rescore_all", { method: "POST" }),
  getPolicy: () => request("/api/policy"),
  applyRigidPreset: () => request("/api/policy/preset/rigid", { method: "POST" }),
  resetPolicy: () => request("/api/policy/preset/reset", { method: "POST" }),
  sendChat: (message) =>
    request("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
  confirmPending: (id, approve) =>
    request(`/api/chat/confirm/${id}`, {
      method: "POST",
      body: JSON.stringify({ approve }),
    }),
  listAudit: () => request("/api/audit"),
  health: () => request("/api/health"),
};
