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

  try {
    const user = await prisma.user.findUnique({ where: { email: email.trim().toLowerCase() } });
    if (!user || !verifyPassword(password, user.passwordHash)) {
      res.status(401).json({ error: "Invalid email or password" });
      return;
    }

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
