import { useState } from "react";
import UploadZone from "./components/UploadZone";
import SummaryPanel from "./components/SummaryPanel";
import FactsPanel from "./components/FactsPanel";
import ChatWindow from "./components/ChatWindow";
 
const LogoIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="16" y1="13" x2="8" y2="13"/>
    <line x1="16" y1="17" x2="8" y2="17"/>
  </svg>
);
 
const PlusIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19"/>
    <line x1="5" y1="12" x2="19" y2="12"/>
  </svg>
);
 
const s = {
  app: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    background: "var(--bg)",
  },
  topbar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "12px 20px",
    borderBottom: "1px solid var(--border)",
    background: "var(--bg-card)",
    flexShrink: 0,
  },
  brand: {
    display: "flex",
    alignItems: "center",
    gap: "9px",
  },
  logoChip: {
    width: "28px",
    height: "28px",
    borderRadius: "7px",
    background: "var(--accent)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  brandText: {
    fontSize: "15px",
    fontWeight: 600,
    color: "var(--text-primary)",
    letterSpacing: "-0.2px",
  },
  brandAccent: { color: "var(--accent)" },
  newDocBtn: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    fontSize: "12px",
    color: "var(--text-secondary)",
    background: "var(--bg-hover)",
    border: "1px solid var(--border-mid)",
    borderRadius: "var(--radius-sm)",
    padding: "6px 12px",
    cursor: "pointer",
    fontFamily: "inherit",
  },
  body: {
    display: "grid",
    gridTemplateColumns: "270px 1fr",
    flex: 1,
    overflow: "hidden",
    height: "calc(100vh - 53px)",
  },
  sidebar: {
    borderRight: "1px solid var(--border)",
    display: "flex",
    flexDirection: "column",
    overflowY: "auto",
    background: "var(--bg-card)",
  },
  indexPill: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    margin: "10px 12px",
    padding: "6px 10px",
    background: "var(--bg)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
  },
  indexDot: {
    width: "6px",
    height: "6px",
    borderRadius: "50%",
    background: "var(--success-text)",
    flexShrink: 0,
  },
  indexText: {
    fontSize: "11px",
    color: "var(--text-muted)",
  },
};
 
export default function App() {
  const [docData, setDocData] = useState(null);
 
  if (!docData) {
    return <UploadZone onUploadSuccess={setDocData} />;
  }
 
  return (
    <div style={s.app}>
      <div style={s.topbar}>
        <div style={s.brand}>
          <div style={s.logoChip}><LogoIcon /></div>
          <span style={s.brandText}>
            Docu<span style={s.brandAccent}>Mind</span>
          </span>
        </div>
        <button style={s.newDocBtn} onClick={() => setDocData(null)}>
          <PlusIcon /> New document
        </button>
      </div>
 
      <div style={s.body}>
        <div style={s.sidebar}>
          <SummaryPanel summary={docData.summary} filename={docData.filename} />
 
          <div style={s.indexPill}>
            <div style={s.indexDot} />
            <span style={s.indexText}>{docData.chunks} chunks indexed · pgvector</span>
          </div>
 
          <FactsPanel facts={docData.facts} />
        </div>
 
        <ChatWindow docId={docData.doc_id} />
      </div>
    </div>
  );
}
 
