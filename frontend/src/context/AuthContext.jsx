/**
 * AuthContext — session state for the VYOMA login gate.
 *
 * The token is a signed stateless token from POST /api/auth/login, kept in
 * localStorage under `vyoma_auth`. On startup the token is re-validated against
 * GET /api/auth/me:
 *   - /me answers 200            → session confirmed, user set.
 *   - /me answers 401            → session is definitively invalid (revoked /
 *                                 expired) — clear it and show the login page.
 *   - /me fails on the NETWORK   → the backend may be restarting or the DB
 *                                 cold; do NOT destroy the session. Restore the
 *                                 user optimistically from the token payload so
 *                                 the user isn't logged out by a blip. A later
 *                                 page load re-validates against /me.
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
import { decodeSessionToken } from "../lib/session.js";

const STORAGE_KEY = "vyoma_auth";

const AuthContext = createContext(null);

function clearStoredSession() {
  localStorage.removeItem(STORAGE_KEY);
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(STORAGE_KEY));
  const [user, setUser] = useState(null);
  const [initializing, setInitializing] = useState(true);

  // Restore/validate the stored token once on startup.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!token) {
          setUser(null);
          return;
        }

        let confirmedUser = null;
        let definitiveInvalid = false;
        try {
          const res = await fetch(`${API_BASE}/api/auth/me`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (res.ok) {
            const data = await res.json();
            confirmedUser = data.user ?? null;
          } else if (res.status === 401) {
            definitiveInvalid = true; // the backend says this token is no good
          }
          // Any other status (5xx) or a thrown network error → fall through to
          // optimistic restore below — never punish the user for a blip.
        } catch {
          // fetch threw — backend unreachable; keep the token and restore
          // optimistically (a later reload will confirm via /me).
        }

        if (cancelled) return;

        if (definitiveInvalid) {
          clearStoredSession();
          setToken(null);
          setUser(null);
          return;
        }

        const restoredUser =
          confirmedUser ?? decodeSessionToken(token);
        if (restoredUser) {
          setUser(restoredUser);
        } else {
          // Token present but undecodable/expired and /me unavailable — safest
          // is to treat it as invalid rather than fabricate a session.
          clearStoredSession();
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
    clearStoredSession();
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
