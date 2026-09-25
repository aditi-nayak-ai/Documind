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
 
  const logout = async () => {
    // Best-effort server-side revocation: this bumps the user's
    // token_version (see backend app/database.py increment_token_version),
    // which immediately invalidates this token -- and every other
    // outstanding token for this user -- rather than leaving it valid
    // for the rest of its 7-day life with no way to kill it. If the
    // request fails (offline, server down), we still clear local state
    // below so the user isn't stuck unable to log out from this device;
    // the token itself would remain valid server-side until it expires
    // in that case, same as before this change.
    try {
      await api.post("/auth/logout");
    } catch {
      // Swallow: logging out locally must succeed even if the network
      // call didn't. See comment above.
    }
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
