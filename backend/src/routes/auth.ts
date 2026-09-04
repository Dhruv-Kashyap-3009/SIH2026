/**
 * Auth routes — POST /api/auth/login, GET /api/auth/me, POST /api/auth/logout.
 *
 * Login verifies the email/password against the User table (scrypt hash), then
 * returns a signed stateless token + the public user profile. /me re-validates
 * a stored token on app startup. Logout is stateless — the client discards its
 * token (the endpoint exists so the API contract is explicit).
 */
import { Router, Request, Response } from "express";
import prisma from "../lib/prisma.js";
import { signToken, verifyPassword, verifyToken } from "../lib/auth.js";

const router = Router();

// ---------------------------------------------------------------------------
// Login rate limiting (in-memory fixed window, per email+IP).
//
// Deliberately dependency-free: a Map of { attempts, windowStart } pruned lazily
// on each request. Limits are env-overridable for tests:
//   LOGIN_RATE_MAX_ATTEMPTS  (default 10)  attempts allowed per window
//   LOGIN_RATE_WINDOW_MS     (default 15 min)
// Note: state lives in this process only — fine for the single-instance demo;
// a horizontally-scaled deployment needs a shared store (Redis/DB) instead.
// ---------------------------------------------------------------------------
interface RateEntry {
  failures: number;
  windowStart: number;
}
const loginFailures = new Map<string, RateEntry>();
const RATE_MAX = parseInt(process.env.LOGIN_RATE_MAX_ATTEMPTS ?? "10", 10) || 10;
const RATE_WINDOW_MS =
  parseInt(process.env.LOGIN_RATE_WINDOW_MS ?? String(15 * 60_000), 10) ||
  15 * 60_000;

/** True when this key has exceeded the failure budget inside the window. */
function isRateBlocked(key: string): boolean {
  const now = Date.now();
  const entry = loginFailures.get(key);
  if (!entry) return false;
  if (now - entry.windowStart >= RATE_WINDOW_MS) {
    loginFailures.delete(key); // window expired — clean slate
    return false;
  }
  return entry.failures >= RATE_MAX;
}

/** Record one failed login (only failures count — successes never lock anyone out). */
function recordRateFailure(key: string) {
  const now = Date.now();
  const entry = loginFailures.get(key);
  if (!entry || now - entry.windowStart >= RATE_WINDOW_MS) {
    loginFailures.set(key, { failures: 1, windowStart: now });
    return;
  }
  entry.failures += 1;
}

/** Seconds until a blocked key's window resets (for the Retry-After header). */
function rateRetryAfterSec(key: string): number {
  const entry = loginFailures.get(key);
  if (!entry) return 0;
  return Math.max(1, Math.ceil((entry.windowStart + RATE_WINDOW_MS - Date.now()) / 1000));
}

// Lazy prune so the map never grows without bound (entries also self-expire on
// their next access).
function pruneRateEntries() {
  const now = Date.now();
  for (const [k, v] of loginFailures) {
    if (now - v.windowStart >= RATE_WINDOW_MS) loginFailures.delete(k);
  }
}


function publicUser(u: { id: string; email: string; name: string; role: string }) {
  return { id: u.id, email: u.email, name: u.name, role: u.role };
}

/** POST /api/auth/login — { email, password } → { token, user } */
router.post("/login", async (req: Request, res: Response) => {
  const { email, password } = req.body ?? {};
  if (typeof email !== "string" || typeof password !== "string") {
    res.status(400).json({ error: "Email and password are required" });
    return;
  }

  const emailNorm = email.trim().toLowerCase();
  // Rate limit per (email, client IP): cheap check BEFORE the scrypt work.
  const rateKey = `${emailNorm}|${req.ip ?? "unknown"}`;
  pruneRateEntries();
  if (isRateBlocked(rateKey)) {
    const retryAfterSec = rateRetryAfterSec(rateKey);
    res.set("Retry-After", String(retryAfterSec));
    res.status(429).json({
      error: `Too many failed login attempts. Try again in ${Math.ceil(retryAfterSec / 60)} minute(s).`,
    });
    return;
  }

  try {
    const user = await prisma.user.findUnique({ where: { email: emailNorm } });
    if (!user || !verifyPassword(password, user.passwordHash)) {
      recordRateFailure(rateKey);
      res.status(401).json({ error: "Invalid email or password" });
      return;
    }

    // Success — clear any accumulated failures for this key (clean slate).
    loginFailures.delete(rateKey);
    res.json({
      token: signToken({ id: user.id, email: user.email, name: user.name, role: user.role }),
      user: publicUser(user),
    });
  } catch (error) {
    console.error("POST /api/auth/login error:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

/** GET /api/auth/me — Authorization: Bearer <token> → { user } | 401 */
router.get("/me", async (req: Request, res: Response) => {
  const header = req.headers.authorization;
  const token = header?.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token) {
    res.status(401).json({ error: "Not authenticated" });
    return;
  }

  const payload = verifyToken(token);
  if (!payload) {
    res.status(401).json({ error: "Invalid or expired session" });
    return;
  }

  try {
    const user = await prisma.user.findUnique({ where: { id: payload.id } });
    if (!user) {
      res.status(401).json({ error: "User no longer exists" });
      return;
    }
    res.json({ user: publicUser(user) });
  } catch (error) {
    console.error("GET /api/auth/me error:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

/** POST /api/auth/logout — stateless; client discards its token. */
router.post("/logout", (_req: Request, res: Response) => {
  res.status(204).end();
});

export default router;
