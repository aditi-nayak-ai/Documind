import { Component } from "react";
 
// Without this, any exception thrown while rendering unmounts the entire
// React tree and the user is left with a blank white page and no clue why.
export default class ErrorBoundary extends Component {
  state = { failed: false };
 
  static getDerivedStateFromError() {
    return { failed: true };
  }
 
  componentDidCatch(error, info) {
    console.error("UI crashed:", error, info?.componentStack);
  }
 
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div
        role="alert"
        style={{
          minHeight: "100vh", display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", gap: "12px",
          background: "var(--bg)", color: "var(--text-secondary)", fontSize: "14px",
        }}
      >
        <p>Something went wrong displaying this page.</p>
        <button
          onClick={() => window.location.reload()}
          style={{
            padding: "8px 16px", cursor: "pointer", fontFamily: "inherit",
            background: "var(--bg-hover)", color: "var(--text-primary)",
            border: "1px solid var(--border-mid)", borderRadius: "var(--radius-sm)",
          }}
        >
          Reload
        </button>
      </div>
    );
  }
}
