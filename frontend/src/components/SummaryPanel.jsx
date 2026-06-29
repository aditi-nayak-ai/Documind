const isQuotaMessage = (text) =>
  text?.toLowerCase().includes("quota");
 
export default function SummaryPanel({ summary, filename }) {
  const quota = isQuotaMessage(summary);
 
  const s = {
    section: {
      padding: "14px 16px",
      borderBottom: "1px solid var(--border)",
    },
    label: {
      fontSize: "10px",
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.07em",
      marginBottom: "8px",
    },
    fileRow: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      padding: "12px 16px",
      borderBottom: "1px solid var(--border)",
    },
    fileChip: {
      width: "30px",
      height: "30px",
      borderRadius: "var(--radius-sm)",
      background: "var(--danger-bg)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0,
    },
    fileName: {
      fontSize: "12px",
      fontWeight: 500,
      color: "var(--text-primary)",
      wordBreak: "break-all",
    },
    fileMeta: {
      fontSize: "11px",
      color: "var(--text-muted)",
      marginTop: "2px",
    },
    body: {
      fontSize: "13px",
      color: "var(--text-secondary)",
      lineHeight: 1.65,
    },
    quotaBox: {
      margin: "10px 12px",
      padding: "9px 12px",
      background: "var(--warning-bg)",
      border: "1px solid var(--warning-border)",
      borderRadius: "var(--radius-sm)",
      fontSize: "12px",
      color: "var(--warning-text)",
      lineHeight: 1.55,
    },
  };
 
  return (
    <>
      <div style={s.fileRow}>
        <div style={s.fileChip}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--danger-text)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
        </div>
        <div>
          <p style={s.fileName}>{filename}</p>
          <p style={s.fileMeta}>Indexed successfully</p>
        </div>
      </div>
 
      {quota && (
        <div style={s.quotaBox}>
          <strong style={{ fontWeight: 600 }}>Gemini quota reached.</strong> Your document is indexed and chat is ready. Summary and key facts will appear once the daily quota resets.
        </div>
      )}
 
      <div style={s.section}>
        <p style={s.label}>Summary</p>
        <p style={s.body}>{summary}</p>
      </div>
    </>
  );
}
