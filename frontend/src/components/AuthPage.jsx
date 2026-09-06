import { useState } from "react";
import { useAuth } from "../AuthContext";

export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (Array.isArray(detail)) {
        // FastAPI/pydantic 422 responses return a list of validation
        // errors, not a single string -- e.g. password under 8 chars.
        setError(detail.map((d) => d.msg).join(" "));
      } else if (detail) {
        setError(detail);
      } else if (e.request) {
        setError("Cannot reach the server. Check that the backend is running.");
      } else {
        setError("Unexpected error. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const s = {
    page: {
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", minHeight: "100vh", padding: "2rem",
      background: "var(--bg)",
    },
    wordmark: {
      fontSize: "32px", fontWeight: 600, color: "var(--text-primary)",
      letterSpacing: "-0.5px", marginBottom: "6px",
    },
    accent: { color: "var(--accent)" },
    tagline: { fontSize: "14px", color: "var(--text-secondary)", marginBottom: "2rem" },
    card: {
      width: "100%", maxWidth: "360px", background: "var(--bg-card)",
      border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "1.75rem",
    },
    tabRow: {
      display: "flex", gap: "4px", marginBottom: "1.25rem",
      background: "var(--bg)", borderRadius: "var(--radius-sm)", padding: "3px",
    },
    tab: (active) => ({
      flex: 1, textAlign: "center", padding: "7px 0", fontSize: "13px",
      fontWeight: 500, borderRadius: "6px", cursor: "pointer",
      color: active ? "#fff" : "var(--text-secondary)",
      background: active ? "var(--accent)" : "transparent",
      transition: "background 0.15s, color 0.15s",
    }),
    label: {
      display: "block", fontSize: "12px", color: "var(--text-secondary)",
      marginBottom: "5px", marginTop: "12px",
    },
    input: {
      width: "100%", boxSizing: "border-box", background: "var(--bg)",
      border: "1px solid var(--border-mid)", borderRadius: "var(--radius-sm)",
      padding: "9px 12px", fontSize: "13px", color: "var(--text-primary)",
      fontFamily: "inherit", outline: "none",
    },
    hint: { fontSize: "11px", color: "var(--text-muted)", marginTop: "5px" },
    submitBtn: {
      width: "100%", marginTop: "20px",
      background: loading ? "rgba(124,58,237,0.5)" : "var(--accent)",
      color: "#fff", fontSize: "13px", fontWeight: 500, padding: "10px 0",
      borderRadius: "var(--radius-sm)", border: "none",
      cursor: loading ? "default" : "pointer", fontFamily: "inherit",
    },
    errorMsg: {
      marginTop: "14px", fontSize: "12px", color: "var(--danger-text)",
      background: "var(--danger-bg)", padding: "9px 12px", borderRadius: "var(--radius-sm)",
    },
  };

  return (
    <div style={s.page}>
      <p style={s.wordmark}>Docu<span style={s.accent}>Mind</span></p>
      <p style={s.tagline}>Sign in to upload and chat with your documents.</p>

      <div style={s.card}>
        <div style={s.tabRow}>
          <div style={s.tab(mode === "login")} onClick={() => { setMode("login"); setError(""); }}>
            Log in
          </div>
          <div style={s.tab(mode === "register")} onClick={() => { setMode("register"); setError(""); }}>
            Sign up
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <label style={s.label} htmlFor="email">Email</label>
          <input id="email" type="email" style={s.input} value={email}
            onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />

          <label style={s.label} htmlFor="password">Password</label>
          <input id="password" type="password" style={s.input} value={password}
            onChange={(e) => setPassword(e.target.value)} required
            minLength={mode === "register" ? 8 : undefined}
            autoComplete={mode === "login" ? "current-password" : "new-password"} />
          {mode === "register" && <p style={s.hint}>At least 8 characters.</p>}

          <button type="submit" style={s.submitBtn} disabled={loading}>
            {loading ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>

        {error && <p style={s.errorMsg}>{error}</p>}
      </div>
    </div>
  );
}
