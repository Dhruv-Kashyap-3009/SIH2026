/**
 * API client — fetches from VYOMA backend.
 * Base URL comes from VITE_API_URL env variable (never hardcoded).
 */
export const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:3001";

/**
 * Fetch a backend path (relative, e.g. "/api/villages" or "/static/….json").
 * API_BASE is prepended here — callers must pass a path, never an absolute URL.
 */
export async function apiFetch(path, init) {
  // Only send a Content-Type header when there is a body. Plain GETs (the norm
  // here) then stay CORS-simple requests — no preflight, and browser caching
  // of the versioned static bundles works as intended.
  const headers =
    init?.body !== undefined
      ? { "Content-Type": "application/json", ...(init?.headers || {}) }
      : init?.headers || {};
  const res = await fetch(`${API_BASE}${path}`, {
    headers,
    ...init,
  });

  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }

  return res.json();
}
