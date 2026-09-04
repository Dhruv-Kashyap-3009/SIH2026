/**
 * Auth helpers — password hashing + signed session tokens.
 *
 * Deliberately uses ONLY Node's built-in `crypto` module (scrypt + HMAC-SHA256)
 * so authentication adds zero npm dependencies. This is demo-grade auth for the
 * SIH platform: tokens are stateless (client stores them), and the data API is
 * public by design (the village/site data is public government data) — auth
 * gates the UI, not the read endpoints.
 *
 * Password storage format: `salt:hash` — scrypt(password, salt, 64) hex.
 * Token format: base64url(header).base64url(payload).base64url(HMAC-SHA256 sig)
 * Signed with AUTH_SECRET (falls back to a dev-only default — set a real secret
 * in backend/.env for any non-demo deployment).
 */
import {
  createHmac,
  randomBytes,
  scryptSync,
  timingSafeEqual,
} from "node:crypto";

const AUTH_SECRET =
  process.env.AUTH_SECRET || "vyoma-demo-secret-change-in-production";
const TOKEN_TTL_MS = 1000 * 60 * 60 * 24 * 7; // 7 days

export interface AuthUserPayload {
  id: string;
  email: string;
  name: string;
  role: string;
}

// ---------------------------------------------------------------------------
// Password hashing (scrypt)
// ---------------------------------------------------------------------------

export function hashPassword(password: string): string {
  const salt = randomBytes(16).toString("hex");
  const hash = scryptSync(password, salt, 64).toString("hex");
  return `${salt}:${hash}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(":");
  if (!salt || !hash) return false;
  const candidate = scryptSync(password, salt, 64);
  const expected = Buffer.from(hash, "hex");
  return (
    candidate.length === expected.length && timingSafeEqual(candidate, expected)
  );
}

// ---------------------------------------------------------------------------
// Signed stateless tokens (HMAC-SHA256, JWT-like)
// ---------------------------------------------------------------------------

function b64url(input: Buffer | string): string {
  return Buffer.from(input).toString("base64url");
}

function fromB64url(input: string): Buffer {
  return Buffer.from(input, "base64url");
}

export function signToken(user: AuthUserPayload): string {
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "VYOMA" }));
  const payload = b64url(
    JSON.stringify({ ...user, exp: Date.now() + TOKEN_TTL_MS })
  );
  const sig = createHmac("sha256", AUTH_SECRET)
    .update(`${header}.${payload}`)
    .digest("base64url");
  return `${header}.${payload}.${sig}`;
}

/** Returns the decoded payload, or null when the token is missing/expired/tampered. */
export function verifyToken(token: string): AuthUserPayload | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;

  const [header, payload, sig] = parts;
  const expected = createHmac("sha256", AUTH_SECRET)
    .update(`${header}.${payload}`)
    .digest("base64url");

  const sigBuf = Buffer.from(sig);
  const expectedBuf = Buffer.from(expected);
  if (
    sigBuf.length !== expectedBuf.length ||
    !timingSafeEqual(sigBuf, expectedBuf)
  ) {
    return null;
  }

  try {
    const data = JSON.parse(fromB64url(payload).toString("utf-8"));
    if (typeof data.exp !== "number" || data.exp < Date.now()) return null;
    return {
      id: data.id,
      email: data.email,
      name: data.name,
      role: data.role,
    } as AuthUserPayload;
  } catch {
    return null;
  }
}
