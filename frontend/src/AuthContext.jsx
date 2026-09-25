import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";
 
const TOKEN_KEY = "documind_token";
 
const AuthContext = createContext(null);
 
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
 
  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
    setIsAuthenticated(false);
  }, []);
 
  // api.js guarantees a 401 always means "the token is missing, expired,
  // or revoked" -- never anything else (see backend app/auth.py). So the
  // only correct reaction, from anywhere in the app, is dropping the
  // session and falling back to the login screen.
  useEffect(() => {
    setUnauthorizedHandler(clearSession);
  }, [clearSession]);
 
  // On first load, a token may already be sitting in localStorage from a
  // previous visit. Validate it against the server before trusting it --
  // otherwise a stale/expired token would flash the authenticated UI and
  // then immediately bounce the user back to login on the first request.
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setCheckingSession(false);
      return;
    }
    api
      .get("/auth/me")
      .then((res) => {
        setUser(res.data);
        setIsAuthenticated(true);
      })
      .catch(() => {
        clearSession();
      })
      .finally(() => setCheckingSession(false));
  }, [clearSession]);
 
  const login = useCallback(async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    localStorage.setItem(TOKEN_KEY, res.data.access_token);
    setUser({ email });
    setIsAuthenticated(true);
  }, []);
 
  // Deliberately does NOT store the returned token or authenticate the
  // user. Registering used to store whatever access_token the backend
  // returned and jump straight to the upload screen, skipping login
  // entirely -- see AuthPage.test.jsx for the regression this guards.
  const register = useCallback(async (email, password) => {
    await api.post("/auth/register", { email, password });
  }, []);
 
  const logout = useCallback(() => {
    // Best-effort server-side revocation (bumps token_version); the
    // session is cleared locally either way.
    api.post("/auth/logout").catch(() => {});
    clearSession();
  }, [clearSession]);
 
  const value = { user, isAuthenticated, checkingSession, login, register, logout };
 
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
 
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
