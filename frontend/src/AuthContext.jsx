import { createContext, useContext, useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";

const AuthContext = createContext(null);

const TOKEN_KEY = "documind_token";

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
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
    sessionStorage.setItem(TOKEN_KEY, res.data.access_token);
    setToken(res.data.access_token);
  };

  const register = async (email, password) => {
    await api.post("/auth/register", { email, password });
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Swallow: logging out locally must succeed even if the network call didn't.
    }
    sessionStorage.removeItem(TOKEN_KEY);
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
