/**
 * Tier-1 in-memory GET response cache (shared module).
 *
 * The dataset behind every read endpoint is static — it only changes when the
 * model exports are re-generated and `npm run seed` is re-run. Caching GET
 * responses in RAM means the first request per URL hits Postgres and every
 * repeat within the TTL is answered from memory (microseconds vs. a ~250 ms
 * remote-DB round trip per request).
 *
 * The cache self-expires after CACHE_MAX_AGE_SECONDS (default 5 minutes,
 * override with the env var) and is cleared on server restart. The refresh job
 * (POST /api/admin/refresh) calls clearResponseCache() when it finishes, so
 * freshly re-seeded rows are served immediately without waiting out the TTL.
 */
export const CACHE_MAX_AGE_SECONDS = parseInt(
  process.env.CACHE_MAX_AGE_SECONDS || "300",
  10
);
const CACHE_MAX_ENTRIES = 200;
// Allow caching of the analytics full-record payload (~42 MB for 43,996 rows
// with top_factors). That response is static between model runs but larger than
// a generic cap, so it was never cached and /analytics paid a ~40 s remote-DB
// query on every session. 64 MB keeps it cached (first hit per TTL hits
// Postgres, repeats are served from RAM + the browser's max-age copy).
export const CACHE_MAX_BODY_BYTES = 64 * 1024 * 1024;

/** key -> pre-serialized JSON payload */
const responseCache = new Map<string, { payload: string; expiresAt: number }>();

export function cacheGet(key: string): string | undefined {
  const entry = responseCache.get(key);
  if (!entry) return undefined;
  if (entry.expiresAt <= Date.now()) {
    responseCache.delete(key); // expired — evict and treat as a miss
    return undefined;
  }
  return entry.payload;
}

export function cacheSet(key: string, payload: string): void {
  // delete-then-set refreshes insertion order (Map evicts oldest first)
  responseCache.delete(key);
  responseCache.set(key, {
    payload,
    expiresAt: Date.now() + CACHE_MAX_AGE_SECONDS * 1000,
  });
  while (responseCache.size > CACHE_MAX_ENTRIES) {
    const oldest = responseCache.keys().next().value;
    if (oldest === undefined) break;
    responseCache.delete(oldest);
  }
}


/** Drop every cached entry (called after a refresh job re-seeds the DB). */
export function clearResponseCache(): void {
  responseCache.clear();
}
