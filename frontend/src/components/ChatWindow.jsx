import { useState, useRef, useEffect } from "react";
import { api } from "../api";

export default function ChatWindow({ docId }) {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef();

  // Scroll to the newest message whenever the conversation grows.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const trimmed = question.trim();
    if (!trimmed || loading) return;

    setError("");
    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setQuestion("");
    setLoading(true);

    try {
      const res = await api.post("/query", { question: trimmed, doc_id: docId });
      setMessages((prev) => [...prev, { role: "assistant", text: res.data.answer }]);
    } catch (e) {
      let msg;
      if (e.response) {
        const { status, data } = e.response;
        if (status === 401) msg = "Your session expired. Please log in again.";
        else if (status === 404) msg = "This document could not be found.";
        else if (status === 429) msg = data?.detail || "Quota reached. Please wait a moment and try again.";
        else msg = data?.detail || "Something went wrong answering that. Please try again.";
      } else if (e.request) {
        msg = "Cannot reach the server. It may be starting up — please wait a few seconds and try again.";
      } else {
        msg = "Unexpected error. Please try again.";
      }
      setError(msg);
      // Also surface the failure inline in the conversation, so it's
      // clear which question didn't get answered rather than just a
      // banner disconnected from the message list.
      setMessages((prev) => [...prev, { role: "assistant", text: msg, isError: true }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const s = {
    wrap: {
      display: "flex",
      flexDirection: "column",
      height: "100%",
      background: "var(--bg)",
    },
    messages: {
      flex: 1,
      overflowY: "auto",
      padding: "24px",
      display: "flex",
      flexDirection: "column",
      gap: "14px",
    },
    empty: {
      flex: 1,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "var(--text-muted)",
      fontSize: "13px",
      textAlign: "center",
    },
    row: (isUser) => ({
      display: "flex",
      justifyContent: isUser ? "flex-end" : "flex-start",
    }),
    bubble: (isUser, isError) => ({
      maxWidth: "70%",
      padding: "10px 14px",
      borderRadius: "var(--radius)",
      fontSize: "13.5px",
      lineHeight: 1.5,
      whiteSpace: "pre-wrap",
      background: isError ? "var(--danger-bg)" : isUser ? "var(--accent)" : "var(--bg-card)",
      color: isError ? "var(--danger-text)" : isUser ? "#fff" : "var(--text-primary)",
      border: isError ? "1px solid var(--danger-text)" : isUser ? "none" : "1px solid var(--border)",
    }),
    typingRow: { display: "flex", justifyContent: "flex-start" },
    typingBubble: {
      padding: "10px 14px",
      borderRadius: "var(--radius)",
      background: "var(--bg-card)",
      border: "1px solid var(--border)",
      display: "flex",
      gap: "4px",
    },
    dot: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "var(--text-muted)",
    },
    inputBar: {
      display: "flex",
      alignItems: "flex-end",
      gap: "10px",
      padding: "14px 20px",
      borderTop: "1px solid var(--border)",
      background: "var(--bg-card)",
    },
    textarea: {
      flex: 1,
      resize: "none",
      minHeight: "22px",
      maxHeight: "120px",
      padding: "9px 12px",
      background: "var(--bg)",
      border: "1px solid var(--border-mid)",
      borderRadius: "var(--radius-sm)",
      color: "var(--text-primary)",
      fontSize: "13.5px",
      fontFamily: "inherit",
      outline: "none",
    },
    sendBtn: {
      background: "var(--accent)",
      color: "#fff",
      border: "none",
      borderRadius: "var(--radius-sm)",
      padding: "9px 18px",
      fontSize: "13px",
      fontWeight: 500,
      cursor: "pointer",
      fontFamily: "inherit",
      opacity: loading || !question.trim() ? 0.5 : 1,
    },
    errorBanner: {
      margin: "0 20px 10px",
      fontSize: "12px",
      color: "var(--danger-text)",
      background: "var(--danger-bg)",
      padding: "8px 12px",
      borderRadius: "var(--radius-sm)",
    },
  };

  return (
    <div style={s.wrap}>
      <div style={s.messages}>
        {messages.length === 0 ? (
          <div style={s.empty}>
            Ask a question about this document to get started.
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} style={s.row(m.role === "user")}>
              <div style={s.bubble(m.role === "user", m.isError)}>{m.text}</div>
            </div>
          ))
        )}

        {loading && (
          <div style={s.typingRow}>
            <div style={s.typingBubble}>
              <span style={s.dot} className="pulse-1" />
              <span style={s.dot} className="pulse-2" />
              <span style={s.dot} className="pulse-3" />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {error && <div style={s.errorBanner}>{error}</div>}

      <div style={s.inputBar}>
        <textarea
          style={s.textarea}
          placeholder="Ask a question about this document…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={loading}
        />
        <button style={s.sendBtn} onClick={handleSend} disabled={loading || !question.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
