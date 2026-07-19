import { useState, useRef } from "react";
import axios from "axios";

const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";

export default function UploadZone({ onUploadSuccess }) {
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef();

  const handleFile = async (file) => {
    if (!file || !file.name.endsWith(".pdf")) {
      setError("Only PDF files are accepted.");
      return;
    }
    setError("");
    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await axios.post(`${BACKEND}/ingest`, formData);
      onUploadSuccess(res.data);
    } catch (e) {
      if (e.response) {
        const { status, data } = e.response;
        if (status === 429) setError(data?.detail || "Gemini quota exhausted. Document is indexed — try again after quota resets.");
        else if (status === 413) setError("File too large. Maximum size is 10 MB.");
        else if (status === 400) setError(data?.detail || "Invalid file. Only PDF files are accepted.");
        else setError(data?.detail || "Upload failed. Please try again.");
      } else if (e.request) {
        setError("Cannot reach the server. Check that the backend is running.");
      } else {
        setError("Unexpected error. Please try again.");
      }
    } finally {
      setLoading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const s = {
    page: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      minHeight: "100vh",
      padding: "2rem",
      background: "var(--bg)",
    },
    wordmark: {
      fontSize: "32px",
      fontWeight: 600,
      color: "var(--text-primary)",
      letterSpacing: "-0.5px",
      marginBottom: "6px",
    },
    accent: { color: "var(--accent)" },
    tagline: {
      fontSize: "14px",
      color: "var(--text-secondary)",
      marginBottom: "2.5rem",
    },
    dropZone: {
      width: "100%",
      maxWidth: "460px",
      border: `1.5px dashed ${dragging ? "var(--accent)" : "var(--border-mid)"}`,
      borderRadius: "var(--radius-lg)",
      padding: "3rem 2rem",
      textAlign: "center",
      cursor: "pointer",
      background: dragging ? "var(--accent-light)" : "var(--bg-card)",
      transition: "border-color 0.15s, background 0.15s",
    },
    iconWrap: {
      width: "48px",
      height: "48px",
      borderRadius: "var(--radius)",
      background: "var(--accent-light)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      margin: "0 auto 16px",
      border: "1px solid var(--accent-border)",
    },
    dropTitle: {
      fontSize: "15px",
      fontWeight: 500,
      color: "var(--text-primary)",
      marginBottom: "4px",
    },
    dropSub: {
      fontSize: "13px",
      color: "var(--text-secondary)",
      marginBottom: "20px",
    },
    btn: {
      display: "inline-flex",
      alignItems: "center",
      gap: "7px",
      background: "var(--accent)",
      color: "#fff",
      fontSize: "13px",
      fontWeight: 500,
      padding: "8px 20px",
      borderRadius: "var(--radius-sm)",
      border: "none",
      cursor: "pointer",
      fontFamily: "inherit",
    },
    limitTag: {
      display: "inline-block",
      marginTop: "14px",
      fontSize: "11px",
      color: "var(--text-muted)",
      background: "rgba(255,255,255,0.04)",
      padding: "3px 10px",
      borderRadius: "20px",
    },
    spinner: {
      width: "36px",
      height: "36px",
      border: "3px solid rgba(124,58,237,0.2)",
      borderTop: "3px solid var(--accent)",
      borderRadius: "50%",
      margin: "0 auto 12px",
    },
    spinnerText: { fontSize: "13px", color: "var(--text-secondary)" },
    errorMsg: {
      marginTop: "16px",
      fontSize: "13px",
      color: "var(--danger-text)",
      maxWidth: "460px",
      textAlign: "center",
      background: "var(--danger-bg)",
      padding: "10px 14px",
      borderRadius: "var(--radius-sm)",
    },
  };

  return (
    <div style={s.page}>
      <p style={s.wordmark}>
        Docu<span style={s.accent}>Mind</span>
      </p>
      <p style={s.tagline}>Upload a PDF. Get an instant summary and chat with your document.</p>

      <div
        style={s.dropZone}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => !loading && inputRef.current.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files[0])}
        />

        {loading ? (
          <>
            <div style={s.spinner} className="spin" />
            <p style={s.spinnerText}>Processing your document…</p>
          </>
        ) : (
          <>
            <div style={s.iconWrap}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="17 8 12 3 7 8"/>
                <line x1="12" y1="3" x2="12" y2="15"/>
              </svg>
            </div>
            <p style={s.dropTitle}>Drop your PDF here</p>
            <p style={s.dropSub}>or click to browse files</p>
            <button
              style={s.btn}
              onClick={(e) => { e.stopPropagation(); inputRef.current.click(); }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="17 8 12 3 7 8"/>
                <line x1="12" y1="3" x2="12" y2="15"/>
              </svg>
              Choose file
            </button>
            <span style={s.limitTag}>PDF only · max 10 MB</span>
          </>
        )}
      </div>

      {error && <p style={s.errorMsg}>{error}</p>}
    </div>
  );
}
