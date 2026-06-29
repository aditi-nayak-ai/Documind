const isQuotaFact = (facts) =>
  facts?.length === 1 && facts[0]?.toLowerCase().includes("quota");
 
export default function FactsPanel({ facts }) {
  const quota = isQuotaFact(facts);
 
  const s = {
    section: {
      padding: "14px 16px",
    },
    label: {
      fontSize: "10px",
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.07em",
      marginBottom: "10px",
    },
    list: {
      display: "flex",
      flexDirection: "column",
      gap: "8px",
    },
    item: {
      display: "flex",
      alignItems: "flex-start",
      gap: "9px",
      fontSize: "13px",
      color: "var(--text-secondary)",
      lineHeight: 1.6,
    },
    dot: {
      width: "5px",
      height: "5px",
      borderRadius: "50%",
      background: "var(--accent)",
      marginTop: "7px",
      flexShrink: 0,
    },
    quotaText: {
      fontSize: "13px",
      color: "var(--text-muted)",
      fontStyle: "italic",
    },
  };
 
  return (
    <div style={s.section}>
      <p style={s.label}>Key facts</p>
      {quota ? (
        <p style={s.quotaText}>Unavailable — quota limit reached.</p>
      ) : (
        <ul style={s.list}>
          {facts.map((fact, i) => (
            <li key={i} style={s.item}>
              <span style={s.dot} />
              <span>{fact}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
