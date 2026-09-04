# Changelog

All notable changes to the NE India Hazard Red Zone Platform.

## [Unreleased] — User login & logout activated (Sep 2026)

- **Login/logout are now real.** Previously the Logout page was a placeholder and there was no auth anywhere. Now:
  - **Backend** — new Prisma `User` model (`backend/prisma/schema.prisma`; table pushed to Postgres), `backend/src/lib/auth.ts` (scrypt password hashing + signed stateless session tokens — Node `crypto` only, **zero new npm dependencies**), and `backend/src/routes/auth.ts` exposing `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`. `/api/auth` is excluded from the GET response cache in `backend/src/index.ts`.
  - **`npm run create-user <email> <password> [name] [role]`** (`backend/src/scripts/create-user.ts`) — standalone user creation that does NOT touch village/site data (no full re-seed needed). Demo user seeded: **admin@vyoma.in / admin123**.
  - **Frontend** — new `frontend/src/pages/LoginPage.jsx` (full-screen sign-in outside the app shell), `frontend/src/context/AuthContext.jsx` (token in `localStorage` under `vyoma_auth`, re-validated against `/api/auth/me` on startup so expired/revoked sessions bounce to login), rewritten `LogoutPage` that clears the session and returns to `/login` with a “signed out” notice, and `frontend/src/App.jsx` now gates every page behind `RequireAuth` (loading screen while validating, redirect otherwise). The TopBar’s hardcoded remote avatar was replaced by the signed-in user’s initials chip.
  - **Scope note:** auth gates the UI. The village/site read API remains public by design — the underlying data is public government data and the read endpoints are the performance-tuned Tier-1/2/3 path.
  - Verified live: unauthenticated visit → `/login`; demo credentials → dashboard; sidebar Logout → session cleared + `/login` with signed-out banner; wrong password → 401. Backend `tsc --noEmit`, frontend `vite build`, and the full Python suite all pass.

## [Unreleased] — Stale-bundle fix: run-tagged bundles + latest.json discovery (Sep 2026)

- **Fixed: the refresh button's new model run never reached browsers that had loaded the site before.** Root cause: the model-refresh job (`backend/src/lib/refreshJob.ts`) regenerated the Tier-3 static bundles **in place under the same filename** (`vyoma_compact_v1.1-susceptibility-2.json`). Browsers cache that URL with `Cache-Control: immutable` on first load, and an immutable entry is never revalidated — so after the re-run the dashboard chip still showed the OLD `Predicted Sep 2, 2026, 04:59 PM` even though the server, DB, and exports all carried the new Sep 4 data. The previous `BUILD_TAG` mechanism was designed for exactly this, but the refresh job could not bump it (the frontend pinned `STATIC_VERSION` in source, and nothing re-pinned it after a server-side refresh).
  - `scripts/generate_frontend_static.py` now derives the bundle filename from the model run's own `predicted_at` timestamp (`vyoma_compact_<version>-<YYYYMMDDTHHMMSSZ>.json`). Every refresh stamps a NEW `predicted_at` → new filename → new URL → browsers holding the old file immutable-cached fetch the new one automatically. No manual version bookkeeping anywhere. Same-timestamp re-runs bump a `-2` suffix instead of overwriting a possibly-cached file, and superseded bundles of the current model version are pruned after the new pair is written.
  - New **`data/processed/static/latest.json`** — a ~220-byte pointer `{ version, predicted_at, compact, sites }` naming the current bundle files.
  - `frontend/src/lib/villagesStore.js` + `sitesStore.js` no longer pin a version string: they fetch `latest.json` (React Query `MANIFEST_KEY`) and then the bundle it names. Backend serves `latest.json` with **`Cache-Control: public, no-store`** (`backend/src/index.ts`) so the pointer itself is never cached; versioned bundles stay immutable in production.
  - Verified live: page load now requests exactly `latest.json` → `vyoma_compact_…20260904T083324Z.json` → `vyoma_sites_…20260904T083324Z.json`; chip reads `Predicted Sep 4, 2026, 02:03 PM · v1.1-susceptibility` (the post-refresh run). Note: after deploying, do one normal reload so the browser picks up the new JS that reads `latest.json`; thereafter every refresh updates automatically.

## [Unreleased] — Village detail: relocation plan card + global data-refresh button (Sep 2026)

- **Village detail page (`/villages/:id`) now shows the relocation plan**, not just a bare site id. The canonical assignment data from `relocation_plan.csv` (single best GREEN destination per RED village) is threaded end-to-end as two **optional extension fields** on the VYOMA export row — `recommended_site_distance_km` (the relocation distance — the cost proxy) and `recommended_site_fit` (`full` / `partial` / `minimal`). Both are `null` on every village without an assignment, so the 16-field ingestion contract is unchanged for consumers that ignore extra keys.
  - `scripts/generate_vyoma_export.py`: emits the two fields from the plan row (`distance_km`, `capacity_fit`).
  - Backend: `Village.recommended_site_distance_km` + `Village.recommended_site_fit` columns in `schema.prisma`; `seed.ts` and `GET /api/villages/:id` (+ full-list projection) carry them through. Database re-pushed and re-seeded (43,996 villages + 12,211 sites).
  - Frontend: the Recommended Site card resolves `recommended_site_id` against the sites bundle and renders destination name + district/state, `46.5 km`-style distance, and a color-coded capacity-fit badge.
