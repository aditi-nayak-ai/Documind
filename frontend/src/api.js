import axios from "axios";

export const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";

// One shared axios instance instead of each component calling axios
// directly with its own BACKEND constant (the old pattern in
// UploadZone.jsx / ChatWindow.jsx). Centralizing it here means the auth
// header and the 401 handling below only have to be written once, and
// every request automatically gets both.
export const api = axios.create({ baseURL: BACKEND });

// Attaches the current token to every outgoing request. Reading it fresh
// from localStorage on each request (rather than capturing it once at
// client-creation time) means a login/logout that happens after this
// module first loads is picked up immediately, with no stale-closure bug.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("documind_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// A 401 here always means the same thing: the token is missing, expired,
// or was forged/tampered with (see backend app/auth.py get_current_user --
// it never returns any other status). There's no refresh-token flow (see
// that same file's docstring for why), so the only correct response to a
// 401 is dropping the stored token and sending the person back to
// login -- silently retrying or ignoring it would just produce more 401s.
let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("documind_token");
      onUnauthorized();
    }
    return Promise.reject(error);
  }
);
