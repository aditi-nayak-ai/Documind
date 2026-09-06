import { createContext, useContext, useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";

const AuthContext = createContext(null);

const TOKEN_KEY = "documind_token";

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(null);
  // Distinguishes "we haven't checked yet" from "checked, not logged in" --
  // without this, a page refresh with a valid stored token would flash
  // the login screen for a moment before /auth/me resolves.
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    // If the api.js interceptor ever sees a 401 (expired/invalid/forged
    // token — see that file's comment), this is what actually clears the
    // logged-in UI state to match the token already being gone.
    setUnauthorizedHandler(() => {
      setToken(null);
      setUser(null);
    });
  }, []);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setCheckingSession(false);
      return;
    }
    api
      .get("/auth/me")
      .then((res) => setUser(res.data))
      .catch(() => {
        setToken(null);
        setUser(null);
      })
      .finally(() => setCheckingSession(false));
  }, [token]);

  const login = async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    localStorage.setItem(TOKEN_KEY, res.data.access_token);
    setToken(res.data.access_token);
  };

  const register = async (email, password) => {
    const res = await api.post("/auth/register", { email, password });
    localStorage.setItem(TOKEN_KEY, res.data.access_token);
    setToken(res.data.access_token);
  };

  const logout = () => {
    // No server-side call: there's no revocation endpoint (see backend
    // app/auth.py -- tokens are stateless JWTs with no revocation store),
    // so "logout" here only ever means "forget the token locally."
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{ token, user, isAuthenticated: !!token, checkingSession, login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