- **Global refresh (sync) button in the top bar** (`frontend/src/components/layout/TopBar.jsx` + new `context/RefreshContext.jsx`): one click invalidates every villages/village/sites query and actively refetches what the current page is showing — so a fresh model run (re-export → re-seed → regenerate static bundles) is pulled on demand from anywhere in the app. The dashboard header chip reflects the whole cycle: spinning `sync` + “Refreshing data…” → brief “✓ Synced HH:MM” → back to the live label.
- **The dashboard “sync” chip is now actually live**: it already derived its text from the bundle meta, but the version suffix never rendered because the meta key is `version`, not `model_version` (latent Tier-3 bug) — fixed; the chip now reads `Predicted Sep 2, 2026, 04:59 PM · v1.1-susceptibility` and updates automatically when a refresh delivers a newer run (flashing “✓ Updated · …” when the run identity changes).
- Tests: `tests/validate_vyoma_export.py` (field set 16→18, plus 3 new coherence checks → 22 total: distance/fit populated ⇔ assignment exists) and `tests/behavioral_vyoma.py` (distance/fit mirror the plan rows on the 66 assigned Mizoram villages; null on the rest). Full suite green: pipeline 285/285, behavioral 41/41.

## [Unreleased] — Tier-3 fix: relocation-priority vocabulary in static bundles (Sep 2026)

- **Bug**: the `/villages` page went blank (`TypeError: Cannot read properties of undefined (reading 'bg')`). Root cause: the Tier-3 static bundle was built from the export JSON, which keeps the **model's original vocabulary** (`SHORT_TERM` / `MEDIUM_TERM` / `MONITOR`), while the UI (and the seeded database) uses the translated one (`SHORT-TERM` / `MEDIUM-TERM` / `ROUTINE`). The table's `PRIORITY_COLORS[v.relocation_priority]` lookup returned `undefined` for raw values and crashed the page.
- **Fixes**:
  - `scripts/generate_frontend_static.py` now applies the same priority translation as `backend/src/seed.ts` when building the compact bundle — bundle counts now match the DB exactly (IMMEDIATE 24,220 · SHORT-TERM 5,467 · MEDIUM-TERM 157 · ROUTINE 14,152).
  - New **`BUILD_TAG`** mechanism in the generator (+ `STATIC_VERSION` in `frontend/src/lib/villagesStore.js`): regenerating bundles for the same model version produces a new filename (`vyoma_compact_<version>-<tag>.json`). Browsers with an immutable-cached copy of an older bundle fetch the new one via the new URL (the old immutable entry cannot be invalidated by a header change).
  - Static bundle cache headers: `immutable` is now **production-only**; in development the bundles are served with `max-age=0, must-revalidate` so hand-regenerated files are never served stale.
  - Defensive guard in `HabitationsPage`: unknown `risk_level` / `relocation_priority` values render a neutral chip instead of crashing the page (this is what let `/villages` render while the stale bundle was in play).
- Verified live: `/villages` renders 43,996 rows with correctly colored chips (`SHORT-TERM` → `bg-severity-orange`), dashboard priority summary shows 24,220 / 5,467 / 157, first load still only hits the two static files (no DB), zero console errors.

## [Unreleased] — Tier-3: static versioned data bundles, DB-free first load (Sep 2026)

- **Before**: even with the Tier-1 cache, the very first page load after a server restart queried the database for all 43,996 villages (~10-15 s cold).
- **Now**: the static read path ships as **versioned JSON bundles** served by the backend as plain files with `Cache-Control: public, max-age=31536000, immutable` — the browser downloads each model version once, ever. The database is **never queried for the first page load**.
- New `scripts/generate_frontend_static.py` builds from the canonical exports (run it after regenerating exports):
  - `data/processed/static/vyoma_compact_<model_version>.json` — `{ meta: { version, predicted_at, village_count }, villages: [43,996 compact rows, risk desc] }` (10.7 MB raw, ~1.5 MB gzipped)
  - `data/processed/static/vyoma_sites_<model_version>.json` — 12,211 sites (4.5 MB raw, ~0.5 MB gzipped)
