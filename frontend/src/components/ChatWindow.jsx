import { useState, useRef, useEffect } from "react";
import axios from "axios";

const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";

const SendIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="19" x2="12" y2="5"/>
    <polyline points="5 12 12 5 19 12"/>
  </svg>
);

export default function ChatWindow({ docId }) {
  const [messages, setMessages] = useState([
    { role: "assistant", text: "Your document is indexed. Ask me anything about it." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef();
  const inputRef = useRef();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const question = input.trim();
    if (!question || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setLoading(true);
    try {
      const res = await axios.post(`${BACKEND}/query`, { question, doc_id: docId });
      setMessages((prev) => [...prev, { role: "assistant", text: res.data.answer }]);
    } catch (e) {
      const status = e.response?.status;
      const detail = e.response?.data?.detail;
      let msg;
      if (status === 429) msg = detail || "Gemini quota reached. Please wait a minute and try again.";
      else msg = detail || "Something went wrong. Please try again.";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: msg },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const s = {
    panel: {
      display: "flex",
      flexDirection: "column",
      height: "100%",
      background: "var(--bg)",
    },
    header: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      padding: "12px 16px",
      borderBottom: "1px solid var(--border)",
      background: "var(--bg-card)",
      flexShrink: 0,
    },
    headerDot: {
      width: "8px",
      height: "8px",
      borderRadius: "50%",
      background: "var(--success-text)",
    },
    headerTitle: {
      fontSize: "13px",
      fontWeight: 500,
      color: "var(--text-primary)",
    },
    headerSub: {
      fontSize: "11px",
      color: "var(--text-muted)",
      marginLeft: "auto",
    },
    messages: {
      flex: 1,
      overflowY: "auto",
      padding: "16px",
      display: "flex",
      flexDirection: "column",
      gap: "12px",
    },
    msgRow: (role) => ({
      display: "flex",
      gap: "8px",
      alignItems: "flex-end",
      flexDirection: role === "user" ? "row-reverse" : "row",
    }),
    avatar: (role) => ({
      width: "24px",
      height: "24px",
      borderRadius: "50%",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "10px",
      fontWeight: 600,
      flexShrink: 0,
      background: role === "user" ? "var(--accent)" : "var(--accent-light)",
      color: role === "user" ? "#fff" : "var(--accent)",
      border: role === "assistant" ? "1px solid var(--accent-border)" : "none",
    }),
    bubble: (role) => ({
      maxWidth: "76%",
      padding: "9px 13px",
      fontSize: "13px",
      lineHeight: 1.65,
      borderRadius: role === "user"
        ? "12px 3px 12px 12px"
        : "3px 12px 12px 12px",
      background: role === "user" ? "var(--accent)" : "var(--bg-card)",
      color: role === "user" ? "#fff" : "var(--text-primary)",
      border: role === "assistant" ? "1px solid var(--border)" : "none",
    }),
    typingBubble: {
      padding: "10px 14px",
      borderRadius: "3px 12px 12px 12px",
      background: "var(--bg-card)",
      border: "1px solid var(--border)",
      display: "flex",
      gap: "5px",
      alignItems: "center",
    },
    typingDot: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "var(--text-muted)",
    },
    inputArea: {
      padding: "12px 16px",
      borderTop: "1px solid var(--border)",
      display: "flex",
      gap: "8px",
      alignItems: "flex-end",
      background: "var(--bg-card)",
      flexShrink: 0,
    },
    input: {
      flex: 1,
      background: "var(--bg)",
      border: "1px solid var(--border-mid)",
      borderRadius: "var(--radius-sm)",
      padding: "8px 12px",
      fontSize: "13px",
      color: "var(--text-primary)",
      fontFamily: "inherit",
      outline: "none",
      resize: "none",
      lineHeight: 1.5,
    },
    sendBtn: {
      width: "34px",
      height: "34px",
      borderRadius: "var(--radius-sm)",
      background: loading || !input.trim() ? "rgba(124,58,237,0.3)" : "var(--accent)",
      border: "none",
      cursor: loading || !input.trim() ? "default" : "pointer",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0,
      color: "#fff",
      transition: "background 0.15s",
    },
  };

  return (
    <div style={s.panel}>
      <div style={s.header}>
        <div style={s.headerDot} />
        <span style={s.headerTitle}>Chat with document</span>
        <span style={s.headerSub}>top-3 chunks · cosine similarity</span>
      </div>

      <div style={s.messages}>
        {messages.map((msg, i) => (
          <div key={i} style={s.msgRow(msg.role)}>
            <div style={s.avatar(msg.role)}>
              {msg.role === "user" ? "A" : "D"}
            </div>
            <div style={s.bubble(msg.role)}>{msg.text}</div>
          </div>
        ))}

        {loading && (
          <div style={s.msgRow("assistant")}>
            <div style={s.avatar("assistant")}>D</div>
            <div style={s.typingBubble}>
              <div style={s.typingDot} className="typing-dot" />
              <div style={s.typingDot} className="typing-dot" />
              <div style={s.typingDot} className="typing-dot" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={s.inputArea}>
        <textarea
          ref={inputRef}
          style={s.input}
          rows={1}
          placeholder="Ask something about your document…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button style={s.sendBtn} onClick={send} disabled={loading || !input.trim()} aria-label="Send">
          <SendIcon />
        </button>
      </div>
    </div>
  );
}
