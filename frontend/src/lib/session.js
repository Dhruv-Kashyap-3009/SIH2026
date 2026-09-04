/**
 * decodeSessionToken — client-side read of the VYOMA session token payload.
 *
 * Used ONLY for optimistic UI restore when the backend is unreachable at startup
 * (the AuthContext still clears the session whenever the backend itself answers
 * 401). Decoding is deliberately signature-free: the backend never trusts this
 * client-derived user for anything — every endpoint is public by design and the
 * real authority is GET /api/auth/me. We only need id/email/name/role for the
 * UI (top-bar chip, route guard) plus the expiry check so long-expired tokens
 * still log the user out.
 *
 * Returns { id, email, name, role } or null when malformed / expired.
 */
export function decodeSessionToken(token) {
  if (!token || typeof token !== "string") return null;

  const parts = token.split(".");
  if (parts.length !== 3) return null;

  let payload;
  try {
    const b64 =
      parts[1].replace(/-/g, "+").replace(/_/g, "/") +
      "=".repeat((4 - (parts[1].length % 4)) % 4);
    payload = JSON.parse(
      decodeURIComponent(escape(atob(b64))) // unicode-safe: name may be non-ASCII
    );
  } catch {
    return null;
  }

  if (!payload || typeof payload !== "object") return null;
  if (typeof payload.exp !== "number" || payload.exp < Date.now()) return null; // expired
  if (typeof payload.id !== "string" || typeof payload.email !== "string") return null;

  return {
    id: payload.id,
    email: payload.email,
    name: typeof payload.name === "string" ? payload.name : payload.email,
    role: typeof payload.role === "string" ? payload.role : "admin",
  };
}
