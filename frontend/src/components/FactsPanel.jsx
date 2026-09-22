import { toFactList } from "../docStatus";
 
// `failed` is an explicit flag from the backend. Previously a single fact
// containing the word "quota" was treated as a failure and replaced with a
// hard-coded message, and a non-array `facts` crashed the whole page.
export default function FactsPanel({ facts, failed = false }) {
  const list = toFactList(facts);
 
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
    note: {
      fontSize: "13px",
      color: "var(--text-muted)",
      fontStyle: "italic",
    },
  };
 
  return (
    <div style={s.section}>
      <p style={s.label}>Key facts</p>
      {failed ? (
        <p style={s.note}>{list[0] || "Key facts are unavailable."}</p>
      ) : list.length === 0 ? (
        <p style={s.note}>No key facts were extracted.</p>
      ) : (
        <ul style={s.list}>
          {list.map((fact, i) => (
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
