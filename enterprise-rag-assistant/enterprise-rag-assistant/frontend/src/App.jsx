import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";

const STATUS_COLORS = {
  ready: "#16a34a",
  failed: "#dc2626",
  empty: "#dc2626",
  unsupported: "#9ca3af",
  pending: "#f59e0b",
  downloading: "#f59e0b",
  extracting: "#f59e0b",
  chunking: "#f59e0b",
  embedding: "#f59e0b",
};

export default function App() {
  const [auth, setAuth] = useState({ connected: false });
  const [documents, setDocuments] = useState([]);
  const [deletedDocuments, setDeletedDocuments] = useState([]);
  const [historyDocuments, setHistoryDocuments] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [view, setView] = useState("active");
  const chatEndRef = useRef(null);

  const refreshAll = async () => {
    try {
      const [authStatus, docs, deletedDocs, historyDocs] = await Promise.all([
        api.authStatus(),
        api.listDocuments(),
        api.listDeletedDocuments(),
        api.listHistory(),
      ]);
      setAuth(authStatus);
      setDocuments(docs);
      setDeletedDocuments(deletedDocs);
      setHistoryDocuments(historyDocs);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    refreshAll();
    const interval = setInterval(refreshAll, 5000); // poll for live ingestion status
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const error = params.get("error");

    if (connected === "true") {
      alert("Google Drive connected successfully.");
    } else if (connected === "false" && error) {
      alert(decodeURIComponent(error.replace(/\+/g, " ")));
    }

    if (connected !== null || error) {
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await api.triggerSync();
      alert("Sync started. If your file is in the 'AI Knowledge Base' folder, it should appear shortly.");
      setTimeout(refreshAll, 1500);
    } catch (e) {
      alert("Sync failed: " + e.message);
    } finally {
      setSyncing(false);
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      await api.uploadDocument(file);
      refreshAll();
    } catch (e) {
      alert("Upload failed: " + e.message);
    }
  };

  const handleReconnect = async () => {
    window.location.href = api.reauthUrl();
  };

  const handleDeleteDocument = async (doc) => {
    if (!window.confirm(`Delete ${doc.file_name}? This removes it from search and chat.`)) {
      return;
    }
    setDeletingId(doc.id);
    try {
      await api.deleteDocument(doc.id);
      await refreshAll();
    } catch (e) {
      alert("Delete failed: " + e.message);
    } finally {
      setDeletingId(null);
    }
  };

  const handleDeleteDeletedDocument = async (doc) => {
    if (!window.confirm(`Permanently remove ${doc.file_name} from history? This cannot be undone.`)) {
      return;
    }
    setDeletingId(doc.id);
    try {
      await api.deleteDeletedDocument(doc.id);
      await refreshAll();
    } catch (e) {
      alert("Delete failed: " + e.message);
    } finally {
      setDeletingId(null);
    }
  };

  const handleDisconnect = async () => {
    try {
      await api.disconnect();
      window.location.reload();
    } catch (e) {
      alert("Disconnect failed: " + e.message);
    }
  };

  const formatDate = (value) => {
    if (!value) return "-";
    return new Date(value).toLocaleString();
  };

  const renderDocumentCard = (doc, options = {}) => (
    <div key={doc.id} style={styles.docItem}>
      <div style={styles.docHeader}>
        <span style={{ ...styles.dot, background: STATUS_COLORS[doc.status] || "#9ca3af" }} />
        <span style={styles.docName} title={doc.file_name}>{doc.file_name}</span>
        {options.showDelete && (
          <button
            style={styles.deleteBtn}
            onClick={() => handleDeleteDocument(doc)}
            disabled={deletingId === doc.id}
            title="Delete document"
          >
            {deletingId === doc.id ? "Deleting..." : "Delete"}
          </button>
        )}
        {options.showPermanentDelete && (
          <button
            style={styles.permanentDeleteBtn}
            onClick={() => handleDeleteDeletedDocument(doc)}
            disabled={deletingId === doc.id}
            title="Permanently delete document"
          >
            {deletingId === doc.id ? "Deleting..." : "Delete Forever"}
          </button>
        )}
      </div>
      <div style={styles.docMeta}>
        <div>{doc.status}{doc.status === "ready" ? ` · ${doc.chunk_count} chunks · ${doc.page_count}p` : ""}</div>
        <div>Uploaded: {formatDate(doc.uploaded_at)}</div>
        <div>Indexed: {formatDate(doc.indexed_at)}</div>
        {doc.deleted_at && <div>Deleted: {formatDate(doc.deleted_at)}</div>}
      </div>
      {doc.error_message && <div style={styles.docError}>{doc.error_message}</div>}
    </div>
  );

  const visibleDocuments = view === "deleted" ? deletedDocuments : view === "history" ? historyDocuments : documents;

  // Extract @mentions like "@report.pdf" from the message to scope search.
  const extractMentions = (text) => {
    const matches = [...text.matchAll(/@([\w.\-]+)/g)].map((m) => m[1]);
    return matches.length ? matches : null;
  };

  const [strategy, setStrategy] = useState("hybrid");
  const [topK, setTopK] = useState(6);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const userMessage = input;
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setInput("");
    setLoading(true);
    try {
      const fileFilter = extractMentions(userMessage);
      const res = await api.sendMessage({
        session_id: sessionId,
        message: userMessage,
        file_filter: fileFilter,
        top_k: Number(topK),
        strategy: strategy,
      });
      setSessionId(res.session_id);
      setMessages((prev) => [...prev, { role: "assistant", content: res.answer, citations: res.citations }]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ Error: ${e.message}`, citations: [] }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.app}>
      <aside style={styles.sidebar}>
        <h1 style={styles.title}>📚 Knowledge Base</h1>

        {!auth.connected ? (
          <a href={api.loginUrl()} style={styles.connectBtn}>Connect Google Drive</a>
        ) : (
          <div style={styles.connected}>
            <span>Connected: {auth.email}</span>
            {auth.drive_folder_id && (
              <span style={styles.subText}>Drive folder: {auth.drive_folder_id}</span>
            )}
            <div style={styles.connectedButtons}>
              <button style={styles.syncBtn} onClick={handleSync} disabled={syncing}>
                {syncing ? "Syncing..." : "Sync now"}
              </button>
              <button style={styles.disconnectBtn} onClick={handleReconnect}>
                Reconnect
              </button>
            </div>
          </div>
        )}

        <div style={styles.uploadRow}>
          <label style={styles.uploadLabel}>
            + Upload file (test without Drive)
            <input type="file" onChange={handleUpload} style={{ display: "none" }} accept=".pdf,.docx,.txt,.md" />
          </label>
        </div>

        <div style={styles.tabBar}>
          <button style={{ ...styles.tabBtn, ...(view === "active" ? styles.tabBtnActive : {}) }} onClick={() => setView("active")}>
            Active ({documents.length})
          </button>
          <button style={{ ...styles.tabBtn, ...(view === "deleted" ? styles.tabBtnActive : {}) }} onClick={() => setView("deleted")}>
            Deleted ({deletedDocuments.length})
          </button>
          <button style={{ ...styles.tabBtn, ...(view === "history" ? styles.tabBtnActive : {}) }} onClick={() => setView("history")}>
            History ({historyDocuments.length})
          </button>
        </div>

        <div style={styles.docList}>
          {visibleDocuments.length === 0 && <p style={styles.empty}>No documents in this view yet.</p>}
          {visibleDocuments.map((doc) =>
            renderDocumentCard(doc, {
              showDelete: view === "active",
              showPermanentDelete: view === "deleted",
            })
          )}
        </div>
      </aside>

      <main style={styles.main}>
        <div style={styles.chatWindow}>
          {messages.length === 0 && (
            <div style={styles.hint}>
              Ask a question about your documents. Use <code>@filename</code> to search a specific file.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} style={m.role === "user" ? styles.userBubble : styles.botBubble}>
              <div>{m.content}</div>
              {m.citations && m.citations.length > 0 && (
                <div style={styles.citations}>
                  {m.citations.map((c, j) => (
                    <div key={j} style={styles.citationChip} title={c.snippet}>
                      📄 {c.file_name} · p.{c.page_number ?? "-"} · {(c.score * 100).toFixed(0)}%
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {loading && <div style={styles.botBubble}>Thinking…</div>}
          <div ref={chatEndRef} />
        </div>

        <div style={styles.toolbar}>
          <div style={styles.controlGroup}>
            <span style={styles.controlLabel}>RAG Strategy:</span>
            <select style={styles.select} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              <option value="hybrid">⚡ Hybrid (Dense Vector + BM25 Sparse)</option>
              <option value="vector">🔍 Dense Vector Similarity Only</option>
              <option value="bm25">🔤 BM25 Exact Keyword Only</option>
            </select>
          </div>

          <div style={styles.controlGroup}>
            <span style={styles.controlLabel}>Retrieval Depth:</span>
            <select style={styles.select} value={topK} onChange={(e) => setTopK(e.target.value)}>
              <option value="4">Top 4 Chunks</option>
              <option value="6">Top 6 Chunks (Default)</option>
              <option value="10">Top 10 Chunks (Deep)</option>
              <option value="15">Top 15 Chunks (500+ Page Docs)</option>
            </select>
          </div>
        </div>

        <div style={styles.inputRow}>
          <input
            style={styles.input}
            value={input}
            placeholder="Ask a question, or @filename to scope search…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
          />
          <button style={styles.sendBtn} onClick={handleSend} disabled={loading}>Send</button>
        </div>
      </main>
    </div>
  );
}

const styles = {
  app: { display: "flex", height: "100vh", fontFamily: "Inter, system-ui, sans-serif", background: "#0f172a" },
  sidebar: { width: 300, background: "#111827", color: "#e5e7eb", padding: 16, overflowY: "auto", borderRight: "1px solid #1f2937" },
  title: { fontSize: 18, marginBottom: 16 },
  connectBtn: { display: "block", textAlign: "center", background: "#2563eb", color: "white", padding: "8px 12px", borderRadius: 8, textDecoration: "none", marginBottom: 16 },
  connected: { display: "flex", flexDirection: "column", gap: 8, marginBottom: 16, fontSize: 13 },
  syncBtn: { background: "#374151", color: "white", border: "none", padding: "6px 10px", borderRadius: 6, cursor: "pointer" },
  subText: { fontSize: 12, color: "#cbd5e1" },
  uploadRow: { marginBottom: 16 },
  uploadLabel: { fontSize: 13, color: "#93c5fd", cursor: "pointer" },
  tabBar: { display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" },
  tabBtn: { background: "#111827", color: "#cbd5e1", border: "1px solid #374151", padding: "6px 10px", borderRadius: 999, cursor: "pointer", fontSize: 12 },
  tabBtnActive: { background: "#2563eb", color: "white", borderColor: "#2563eb" },
  docList: { display: "flex", flexDirection: "column", gap: 10 },
  empty: { fontSize: 13, color: "#6b7280" },
  docItem: { background: "#1f2937", borderRadius: 8, padding: 10 },
  docHeader: { display: "flex", alignItems: "center", gap: 8 },
  dot: { width: 8, height: 8, borderRadius: "50%", flexShrink: 0 },
  docName: { fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", flex: 1 },
  deleteBtn: { background: "#374151", color: "#e5e7eb", border: "1px solid #4b5563", padding: "4px 8px", borderRadius: 6, cursor: "pointer", fontSize: 11, flexShrink: 0 },
  permanentDeleteBtn: { background: "#7f1d1d", color: "#fef2f2", border: "1px solid #991b1b", padding: "4px 8px", borderRadius: 6, cursor: "pointer", fontSize: 11, flexShrink: 0 },
  docMeta: { fontSize: 11, color: "#9ca3af", marginTop: 4, display: "flex", flexDirection: "column", gap: 2 },
  docError: { fontSize: 11, color: "#f87171", marginTop: 4 },
  main: { flex: 1, display: "flex", flexDirection: "column", background: "#0b1220" },
  chatWindow: { flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 12 },
  hint: { color: "#6b7280", fontSize: 14, margin: "auto" },
  userBubble: { alignSelf: "flex-end", background: "#2563eb", color: "white", padding: "10px 14px", borderRadius: 12, maxWidth: "70%" },
  botBubble: { alignSelf: "flex-start", background: "#1f2937", color: "#e5e7eb", padding: "10px 14px", borderRadius: 12, maxWidth: "75%" },
  citations: { display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 },
  citationChip: { fontSize: 11, background: "#111827", padding: "4px 8px", borderRadius: 6, color: "#93c5fd", cursor: "help" },
  toolbar: { display: "flex", gap: 16, padding: "8px 16px", background: "#0f172a", borderTop: "1px solid #1f2937", alignItems: "center" },
  controlGroup: { display: "flex", alignItems: "center", gap: 6 },
  controlLabel: { fontSize: 12, color: "#94a3b8", fontWeight: 500 },
  select: { background: "#1e293b", color: "#f8fafc", border: "1px solid #334155", borderRadius: 6, padding: "4px 8px", fontSize: 12, outline: "none" },
  inputRow: { display: "flex", gap: 8, padding: 16, borderTop: "1px solid #1f2937" },
  input: { flex: 1, padding: "12px 14px", borderRadius: 10, border: "1px solid #374151", background: "#111827", color: "white", fontSize: 14 },
  sendBtn: { padding: "0 20px", borderRadius: 10, border: "none", background: "#2563eb", color: "white", cursor: "pointer", fontSize: 14 },
};
