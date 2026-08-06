const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function handle(res) {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  authStatus: () => fetch(`${BASE_URL}/api/auth/status`).then(handle),
  loginUrl: () => `${BASE_URL}/api/auth/google/login`,
  reauthUrl: () => `${BASE_URL}/api/auth/google/reauth`,
  disconnect: () => fetch(`${BASE_URL}/api/auth/google/disconnect`, { method: "POST" }).then(handle),

  listDocuments: () => fetch(`${BASE_URL}/api/drive/documents`).then(handle),
  listDeletedDocuments: () => fetch(`${BASE_URL}/api/drive/deleted-documents`).then(handle),
  listHistory: () => fetch(`${BASE_URL}/api/drive/history`).then(handle),
  triggerSync: () => fetch(`${BASE_URL}/api/drive/sync`, { method: "POST" }).then(handle),
  deleteDocument: (id) => fetch(`${BASE_URL}/api/drive/documents/${id}`, { method: "DELETE" }).then(handle),
  deleteDeletedDocument: (id) => fetch(`${BASE_URL}/api/drive/deleted-documents/${id}`, { method: "DELETE" }).then(handle),

  uploadDocument: (file) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE_URL}/api/documents/upload`, { method: "POST", body: form }).then(handle);
  },

  sendMessage: (payload) =>
    fetch(`${BASE_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(handle),
};

export { BASE_URL };
