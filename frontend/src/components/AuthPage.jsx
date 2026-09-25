import { useState } from "react";
import { useAuth } from "../AuthContext";
 
const s = {
  wrap: {
    minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
    background: "var(--bg)",
  },
  card: {
    width: "340px", padding: "28px", background: "var(--bg-card)",
    border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
  },
  title: { fontSize: "16px", fontWeight: 600, color: "var(--text-primary)", marginBottom: "18px" },
  brandAccent: { color: "var(--accent)" },
  field: { marginBottom: "14px" },
  label: { display: "block", fontSize: "12px", color: "var(--text-secondary)", marginBottom: "5px" },
  input: {
    width: "100%", padding: "8px 10px", fontSize: "13px", boxSizing: "border-box",
    border: "1px solid var(--border-mid)", borderRadius: "var(--radius-sm)", fontFamily: "inherit",
  },
  submit: {
    width: "100%", padding: "9px", fontSize: "13px", fontWeight: 600, color: "#fff",
    background: "var(--accent)", border: "none", borderRadius: "var(--radius-sm)",
    cursor: "pointer", fontFamily: "inherit", marginTop: "4px",
  },
  switchRow: { marginTop: "14px", fontSize: "12px", color: "var(--text-secondary)", textAlign: "center" },
  switchLink: { color: "var(--accent)", cursor: "pointer", fontWeight: 600 },
  error: { fontSize: "12px", color: "var(--danger-text)", marginBottom: "10px" },
  info: { fontSize: "12px", color: "var(--success-text)", marginBottom: "10px" },
};
 
export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [submitting, setSubmitting] = useState(false);
 
  // Manually switching tabs is a fresh start -- any leftover error or
  // "account created" message from the previous mode shouldn't linger.
  const switchMode = (nextMode) => {
    setMode(nextMode);
    setError("");
    setInfo("");
  };
 
  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (mode === "register") {
        await register(email, password);
        // Registering does not log the user in (see AuthContext.jsx) --
        // send them to the login tab instead, with the password field
        // cleared but the email they just typed still filled in.
        setPassword("");
        setMode("login");
        setInfo("Account created. Log in to continue.");
      } else {
        await login(email, password);
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(
        Array.isArray(detail)
          ? detail.map((d) => d.msg).join(" ")
          : detail || "Something went wrong. Please try again."
      );
    } finally {
      setSubmitting(false);
    }
  };
 
  return (
    <div style={s.wrap}>
      <div style={s.card}>
        <div style={s.title}>
          Docu<span style={s.brandAccent}>Mind</span>
        </div>
        {error && <div style={s.error}>{error}</div>}
        {info && <div style={s.info}>{info}</div>}
        <form onSubmit={handleSubmit}>
          <div style={s.field}>
            <label style={s.label} htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              style={s.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div style={s.field}>
            <label style={s.label} htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              style={s.input}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "register" ? 8 : undefined}
            />
          </div>
          <button type="submit" style={s.submit} disabled={submitting}>
            {mode === "register" ? "Create account" : "Log in"}
          </button>
        </form>
        <div style={s.switchRow}>
          {mode === "login" ? (
            <>
              Don&apos;t have an account?{" "}
              <span style={s.switchLink} onClick={() => switchMode("register")}>Sign up</span>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <span style={s.switchLink} onClick={() => switchMode("login")}>Log in</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
