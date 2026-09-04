/**
 * Create/update a VYOMA user — standalone, does NOT touch village/site data.
 *
 * Usage (from the backend/ directory):
 *   npx tsx src/scripts/create-user.ts <email> <password> [name] [role]
 *
 * Examples:
 *   npx tsx src/scripts/create-user.ts admin@vyoma.in "Vyoma@2026" "VYOMA Admin"
 *
 * Passwords are hashed with scrypt before storage (see lib/auth.ts).
 */
import "dotenv/config";
import { PrismaClient } from "@prisma/client";
import { hashPassword } from "../lib/auth.js";

const prisma = new PrismaClient();

async function main() {
  const email = (process.argv[2] ?? "").trim().toLowerCase();
  const password = process.argv[3] ?? "";
  const name = process.argv[4]?.trim() || email.split("@")[0];
  const role = process.argv[5]?.trim() || "admin";

  if (!email || !password) {
    console.error(
      "Usage: npx tsx src/scripts/create-user.ts <email> <password> [name] [role]"
    );
    process.exit(1);
  }
  if (password.length < 6) {
    console.error("Password must be at least 6 characters.");
    process.exit(1);
  }

  const user = await prisma.user.upsert({
    where: { email },
    update: { passwordHash: hashPassword(password), name, role },
    create: { email, passwordHash: hashPassword(password), name, role },
  });

  console.log(`✓ User ready: ${user.email} (${user.name}, role=${user.role}, id=${user.id})`);
  console.log("  Sign in at http://localhost:5173/login");
}

main()
  .catch((e) => {
    console.error("create-user failed:", e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
