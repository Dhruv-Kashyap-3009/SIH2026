/**
 * AuthContext — session state for the VYOMA login gate.
 *
 * The token is a signed stateless token from POST /api/auth/login, kept in
 * localStorage under `vyoma_auth`. On startup the token is re-validated against
 * GET /api/auth/me (so a revoked/expired session bounces back to /login).
 *
 * Exposes: { user, token, initializing, login(email, password), logout() }
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { API_BASE } from "../lib/api.js";

const STORAGE_KEY = "vyoma_auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(STORAGE_KEY));
  const [user, setUser] = useState(null);
  const [initializing, setInitializing] = useState(true);

  // Restore/validate the stored token once on startup.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!token) return;
        const res = await fetch(`${API_BASE}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error("session invalid");
        const data = await res.json();
        if (!cancelled) setUser(data.user);
      } catch {
        if (!cancelled) {
          // Stale/expired token — clear it so the guard sends us to /login.
          localStorage.removeItem(STORAGE_KEY);
          setToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setInitializing(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || `Login failed (${res.status})`);
    }
    localStorage.setItem(STORAGE_KEY, data.token);
    setToken(data.token);
    setUser(data.user);
    return data.user;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, initializing, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