- Backend: `GET /static/*` mounted on `data/processed/static` (env override `STATIC_DATA_DIR`) with immutable headers; gzip via the existing compression middleware.
- Frontend: `villagesStore` now reads the compact bundle (embedded `meta` = the dashboard's `predicted_at` / `model_version`); new `sitesStore` reads the sites bundle. Dashboard stat cards, header metadata, priority summary, and the site-capacity card are now **aggregated in the browser** from those bundles (identical source rows to the old `/api/dashboard` — numbers unchanged: RED 27,881 / ORANGE 3,548 / GREEN 12,567 / sites 12,211 / IMMEDIATE 24,220). SitesPage, CapacityPage and Analytics' site charts region-filter the static list client-side. `api.js` exports `API_BASE` and plain GETs no longer send a Content-Type header (no CORS preflight, so static responses are browser-cacheable).
- Still database-backed (deliberately small/lazy): village detail `/api/villages/:id`, Analytics' full-record fetch (needs per-village `top_factors`), and the `/api/villages/districts` list on state change.
- Live-verified on the Singapore DB: first page load issued exactly **two** requests — the two static files (~170 ms each) — with zero `/api/dashboard`, `/api/villages` or `/api/sites` calls; dashboard numbers match the previous DB-backed values exactly; all 43,996 villages still render on the map.
- Note: `STATIC_VERSION` in `frontend/src/lib/villagesStore.js` must stay in sync with the model version of the current exports; bump it when exports are regenerated with a new version.
- Two bugs found during live verification and fixed: `useAllSites` exposed the raw query result (crash when aggregating before data arrived) and the stores passed absolute URLs into `apiFetch` (which prepends `API_BASE`), doubling the host prefix.

## [Unreleased] — Tier-2 frontend: one fetch, client-side filtering (Sep 2026)

- **Before**: every page (map, villages table, kanban, analytics) re-queried `GET /api/villages?compact=1` with `?state=`/`&district=` filters on every navigation and every filter change — each a fresh remote-DB round trip over the 43,996-village list (~10-15 s cold).
- **Now**: new `frontend/src/lib/villagesStore.js` holds the full compact village list in the React Query cache **once per app session** (`staleTime/gcTime: Infinity` — the exports are static between model runs), prefetched at startup in `App.jsx`. Pages filter that in-memory array by the global State/District selection in milliseconds — **zero per-navigation DB queries**. All 43,996 villages remain available; the map still renders the full dataset (43996 counter, region views included).
- Consumers rewired: `MapPanel` + `CriticalHabitationsTable` (shared dashboard fetch), `MapPage`, `HabitationsPage` (risk/priority chips now fully client-side), `PriorityPage` (kanban), `AnalyticsPage` (lazy-loads the FULL records once on first visit — it charts `top_factors` — then region-filters in memory; sites fetch unchanged). Village detail pages keep their single `/api/villages/:id` fetch.
- Verified live against the Singapore Neon DB: exactly **one** `villages?compact=1` request per page load; navigating map → villages → analytics added **zero** village fetches (only the small `/districts` call on state change); selecting Mizoram switched the map to 830 villages and the table to "Mizoram — 830 of 830 villages" instantly.

## [Unreleased] — Backend Tier-1 performance (gzip + response cache) (Sep 2026)

- **Root cause of UI lag**: every page load re-queried the remote Neon DB (us-east-2) for all 43,996 rows — ~250 ms network round trip per request, plus a 40 MB/5–11 MB JSON transfer and browser-side render of tens of thousands of rows.
- `backend/src/index.ts` additions:
  - **gzip compression** (`compression` middleware) — the 11.2 MB compact villages payload transfers as **1.51 MB (~7.4× smaller)**; JSON is ~90% compressible.
  - **In-memory GET response cache** — first request per URL hits Postgres; every repeat within the TTL is answered from RAM with the pre-serialized payload (no re-stringify, no DB). Only successful 2xx/3xx responses are cached; errors (404/500) and `/api/health` never are. Eviction: TTL expiry (`CACHE_MAX_AGE_SECONDS`, default 300 s), 200-entry cap, 16 MB per-response cap. After re-seeding, restart the server (or wait out the TTL) to invalidate.
  - `Cache-Control: public, max-age=…` + `X-Cache: HIT/MISS` headers on every cached route.
- **Measured live against Neon (43,996 villages)**: `/api/villages?compact=1` **40.06 s cold → 0.051 s cached (~780×)**, payloads byte-identical; `/api/dashboard` **3.93 s cold → 0.003 s cached**; district-filtered list 1.22 s → 0.0035 s; gzip confirmed on cached hits (`Content-Encoding: gzip`); 404s verified never cached.
- New dep: `compression` + `@types/compression` in `backend/`.
- Note: the remaining cold-cache cost on the first visit per URL is the DB read itself (10–40 s at 44k rows over remote Neon); Tier 2 (client-side filtering of one compact fetch / pagination / static-file serving) removes even that.

## [Unreleased] — Map color fidelity at all zoom levels (Sep 2026)

- `GisMap` no longer swaps to a density heatmap when zoomed out. The low-zoom heatmap blended every village toward a red “blur” regardless of true risk color; risk-colored dots (`RED`/`ORANGE`/`GREEN`) are now rendered at **every** zoom level (`villages-circle` minzoom 0). Dot radius and stroke scale with zoom (≈2.5 px at z0 → 8 px at z15) so 44k points stay legible when zoomed out.
- RED pulse halo now only appears above zoom 8 (was 11.5) so it never tints neighboring ORANGE/GREEN dots red at wide views.
- Removed the now-stale “Risk density (zoomed out)” legend row from both `MapPage` and the dashboard `MapPanel` legend.
- Verified live at zoom 6 against the real dataset: `queryRenderedFeatures` returns 40,097 circle features spanning all three risk colors (RED 26,607 / ORANGE 3,413 / GREEN 10,077); no heatmap layer present.

## [Unreleased] — Live Neon setup: seed strategy + env fixes (Sep 2026)

- `backend/.env` created with the real Neon `DATABASE_URL` (gitignored — never committed).
- `backend/src/seed.ts` now imports `dotenv/config` so `npm run seed` loads `.env` (Prisma 6's runtime client does not auto-load it — `index.ts` already did this; the seed did not).
- Seed switched from per-row `upsert` to a **snapshot reload** (clear tables + chunked `createMany`, 5,000/batch): per-row upserts over remote Neon run at ~4 rows/s (43,996 villages would take ~3 hours); bulk insert finished in minutes. The exports are the source of truth; stale rows are removed by design. `SEED_DATA_DIR` / `SEED_VILLAGES_FILE` / `SEED_SITES_FILE` overrides unchanged.
- Verified live against Neon: **43,996 villages + 12,211 sites**, zones RED 27,881 / ORANGE 3,548 / GREEN 12,567 and priorities IMMEDIATE 24,220 / SHORT-TERM 5,467 / MEDIUM-TERM 157 / ROUTINE 14,152 — all matching the canonical exports; 7 states present. (The teammate's 16 Kerala demo rows were cleared during the snapshot load.)

## [Unreleased] — VYOMA real-data scale fixes (Sep 2026)

Review of the merged app against the real 43,996-village dataset surfaced mock-era limitations; fixed in the merged frontend/backend:

### Backend (Express API)
- `GET /api/villages/districts?state=…` — new endpoint returning the real Census district names per state (registered before `/:id` so it can't be swallowed as a village lookup). Powers the cascading State→District selector.
- `GET /api/villages?compact=1` — slim projection (11 map/table fields: id, name, district, state, coords, population, risk_score, risk_level, relocation_priority, low_confidence). The full 16-field objects include heavy per-row `top_factors` JSON; at 44k rows that is ~40 MB vs ~5 MB compact.
- `GET /api/villages` / `GET /api/sites` — optional server-side pagination `?limit=` `?offset=` (applied after the existing sort).
- `GET /api/dashboard` — now also returns `predicted_at` (most recent `prediction_timestamp`) and `model_version` so the UI's "last updated / model version" is real data, never hardcoded.

### Frontend (React)
- `SelectionContext`: districts are loaded live from the new endpoint per selected state (with stale-response guard) instead of the hardcoded 3-per-state placeholder list (which contained non-districts like “Itanagar” and couldn't reach most of the ~180 real districts). `TopBar` disables the district dropdown while loading.
- `GisMap`: fixed an async-data bug — the GeoJSON source was built once from the mount-time village array, so the dashboard map stayed empty after the API query resolved; the source now updates whenever `villages` change. Default view moved from Idukki (Kerala mock) to NE India ([93.5, 25.8], zoom 6); selecting a district now flies the viewport to that district's villages.
- Payload discipline: dashboard map + critical-habitations table share one `compact=1` fetch; Habitations / Priority / Map pages use `compact=1` too (Analytics keeps the full fetch because it aggregates `top_factors`).
- DOM caps at real scale: Kanban renders top 100 per lane (was rendering all 24k IMMEDIATE cards); the dashboard site-capacity card shows the top 30 most-utilized of 12,211 sites with a real count note.
- Dashboard header + stat cards now show real values (`Predicted {timestamp} · {model_version}`, low-confidence counts, GREEN count, sites available) instead of demo chrome (“Last updated: 14:30”, “+1 this week”, “verified”).

### Additional defects found & fixed during the live E2E test pass
- **`/analytics` crashed on entry** (`ReferenceError: SkeletonBars is not defined`) — the loading skeleton used `SkeletonBars` but the import only pulled `SkeletonLoader, SkeletonCards`. Latent in the teammate code; only visible once a real backend serves data (loading state renders first). Fixed the import.
- **Recharts duplicate-key warning** in the site-capacity chart — real Census data has same-named villages in different districts and the truncated chart label collided. Cells now key on `site_id`.
- Oversubscribed sites (>100% occupied — documented semantics) rendered `>100%` bar widths; the card now clamps the bar at 100% and labels it `>100%`.

### Verification (live E2E against a real database)
- Booted an **embedded PostgreSQL**, `prisma db push`, and ran the real seed (`SEED_VILLAGES_FILE=vyoma_export_mizoram.json` + `SEED_SITES_FILE=vyoma_sites_export_mizoram.json`) — 830 villages + 53 sites upserted, vocabulary translation applied (`MONITOR → ROUTINE ×26`).
- Exercised every endpoint against the live DB: `/api/villages/districts` returns the 8 real Mizoram Census districts (empty for unknown states); `?compact=1` returns exactly 11 fields × 830 rows sorted by risk desc; full rows keep `top_factors`/`model_version`; `?limit=`/`?offset=` slide correctly; `district`/`risk_level` filters and `/villages/:id` + `/sites/:id` (incl. 404s) all correct; `/api/villages/districts` is not swallowed by `/:id`; `/api/dashboard` counts match row-level recomputation (RED 810 / ORANGE 9 / GREEN 11), priority keys are the UI taxonomy (`SHORT-TERM`/`ROUTINE`), `predicted_at` ISO + `model_version v1.1-susceptibility` present, capacity bookkeeping intact — **39/39 assertions passed** (2 initial failures were wrong test expectations, not app bugs).
- Live UI drive: dashboard header shows `Predicted Sep 2, 2026 · v1.1-susceptibility`; stat cards 810/9/11 with real details; top-6 critical table; map tiles confirm the NE-India default center (zoom-7 tiles at x≈96/y≈54 — Kerala would be x≈27/y≈62); Villages table renders all 830 rows; State→District cascade loads the real districts from the API and filtering to Aizawl returns 104/104 villages; Priority kanban shows IMMEDIATE 804 with “+704 more (top 100 by risk)”; village detail (Aibawk) renders full factors/site info; Analytics renders all 6 charts. Zero JS exceptions after the fixes.

## [Unreleased] — VYOMA frontend/backend code merged into the repo (Sep 2026)

### What happened
- The teammate's **VYOMA web application** (from the `Vyoma-main` zip) was merged into this repo so the model outputs and the UI that consumes them live together:
  - `frontend/` — React 18 + Vite + Tailwind + MapLibre GL + TanStack Query dashboard (11 routes; dev server :5173). Old single-file demo page replaced.
  - `backend/` — Express + TypeScript + Prisma + PostgreSQL API (routes: villages, sites, dashboard, health; :3001). Old FastAPI demo backend replaced.
- The teammate's **`mockData/` demo dataset was intentionally NOT merged** (placeholder Kerala demo data — superseded by real model exports).
- Old demo dashboard files removed (all still in git history): `frontend/index.html` (single-page Leaflet map), `backend/main.py` + `backend/requirements.txt` (FastAPI server), `run_dashboard.sh`.
- Docs: README gained a “VYOMA Application (merged frontend/backend)” section (structure, run steps, vocabulary note); Project Structure tree updated.

### Seed wiring — real model data, no mock data
- `backend/src/seed.ts` rewritten to ingest **`data/processed/vyoma_export_all_states.json` (43,996 villages) + `vyoma_sites_export_all_states.json` (12,211 sites)** instead of `mockData/*.json`. Env overrides: `SEED_DATA_DIR`, `SEED_VILLAGES_FILE`, `SEED_SITES_FILE`; clear error message if exports are missing (tells the user to run `generate_vyoma_export.py` / `generate_relocation_sites.py`). Progress logged every 5,000 rows.
- Pre-seed validation (run against the live exports): all 43,996 village rows have the 16 required fields, correct types, in-range Ints, parseable ISO timestamps, non-empty `top_factors`; all 12,211 site rows have complete 6-key boolean `infrastructure`; site ids unique; **0 dangling `recommended_site_id`** — zero errors.
- **Relocation-priority vocabulary translation** at seed time (model → UI): `SHORT_TERM → SHORT-TERM`, `MEDIUM_TERM → MEDIUM-TERM`, `MONITOR → ROUTINE` (IMMEDIATE passes through) so the DB matches the kanban lanes / dashboard counts the UI hardcodes (`IMMEDIATE`/`SHORT-TERM`/`MEDIUM-TERM`/`ROUTINE` — verified in `PriorityPage.jsx`, `KanbanBoard.jsx`, `dashboard.ts`). Applied counts: IMMEDIATE 24,220 · SHORT-TERM 5,467 · MEDIUM-TERM 157 · ROUTINE 14,152. `prediction_output.csv` keeps the model's original vocabulary.

### Verification
- Frontend: `npm install` + `npm run build` — clean (703 modules; only a chunk-size advisory). Dev server smoke-tested — app renders (sidebar, dashboard, MapLibre map), zero JS errors; the only console noise is `ERR_CONNECTION_REFUSED` to :3001 when the backend isn't running (documented ErrorState behavior).
- Backend: `npm install` + `npx prisma generate` + `npx tsc --noEmit` — clean.
- `.gitignore` additions: `node_modules/`, `frontend/dist/`, `backend/dist/`, `frontend/.env*`, `backend/.env*`, `backend/prisma/migrations/`.

## [Unreleased] — Full-state VYOMA export + data/processed cleanup (Sep 2026)

### Full 7-state frontend export
- `scripts/generate_vyoma_export.py` (all-states mode) now writes clearly-named outputs instead of the ambiguous `vyoma_export.json`:
  - `data/processed/vyoma_export_all_states.json` — **43,996 villages** (all 7 NE states; RED 27,881 / ORANGE 3,548 / GREEN 12,567)
  - `data/processed/vyoma_sites_export_all_states.json` — **12,211 canonical-GREEN sites**
  - **9,972 villages carry a non-null `recommended_site_id`**; every id resolves to a site row (verified).
- The state-filtered path is unchanged (`vyoma_export_mizoram.json` etc. kept as a small test fixture).
- `tests/validate_vyoma_export.py` now validates BOTH pairs (Mizoram fixture + full all-states export) — 19 schema checks each, all passing. `.gitignore` updated for the new filenames (42.5 MB village + 5.1 MB sites JSONs stay off GitHub).

### data/processed/ cleanup — removed files (all regenerable or superseded)
- **`frontend_data.json`** (20 MB, git-tracked) — pre-VYOMA “frontend data” attempt from Aug 31 with **zero code references**; superseded by `generate_vyoma_export.py`. Deleted.
- **`test_output.csv`** (87 MB) — leftover debug/scratch file with **zero code references**. Deleted.
- **`relocation_matches.csv`** (7.7 MB) — written only by `match_relocation_sites.py`, which nothing in the current pipeline invokes (`relocation_planner.py` superseded it; the VYOMA export consumes `relocation_plan.csv` + `relocation_sites.*` only). Its targets predated the canonical-GREEN-only fix, so it could still recommend villages now flagged RED/ORANGE. Deleted by decision; `match_relocation_sites.py` marked SUPERSEDED in its docstring; `test_pipeline.py` Test 14 repointed from the removed file to the canonical `relocation_sites.csv/.json` register (register-size, canonical-GREEN purity, capacity bookkeeping, CSV↔JSON agreement). The FastAPI demo endpoint `/api/matches/{village_id}` degrades to its existing graceful 404 if called.
- **`vyoma_export.json` / `vyoma_sites_export.json`** — superseded duplicates of the renamed all-states exports. Deleted.
- **`data/processed/maps/`** — empty directory (recreated by `phase4_visualization.py` on demand). Removed.
- **`ne_india_village_features_model_input.csv`** (new, 43,996 × 64) — slim model-input copy: `habitation_id` (joined from `prediction_output.csv` via Village Code), latitude, longitude, state, district + the exact 59 `models/susceptibility_features.json` columns. The full 450-column feature matrix is **kept** — ~20 scripts and tests still read raw Census columns from it.

### Kept as-is (canonical outputs / methodology docs)
`prediction_output.csv`, `carrying_capacity.csv`, `carrying_capacity_assumptions.json`, `social_vulnerability.csv`, `social_vulnerability_assumptions.json`, `relocation_plan.csv`, `relocation_capacity_pool.csv`, `relocation_sites.csv/.json`, plus the Mizoram and all-states VYOMA exports.

### Post-cleanup redundancy audit (follow-up)
- **`village_risk_labels.csv` removed.** Verified fully redundant: all 15 of its columns exist identically in `ne_india_village_features.csv` (same row count 43,996; `high_risk` 29,900/14,096 and `risk_zone` RED 27,881 / ORANGE 11,381 / GREEN 4,734 match exactly), it has **no stable join key** (no Village Code) and **zero consumers** — only `create_labels.py`/`update_labels_flood.py` write it. Labels remain available as columns in the feature matrix; both label scripts re-create the standalone file on demand if ever needed.
- **`relocation_capacity_pool.csv` cleaned at source**: it carried duplicate `state.1`/`district.1` columns (exact copies of `state`/`district`) caused by a rename collision in `generate_relocation_sites.py` (carrying-capacity frame already has lowercase state/district AND the pred join adds uppercase State/District Name). Pool is now built directly from the carrying-capacity frame filtered to the eligible ids — 13 clean columns, same 12,211 rows. Sites register unchanged.
- **Verified NOT redundant** (kept): `social_vulnerability.csv` (full-precision index differs from the 4-decimal-rounded copy in prediction_output by ≤0.0005, plus component columns not elsewhere; read by tests), `relocation_sites.csv` + `.json` (dual serialization of one register — CSV consumed by tests, JSON by the export), Mizoram exports (strict subsets of all-states, kept as small git-tracked fixtures), `ne_india_village_features_model_input.csv` (strict column subset of the feature matrix + identifiers — declared model-input interface). The 7 feature-matrix columns absent from prediction_output (`model_prediction`, `prediction_mean`, `soft_risk_*`, `slope_x_rainfall`, `twi_proxy`) all have producer scripts and are diagnostic/train-time or rejected-experiment columns deliberately excluded from the model and exports — not orphaned data.

## [Unreleased] — Final Review Fixes (threshold model-consistency + Q5 verification)

### Fix A: threshold calibrated AND applied on the susceptibility model
- `optimize_thresholds.py` applied the cost-optimal threshold (tuned on out-of-fold **susceptibility** predictions) to the **historical** model's `risk_score`. Score distributions differ (historical scores are inflated by leakage), so the zones were computed on a different model than the threshold was calibrated for — contradicting the Q1 canonical-model decision.
- **Fix**: `risk_scores = df_pred['susceptibility_score'].values` — threshold and score source now reference the same (canonical) model. `score_column` + Q1 note added to `models/threshold_metadata.json`.
- **Results after re-run** (cost curve unchanged — it was already out-of-fold): cost-optimal threshold **0.28**, cost reduction **65.0%** on OOF predictions (fixed 0.7 threshold baseline). Zone columns now reflect the susceptibility distribution:
  - `predicted_risk_zone_fixed` (RED ≥ 0.28, ORANGE ≥ 0.154): RED 32,937 / ORANGE 2,511 / GREEN 8,548
  - `predicted_risk_zone_quantile` (67% / 1% / 32% by score rank): RED 29,477 / ORANGE 439 / GREEN 14,080
- The older in-sample figures (0.38 threshold, 90.4% reduction) are superseded and corrected below.
- Regression guards added: `test_threshold_model_consistency` (script applies threshold on `susceptibility_score`, never `risk_score`; metadata documents the canonical source).

### Fix B: Q5 (landslide/flood independence) now verified with actual numbers
- Computed on `prediction_output.csv` (decomposition already runs on the susceptibility model): **Pearson correlation(landslide_risk_score, flood_risk_score) = −0.145** across 43,996 villages — mildly negative, not collinear.
- Not proportional to overall risk: within narrow `susceptibility_score` bins the std of (landslide − flood) is **0.105 (0.7–0.8), 0.107 (0.8–0.9), 0.139 (0.9–1.0)** — near-zero if the two moved with overall risk.
- Example villages at near-identical high overall risk: **Pempaleng (Tawang, AP)** sus 0.987 → landslide 0.471 / flood 0.062, vs **Hahim (Kamrup, Assam)** sus 0.966 → landslide 0.043 / flood 0.539.
- Saved to `models/hazard_decomposition_validation.json`; regression guard `test_hazard_independence` asserts correlation < 0.9.

## [Unreleased] — VYOMA Frontend Ingestion Export (Sep 2026)

### Canonical model switch: historical → susceptibility for ALL public output
- `risk_level` / `risk_score` in every public export now come from the leakage-free **susceptibility model** (`susceptibility_risk_zone`, `susceptibility_score`), not the historical model (`predicted_risk_zone`, `risk_score`), for methodological consistency. Historical zones remain as a column and still drive `relocation_timeline`.
- README “Risk Zone Distribution” + “Risk by State” regenerated from `susceptibility_risk_zone`: **RED 27,881 (63.4%) · ORANGE 3,548 (8.1%) · GREEN 12,567 (28.6%)** (per-state sums == headline, verified by new regression test `test_susceptibility_state_totals_consistency`; `test_readme_consistency.py` re-pointed at the susceptibility distribution).

### relocation_timeline verified (4 tiers, README counts confirmed)
- Actual distribution: IMMEDIATE 24,220 (55.1%) · SHORT_TERM 5,467 (12.4%) · MEDIUM_TERM 157 (0.4%) · MONITOR 14,152 (32.2%). README prose that described these as percentile tiers (“Top 30%”) was wrong — rewritten to the real `predict.py` rules (score thresholds + disaster-zone/high-density context).

### priority_level finding (Q3)
- `priority_level` (HIGH/MEDIUM/LOW = 13,199/13,199/17,598) is produced by `phase4_visualization.py` as quantile buckets of `priority_score = historical model_risk_score × vulnerability_score`. It is NOT dead code — `relocation_planner.py`/`match_relocation_sites.py` still use it to include HIGH-priority ORANGE sources — but it is an internal coarse bucket, **excluded from the VYOMA export**. `relocation_priority` maps to `relocation_timeline` instead.

### Relocation sites defined in code (Q4 — “236 IDEAL” was orphaned data)
- Root cause: the legacy “236 IDEAL Relocation Sites” came from `suitability_category == 'IDEAL'` in `prediction_output.csv`, a column **no longer generated by any script** (62 of its 236 rows were RED/ORANGE villages — not valid destinations). Not reproducible live logic.
- `scripts/generate_relocation_sites.py` now defines sites in code with an **eligibility filter on the canonical (susceptibility) zone**: the register is restricted to candidates that are GREEN under the susceptibility model — the same model the export reports as `risk_level`. Final review found the raw carrying-capacity snapshot (14,109, computed against an older historical zone version) contained **366 RED + 1,532 ORANGE villages under the canonical model** — recommending those as destinations would have sent people into zones the export itself flags as hazardous. Excluded → register = **12,211 canonical-GREEN sites**, `is_ideal = carrying_capacity_score ≥ 0.8` → **446 ideal sites**. Output: `data/processed/relocation_sites.csv/.json`; the same eligible set is written as `relocation_capacity_pool.csv` for the planner.
- `relocation_planner.py` now records `red_habitation_id` + `red_population` per row (the old `red_village_id` was a positional index that could not be joined back reliably) and accepts `--capacity <csv>` to plan against a specific candidate pool.
- `relocation_plan.csv` regenerated against the canonical-GREEN pool: **9,972 assigned / 19,715 no-feasible-site (33.6%)**, mean distance 34.6 km — no assignment targets a RED/ORANGE village.

### New export script
- `scripts/generate_vyoma_export.py` — single source of truth for what the frontend consumes: 16 canonical village fields + site array; raw Census columns and all zone/score variants deliberately excluded. Mizoram sample: `data/processed/vyoma_export_mizoram.json` (830 villages, 66 with a recommended site) + `vyoma_sites_export_mizoram.json` (53 sites). `model_version = "v1.1-susceptibility"`.
- `tests/validate_vyoma_export.py` — schema contract validator (19 checks: field set, types, ISO timestamps, vocabularies, dangling site refs, capacity bookkeeping).

### Notes
- `population_vulnerability_multiplier` does not exist as a column; the multiplier actually used in `priority_score` is `vulnerability_score` — exported as `vulnerability_multiplier` and documented.
- Supersedes the earlier in-sample threshold figures: cost-optimal threshold **0.28** with **65.0% cost reduction on out-of-fold predictions** (not 0.38 / 90.4% in-sample).

## [Unreleased] — Model Improvement Pass (Tasks 1-6)

### Task 1: Close Spatial Generalization Gap
- **Hyperparameter search**: Grid search over max_depth (4,6), n_estimators (300,500), learning_rate (0.05), optimized for LOSO AUC. Best: max_depth=4, n_estimators=500.
- **LOSO AUC improved**: 0.685 → 0.696 (+1.1%). Still a large gap vs random CV (0.962) — reveals fundamental spatial autocorrelation in features.
- **Interaction features (slope×rainfall, TWI proxy) HURT**: LOSO decreased by -0.005. Dropped from feature set. Physical interactions don't help when single features already capture the signal.
- **LogReg baseline**: LOSO AUC=0.573 (much worse than XGBoost's 0.696). Extra model complexity IS warranted for spatial transfer.
- **Per-state LOSO**: Worst states: Tripura (0.569), Arunachal Pradesh (0.603). Best: Meghalaya (0.807), Nagaland (0.769).
- **Output**: models/hyperparam_search_spatial.csv, models/spatial_cv_scores.json (with loso_per_state)

### Task 5: Threshold Optimization
- **Cost-optimal threshold (CORRECTED)**: 0.28 on out-of-fold predictions (the original 0.38 figure was in-sample and is superseded). With FN cost weight=5x, lowering threshold reduces missed-risk cost.
- **Cost reduction (CORRECTED)**: 65.0% on out-of-fold predictions (the original 90.4% was in-sample). Threshold is now also *applied* to `susceptibility_score` (canonical model) — see Fix A above.
- **Quantile-based zoning**: Also implemented — top 67% by score = RED.
- **New columns in prediction_output.csv**: predicted_risk_zone_fixed, predicted_risk_zone_quantile
- **Output**: models/threshold_cost_curve.csv, models/threshold_metadata.json

### Task 4: Model Calibration
- **Model is already well-calibrated**: ECE=0.021 (excellent). Platt scaling and isotonic regression WORSENED calibration (ECE=0.224 and 0.205). XGBoost's predict_proba is naturally well-calibrated on this data.
- **Calibration NOT applied** — model outputs used as-is.
- **Output**: models/calibration_plot.png, models/calibration_metadata.json

### Task 2: Distance-Decay Soft Labels
- **Soft risk contribution**: exp(-distance_km / decay_constant), summing landslide (decay=5km) and flood (decay=7km) contributions.
- **Combined soft risk mean**: 0.728 (vs hard label positive rate 68%). More nuanced risk picture.
- **New columns**: soft_risk_landslide, soft_risk_flood, soft_risk_combined
- **Output**: models/soft_label_metadata.json

### Task 6: Uncertainty Quantification
- **Bootstrap ensemble**: 7 XGBoost models trained on resampled data.
- **Prediction uncertainty**: Continuous measure [0,1] based on prediction variance across ensemble.
- **Low confidence**: 25.0% of villages (top quartile of uncertainty).
- **New columns**: prediction_uncertainty, prediction_std, low_confidence (updated to continuous)
- **Output**: models/uncertainty_metadata.json

### Negative Results (Honest Reporting)
- Interaction features (slope×rainfall, TWI proxy) did NOT help LOSO AUC. Physical interaction terms don't add signal when single features already capture the mechanism.
- Calibration methods worsened model calibration. XGBoost's native probability estimates are already well-calibrated.
- The 0.265 LOSO-to-random CV gap persists despite tuning. This reflects genuine spatial autocorrelation in the features, not a model tuning problem.

## [Unreleased] — Phase 1-5 + Bug Fixes

### FIX 3 — Stale README Numbers (Data Consistency)
- **Bug**: The README's headline Risk Zone Distribution (29,204 RED = 66.4%) and per-state Risk by State table (22,742 RED = 51.7%) described the same metric but disagreed by 6,462 villages (~14.7 percentage points).
- **Root cause**: Both tables were stale from different points in the pipeline's evolution. The headline was partially updated after bug fixes but never re-derived from the actual `prediction_output.csv`. The per-state table was written early (pre-tie-break fix) and never regenerated.
- **Investigation**: `predicted_risk_zone` (historical model, thresholds: RED ≥ 0.7, ORANGE 0.4–0.7, GREEN < 0.4) is the source of truth. Actual current counts: RED=29,687 (67.5%), ORANGE=258 (0.6%), GREEN=14,051 (31.9%). Per-state sum now matches headline exactly.
- **Fix**: Regenerated both tables from `prediction_output.csv`. Added explicit zone-definition note in README. Added `test_state_totals_consistency()` test (7 assertions) that verifies per-state RED/ORANGE/GREEN counts sum to headline totals. Also corrected stale relocation priority and hazard decomposition counts.
- **Test impact**: 251 → 263 assertions.

### FIX 1 — Slope Extraction Corruption (Critical)
- **Bug**: `extract_raster_features.py` computed slope using `np.gradient(window, src.res[0])` where `src.res[0]` is in degrees (EPSG:4326). This produced rise(meters)/run(degrees) instead of rise/run in consistent units, pushing every slope estimate toward ~90°.
- **Impact**: 95.1% of villages showed slope > 15° (median 89.99°). The `carrying_capacity.py` had to use a terrain_roughness proxy instead of the proper slope filter.
- **Root cause**: SRTM DEM tiles are in WGS84 (EPSG:4326) with pixel size 0.000278° (~30m). The gradient denominator must be converted to meters: `pixel_m = pixel_degrees * 111320 * cos(lat)`.
- **Fix**: `extract_raster_features.py` line 113: added degree-to-meter conversion. `fix_slope.py` created to re-extract slope for all 43,996 villages. `carrying_capacity.py` updated to use proper slope < 15° filter instead of roughness proxy.
- **Validation**: Sanity-checked on 6 known-terrain villages (Aizawl=10.2°, Guwahati=2.3°, etc.). Corrected distribution: mean=8.92°, median=4.06°, >15°=21.8%.
- **SHAP impact**: slope_degrees moved to rank #10 (importance=0.124) — meaningful but not dominant. CV scores: Random AUC=0.978, LOSO AUC=0.678.

### FIX 2 — Floating-Point Tie-Break (Low Priority)
- **Issue**: Village "Gandhia No.2" had ls=0.5741 vs fl*1.2=0.57408 — a near-exact tie at the classification boundary.
- **Fix**: `hazard_decomposition.py`: changed `>` to `>=` for landslide_dominates comparison, with explicit comment: "ties resolve to RELOCATE (conservative for disaster safety)."
- **Regression test**: Added to `test_pipeline.py` — locks in Gandhia No.2's expected classification as RELOCATE.

### Phase 1 — Leakage-Free Susceptibility Model
- **New files**: `scripts/spatial_cv.py`, `scripts/train_susceptibility_model.py`
- **Feature count**: 59 features (16 physical + 44 Census infra), 7 leakage features dropped
- **Spatial CV**: LOSO AUC=0.678, LODO AUC=0.770, gap=0.300 (honest generalization measure)
- **New columns**: `susceptibility_score`, `susceptibility_risk_zone`, `is_novel_red_zone`

### Phase 2 — Carrying Capacity Assessment
- **Rewritten**: `scripts/carrying_capacity.py` with buildable land (slope < 15°), water margin, infra headroom
- **Output**: `data/processed/carrying_capacity.csv` (14,109 candidate villages)
- **Assumptions documented**: `data/processed/carrying_capacity_assumptions.json`

### Phase 3 — Relocation Planner
- **New file**: `scripts/relocation_planner.py` with greedy + LP benchmark
- **Output**: `data/processed/relocation_plan.csv` (29,705 source villages, 11,318 assigned)
- **CLI**: `--village "Betanipam"` for single-village inspection, `--radius 30` for custom radius

### Phase 4 — Social Vulnerability
- **New file**: `scripts/social_vulnerability.py` with SC/ST %, density, female ratio
- **New columns**: `social_vulnerability_index`, `relocation_sensitivity`
- **Priority score updated**: `risk × (0.6 × pop_weight + 0.4 × vulnerability)`

### Phase 5 — Multi-Hazard Decomposition
- **New file**: `scripts/hazard_decomposition.py` with SHAP-based landslide vs flood decomposition
- **New columns**: `landslide_risk_score`, `flood_risk_score`, `recommended_action`
- **Actions**: RELOCATE (30%), MITIGATE (43%), MONITOR (27%)

## Breaking Changes

| Change | Migration |
|--------|-----------|
| `slope_degrees` values corrected | Re-run `fix_slope.py` then `carrying_capacity.py` |
| `priority_score` formula updated | Re-run `social_vulnerability.py` |
| `recommended_action` threshold changed (> to >=) | Re-run `hazard_decomposition.py` |

## Schema Additions (non-breaking)

New columns in `prediction_output.csv`:
- `susceptibility_score`, `susceptibility_risk_zone`, `is_novel_red_zone` (Phase 1)
- `social_vulnerability_index`, `relocation_sensitivity` (Phase 4)
- `landslide_risk_score`, `flood_risk_score`, `recommended_action` (Phase 5)

New output files:
- `data/processed/carrying_capacity.csv` (Phase 2)
- `data/processed/relocation_plan.csv` (Phase 3)
- `data/processed/social_vulnerability.csv` (Phase 4)
