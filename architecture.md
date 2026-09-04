# 🏗️ Architecture — NE India Hazard Red Zone Platform (VYOMA)

> SIH 2026 · Problem Statement 26191 · Ministry of Home Affairs (NDRF/DM Division)
> A companion to [`README.md`](README.md) (quick start + headline results), [`design.md`](design.md) (why each design decision was made), [`documentation.md`](documentation.md) (how to operate everything), and [`CHANGELOG.md`](CHANGELOG.md) (history of every change).

This document explains **how the system is built** — every layer, every moving part, and how data flows from raw satellite/government datasets all the way to the browser map.

---

## 1. System at a Glance

```
┌───────────────────────────  MODEL / DATA PIPELINE (Python)  ───────────────────────────┐
│ Raw datasets (Census, SHRUG, SRTM, IMD, GSI, EM-DAT, WorldCover, OSM, DFO)             │
│      │  scripts/join_census_shrug.py · extract_* · combine_features.py                  │
│      ▼                                                                                 │
│ ne_india_village_features.csv  (43,996 × 450 — the feature matrix)                     │
│      │  create_labels.py / update_labels_flood.py  (ground-truth labels)               │
│      ▼                                                                                 │
│ TWO XGBoost models                                                                     │
│    • historical     models/red_zone_xgboost.json        (66 features, 7 leaky)         │
│    • susceptibility models/susceptibility_xgboost.json  (59 features, leakage-free)    │
│      │  scripts/predict.py / refresh_predictions.py  (scores + SHAP top factors)       │
│      ▼                                                                                 │
│ prediction_output.csv  (43,996 × 463 — the canonical per-village master)               │
│      │  downstream modules: social_vulnerability · hazard_decomposition ·              │
│      │  carrying_capacity · relocation_planner · generate_relocation_sites ·           │
│      │  optimize_thresholds · uncertainty_quantification                               │
│      ▼                                                                                 │
│ CANONICAL EXPORTS  (what the app consumes)                                             │
│    vyoma_export_all_states.json         43,996 villages × 18 fields                    │
│    vyoma_sites_export_all_states.json   10,603 relocation sites                        │
│    data/processed/static/*               versioned Tier-3 UI bundles + latest.json     │
└──────────────────────────────────────┬─────────────────────────────────────────────────┘
                                       │  npm run seed (Postgres snapshot load)
┌───────────────────────────  WEB APPLICATION  ─────────────────────────────┐
│ Backend (Express + TypeScript + Prisma + PostgreSQL / Neon)               │
│    /api/villages · /api/sites · /api/dashboard · /api/auth ·              │
│    /api/admin/refresh · /static/* (immutable bundles)                     │
│    Middleware: gzip → GET response cache → routers → 404                  │
│ Frontend (React 18 + Vite + Tailwind + MapLibre GL + TanStack Query)      │
│    / (login) · /dashboard · /map · /villages · /priority · /sites ·       │
│    /capacity · /analytics · /help — all behind an auth gate               │
└────────────────────────────────────────────────────────────────────────────┘
```

The single most important architectural fact: **the frontend never talks to the model**. The model pipeline produces static CSV/JSON artifacts; a seed step loads them into Postgres; the API (plus pre-built static bundles) serves them. Re-running the model = re-running the Python chain → re-exporting → re-seeding. The browser only ever renders.

---

## 2. Repository Layout

```
SIH2026/
├── scripts/            # Entire Python model pipeline (30 scripts) — see §3–§6 and documentation.md §7
├── models/             # Trained models + diagnostics (weights gitignored; CSVs/JSONs tracked)
├── data/
│   ├── raw/            # Input datasets, ~5.6 GB, gitignored (see README "Datasets Used")
│   └── processed/      # Canonical outputs (feature matrix, prediction master, exports, static/)
├── backend/            # Express + Prisma API (:3001)
│   ├── prisma/schema.prisma
│   └── src/
│       ├── index.ts            # app wiring: cors → json → compression → cache → static → routers
│       ├── seed.ts             # Postgres snapshot loader (clear + bulk insert)
│       ├── routes/             # villages · sites · dashboard · auth · admin
│       ├── lib/                # prisma · responseCache · auth · refreshJob
│       └── scripts/create-user.ts
├── frontend/           # React app (:5173)
│   └── src/
│       ├── pages/              # one file per route (Login … Analytics, 404)
│       ├── components/         # layout/ (Sidebar, TopBar) · dashboard/ · ui/ (GisMap, BrandedLoader…)
│       ├── context/            # AuthContext · SelectionContext · RefreshContext
│       └── lib/                # api.js · villagesStore.js · sitesStore.js · session.js
├── tests/              # 6 Python suites (~360 assertions total)
├── README.md · CHANGELOG.md · architecture.md · design.md · documentation.md
```

---

## 3. Data Layer (Phase 0–1: join, extract, combine)

### 3.1 Input datasets (in `data/raw/`)

| Dataset | Content | Role |
|---|---|---|
| Census 2011 Village Directory (7 NE states) | ~396 columns/village — population, literacy, SC/ST, water/power/infra status columns | the demographic/infrastructure feature backbone |
| SHRUG village polygons (Stanford) | 648,878 boundaries keyed to Census | coordinate join → lat/lon + habitation_id |
| SRTM DEM (30 m) | elevation tiles | `elevation_m`, `slope_degrees`, `terrain_roughness` |
| IMD gridded rainfall (0.25°, 2020–24) | daily rainfall | max/mean/90th/95th percentile, rain days |
| GSI landslide inventory | 10,408 points | label source + (historical model) distance/density features |
| EM-DAT | 124 NE-India disasters | label source (15 km buffers) |
| ESA WorldCover (10 m) | land cover, **~60% tile coverage** | `landcover_class` (the main cause of low-confidence flags) |
| OpenStreetMap (NE PBF) | roads, rivers, amenities | distances to road/river/hospital/school, road density |
| DFO Global Flood Database | 274 flood events 1985–2023 | flood label + (historical model) flood distance/density |

### 3.2 Join → feature matrix

Script order and outputs:

| Script | What it produces |
|---|---|
| `join_census_shrug.py` | Census + SHRUG coordinate join → `ne_india_census_with_coords.csv` (44,537 → **43,996** matched, 98.8%) |
| `extract_raster_features.py` | per-village elevation, slope (degree→meter projection fix), roughness from SRTM; land cover from WorldCover. **Slope fix:** gradients must be computed in meters (`pixel_degrees × 111320 × cos(lat)`), not raw degrees — a broken version produced median 89.99° and was corrected to 4.06° |
| `extract_vector_features.py` | OSM distances (road/river/hospital/school), road density, **and** GSI landslide proximity/density (later banned from the susceptibility model) |
| `extract_flood_features.py` | DFO flood distance/density + derived `is_lowland`, `near_major_river` |
| `extract_cloudburst_features.py` | experimental cloudburst-risk stub (not in the trained models) |
| `extract_interaction_features.py` | `slope_x_rainfall`, `twi_proxy` — tested, **rejected** (LOSO AUC −0.005), columns kept in matrix only |
| `combine_features.py` | merges everything → `ne_india_village_features.csv` (**43,996 × 450**) |
| `create_labels.py` / `update_labels_flood.py` | ground-truth `high_risk` binary + `risk_zone` RED/ORANGE/GREEN label from GSI 10 km + EM-DAT 15 km + DFO flood density. **Tie-break convention:** boundary ties resolve to the *higher-risk* class (`>=`, conservative for disaster safety) |

`habitation_id` = `{State Code}-{District Code}-{Sub District Code}-{Village Code}` — a stable Census/SHRUG composite key used everywhere downstream (CSV master, exports, DB primary key).

### 3.3 Data coverage caveats (drive the `low_confidence` flag)

- SRTM: ~1,755 villages missing elevation (28 missing tiles in northern Arunachal) — *fix option: Copernicus GLO-30 fallback*.
- WorldCover: ~26,419 villages missing land cover (~60% coverage) — *fix option: ESRI 10 m LULC / NRSC-Bhuvan fallback*.
- `low_confidence = missing elevation OR missing land cover` → **27,668 villages (62.9%)** flagged; the model median-imputes those features before scoring and the UI shows an amber caveat on the village detail page.

---

## 4. Model Layer (Phase 3)

### 4.1 Two-model design

| | Historical validation model | Susceptibility model (**canonical**) |
|---|---|---|
| File | `models/red_zone_xgboost.json` | `models/susceptibility_xgboost.json` |
| Features | 66 — includes 7 distance/density features built **from the same events used to create the label** | 59 — **zero** label-derived features (physical drivers + Census infra) |
| Purpose | validates the model can find villages near past disasters | predicts genuine hazard susceptibility, incl. *unrecorded* danger |
| Random CV AUC | 0.9994 | 0.9615 |
| Honest spatial CV | — (leaky by construction) | LOSO ≈ 0.696 · LODO ≈ 0.770 |
| Role today | still scored (`risk_score`/`predicted_risk_zone`), used by the relocation **planner** source set and rainfall-refresh demo | **everything public**: export `risk_score`/`risk_level`, dashboard, map, analytics |

### 4.2 CV machinery (`scripts/spatial_cv.py`)

Three regimes so claims are testable and honest:

- **Random 5-fold stratified** — optimistic (spatial autocorrelation leaks across folds).
- **Leave-One-State-Out (LOSO)** — 7 folds; AUC ≈ 0.696. Worst states: Tripura (0.569), Arunachal (0.603); best: Meghalaya (0.807), Nagaland (0.769) — reported per-state in `models/spatial_cv_scores.json`.
- **Leave-One-District-Out (LODO)** — 62 folds; AUC ≈ 0.770.
- **Logistic-regression baseline** (same 59 features, same folds): LOSO ≈ 0.573 → shows XGBoost's complexity earns real spatial transfer.

Results are saved to `models/spatial_cv_scores.json` and mirrored in `models/*.csv`.

### 4.3 Model artifacts (`models/`)

Weights (gitignored, retrainable): `red_zone_xgboost.json`, `susceptibility_xgboost.json`. Metadata + diagnostics (tracked): `model_metadata.json` (historical: 66 feats, AUC 0.9994), `susceptibility_model_metadata.json`, `features.json`, `susceptibility_features.json`, `cv_scores.csv`, `feature_importance.csv`, `susceptibility_feature_importance.csv`, `shap_state_consistency.csv`, `hyperparam_search_spatial.csv`, `spatial_cv_scores.json`, `threshold_metadata.json`, `threshold_cost_curve.csv`, `calibration_metadata.json` (+ png), `uncertainty_metadata.json`, `soft_label_metadata.json`, `hazard_decomposition_validation.json`, evaluation/shap pngs.

---

## 5. Prediction & Decision Post-Processing (Phase 4–7)

`prediction_output.csv` (**43,996 × 463**) is the **canonical master**: model outputs **plus** every downstream module's columns live here, and the exports read from here. `scripts/refresh_predictions.py` re-runs the two models **in place** over this file (keeping the 400+ downstream columns), which is why prediction runs are incremental rather than rebuilt from scratch.

### 5.1 `predict.py`/`refresh_predictions.py` per-village outputs

| Column group | Columns | Notes |
|---|---|---|
| Historical score | `model_risk_score`, `risk_score`, `predicted_risk_zone` | zone from thresholds |
| **Susceptibility (canonical)** | `susceptibility_score`, `susceptibility_risk_zone` | drives exports/UI |
| **Zones** | RED ≥ 0.9 · ORANGE 0.4–0.9 · GREEN < 0.4 | raised from 0.7 on 2026-09-04 — see design.md §6 |
| **Priority tiers** | `relocation_timeline`: IMMEDIATE / SHORT_TERM / MEDIUM_TERM / MONITOR | derived from the *canonical score* with the **same** zone cutoffs so tier never contradicts zone |
| Explainability | `top_factors` (JSON: top-5 SHAP contributors with value/impact/shap) | **susceptibility-model** SHAP (TreeExplainer) — recomputed over the canonical pass so the explanation always matches `risk_level` |
| Quality | `low_confidence` (bool), `prediction_uncertainty`, `prediction_std` | coverage vs bootstrap variance |
| Novelty | `is_novel_red_zone` | canonical-RED AND no recorded historical event within buffers (131 of 20,129) |
| Stamp | `predicted_at` (ISO-UTC), `model_version` | model-file hash (`v1.0-…`); the export rewrites a friendly `v1.1-susceptibility` |

### 5.2 Downstream modules (each writes columns back onto `prediction_output.csv` or its own CSV)

| Script | Adds | Key numbers (current) |
|---|---|---|
| `social_vulnerability.py` | `social_vulnerability_index`, `vulnerability_score`, `relocation_sensitivity`; reweights `priority_score = risk × (0.6·pop_weight + 0.4·vulnerability)`; quantile `priority_level` HIGH/MEDIUM/LOW | sensitivity flags by ST% (≤15 / 15–25 / >25) |
| `hazard_decomposition.py` | `landslide_risk_score`, `flood_risk_score`, `recommended_action` | corr(landslide, flood) = −0.145 (independent); RELOCATE 6,986 / MITIGATE 29,964 / MONITOR 7,046 |
| `carrying_capacity.py` | per-GREEN-village `carrying_capacity.csv`: buildable land (WorldCover usable classes ∩ slope < 15°), water margin, infra headroom → `estimated_absorbable_population` | 14,109 candidates |
| `relocation_planner.py` | `relocation_plan.csv`: RED (+HIGH-ORANGE) → GREEN assignment ≤ 50 km, capacity-constrained, greedy (+LP benchmark) | 29,105 sources → **8,431 assigned**, mean 35.3 km |
| `generate_relocation_sites.py` | canonical-GREEN site register `relocation_sites.csv/.json` + `relocation_capacity_pool.csv` (the planner's safe pool) | **10,603 sites**, `is_ideal` (score ≥ 0.8) → **406** |
| `optimize_thresholds.py` | `predicted_risk_zone_fixed/quantile` + `threshold_metadata.json` | cost-optimal 0.28 on out-of-fold susceptibility predictions, 65% cost cut (research only, not the shipped zones) |
| `uncertainty_quantification.py` | `prediction_uncertainty`, `prediction_std` (7-model bootstrap) | mean 0.1125; top-quartile = 25% |
| `calibrate_model.py` | ECE/reliability report | ECE 0.021 → **calibration NOT applied** (methods made it worse) |
| `create_soft_labels.py` | distance-decay soft labels | **diagnostic only — never a model input** (leakage guard) |
| `refresh_rainfall.py` | demo hook: re-scores villages from changed rainfall with the historical model | updates `prediction_output.csv` (demo only) |

---

## 6. Canonical Export Layer (what the app consumes)

`scripts/generate_vyoma_export.py` is the **single source of truth for "what VYOMA sees"**. It reads `prediction_output.csv` + `relocation_plan.csv` + `relocation_sites.json` and writes:

- `vyoma_export_all_states.json` — 43,996 villages × exactly **18 fields** (id, name, district, state, lat/lon, population, `risk_score` = susceptibility_score, `risk_level` = susceptibility_risk_zone, `relocation_priority` = relocation_timeline, vulnerability_multiplier, top_factors, low_confidence, recommended_site_id/distance_km/fit, prediction_timestamp, model_version). Raw Census columns and all six zone/score variants are deliberately **excluded**.
- `vyoma_sites_export_all_states.json` — the 10,603-site register (mirror of `relocation_sites.json`).
- State-filtered variants (`vyoma_export_mizoram.json`, 830 villages) used as the small git-tracked demo fixture.

`scripts/generate_frontend_static.py` then builds **Tier-3 bundles** into `data/processed/static/`:
`vyoma_compact_<version>-<run_tag>.json` (11 compact fields × 43,996, ~11 MB), `vyoma_sites_<version>-<run_tag>.json` (~4 MB), and `latest.json` (tiny pointer). The run tag embeds `predicted_at`, so every model run yields a new filename → browsers holding an `immutable`-cached old bundle fetch the new one automatically.

---

## 7. Backend Layer (`backend/`, Express + Prisma + Postgres)

### 7.1 Request pipeline (order matters)

```
cors → express.json → compression(gzip) → Tier-1 GET cache middleware → static files → routers → 404
```

- **gzip**: JSON is ~90% compressible; the 11 MB compact list transfers as ~1.5 MB.
- **Tier-1 GET cache** (`lib/responseCache.ts`): in-memory LRU-ish map, TTL 300 s (env `CACHE_MAX_AGE_SECONDS`), 200 entries, 16 MB max body. Successful GETs only. **Excluded**: `/api/health`, `/api/auth/*`, `/api/admin/*`. Responses carry `X-Cache: HIT|MISS` and `Cache-Control`. Cold → cached was measured ~40 s → 0.05 s for the 44k-row list on remote Neon.
- **Static files** (`/static/*`): served from `data/processed/static` (`STATIC_DATA_DIR` override). `latest.json` = `no-store`; versioned bundles = `immutable` in production, `must-revalidate` in dev.

### 7.2 Routes

| Method + path | Purpose |
|---|---|
| `GET /api/villages` | list villages; `?district= ?state= ?risk_level= ?relocation_priority=` filters, `?compact=1` slim 11-field projection, `?limit= ?offset=` pagination (after risk desc sort). **Never returns raw model columns** |
| `GET /api/villages/districts?state=` | distinct district names (registered before `/:id`) |
| `GET /api/villages/:id` | full 18-field record incl. top_factors + relocation fields |
| `GET /api/sites` / `GET /api/sites/:id` | relocation sites register (same filters/pagination) |
| `GET /api/dashboard` | aggregates: total_villages, risk_level{…}, relocation_priority{…}, population_at_risk, avg_risk_score, low_confidence_count, sites, `predicted_at`, `model_version` |
| `POST /api/auth/login` · `GET /api/auth/me` · `POST /api/auth/logout` | session auth (see §9) |
| `POST /api/admin/refresh` · `GET /api/admin/refresh/status` | run/observe the model-refresh chain (§8) |
| `GET /api/health` | liveness |
| `GET /static/latest.json` + bundles | Tier-3 data |

### 7.3 Database (`prisma/schema.prisma`)

- **Village** — village_id (PK = habitation_id), name, district, state, lat/lon, population, risk_score, risk_level, relocation_priority, vulnerability_multiplier, top_factors (Json), low_confidence, recommended_site_id?, recommended_site_distance_km?, recommended_site_fit?, prediction_timestamp, model_version; indexes on district/state/risk_level/relocation_priority.
- **RelocationSite** — site_id (PK), name, district, state, lat/lon, suitability_score, total_capacity, occupied, available, infrastructure (Json with 6 booleans).
- **User** — id (cuid), unique email, name, scrypt `passwordHash`, role, createdAt.

### 7.4 Seed (`npm run seed`, `src/seed.ts`)

Snapshot reload: **clear Village + RelocationSite → chunked `createMany` (5,000/batch)** from `vyoma_export_all_states.json` + `vyoma_sites_export_all_states.json`. Per-row upserts were ~4 rows/s on remote Neon (3 h); bulk insert takes minutes. Env overrides: `SEED_DATA_DIR`, `SEED_VILLAGES_FILE`, `SEED_SITES_FILE` (the Mizoram fixture is seedable the same way). During load it applies the **vocabulary translation** (§8 note) and prints per-priority counts.

---

## 8. The Refresh Chain (the top-bar sync button)

Model outputs are static between runs, so "refresh" = a deterministic re-run orchestrated by `backend/src/lib/refreshJob.ts` (single in-flight job, status polled via `/api/admin/refresh/status`), each step spawning the exact Python script:

1. `python scripts/refresh_predictions.py` — re-run BOTH models over all 43,996 rows (in-place on `prediction_output.csv`), stamp a **new `predicted_at`**
2. `python scripts/generate_relocation_sites.py` — site register from the fresh zones
3. `python scripts/relocation_planner.py --capacity data/processed/relocation_capacity_pool.csv` — re-solve assignments
4. `python scripts/generate_relocation_sites.py` — fold occupancy in
5. `python scripts/generate_vyoma_export.py` (all states) and `--state Mizoram` (fixture)
6. `python scripts/generate_frontend_static.py` — new run-tagged bundles + `latest.json`
7. `npx tsx src/seed.ts` (from `backend/`) — reload Postgres
8. `clearResponseCache()` — fresh rows served instantly

**Deliberate boundary:** the button does **not** retrain XGBoost (with unchanged labels/features training is bit-identical, and it needs the 5.6 GB raw data) — training is always a manual, data-driven step.

**Vocabulary note:** the model CSVs say `SHORT_TERM / MEDIUM_TERM / MONITOR`; the DB/UI speak `SHORT-TERM / MEDIUM-TERM / ROUTINE` (seed + static generator translate). `prediction_output.csv` keeps the original strings.

---

## 9. Authentication Architecture

- **Backend** (`lib/auth.ts`, Node `crypto` only — zero extra deps): passwords hashed with **scrypt** (`salt:hash`); sessions are **HMAC-signed stateless tokens** (`payload.signature`, base64url). `AUTH_SECRET` is **required in production** (server refuses to start without it); a stable dev fallback is used when unset outside production.
- **Endpoints**: `POST /api/auth/login` (email+password → token), `GET /api/auth/me` (validate), `POST /api/auth/logout`. **Login rate limiting**: in-memory fixed window keyed by email+IP, only *failures* count (default 10 / 15 min → HTTP 429 + `Retry-After`); env `LOGIN_RATE_MAX_ATTEMPTS`, `LOGIN_RATE_WINDOW_MS`.
- **Frontend** (`AuthContext` + `lib/session.js`): token stored in `localStorage` (`vyoma_auth`); on startup `/me` is validated — **only a definitive 401 clears the session** (network/DB blips keep you signed in optimistically from the decoded token). Every route except `/`, `/login`, `/logout` sits behind `RequireAuth`.
- **Scope decision:** auth gates the UI. The read API + static data stay public by design (public government data, performance path).
- Users created via `npm run create-user <email> <password> [name]`; demo account **admin@vyoma.in / admin123** (documented in README).

---

## 10. Frontend Layer (`frontend/`, React 18 + Vite)

### 10.1 Routes (`App.jsx`)

| Path | Page | Data source |
|---|---|---|
| `/` | LoginPage | — |
| `/dashboard` | national Overview: stat cards, hazard map, critical habitations, priority + capacity summaries | compact bundle (client-aggregated) |
| `/map` | full-screen hazard map | compact bundle |
| `/villages` | sortable/filterable table of all villages | compact bundle |
| `/villages/:id` | village detail: risk, factors, **relocation plan**, low-confidence badge | `GET /api/villages/:id` |
| `/priority` | relocation-priority kanban (IMMEDIATE → ROUTINE), capped at top-100/lane | compact bundle |
| `/sites` | relocation sites list | sites bundle |
| `/capacity` | site capacity/carrying-capacity view | sites bundle |
| `/analytics` | 6 Recharts panels (lazy-loads FULL records once — needs `top_factors`) | `GET /api/villages` full |
| `/help` | user guide with **live** stat cards from `/api/dashboard` | API |
| `/logout`, `*` | sign-out, 404 | — |

### 10.2 State & data flow

- **Contexts**: `AuthContext` (session), `SelectionContext` (global State/District for client-side filtering), `RefreshContext` (sync-button lifecycle).
- **Stores** (TanStack Query): `villagesStore` holds the compact bundle (React Query cache, `staleTime/gcTime: Infinity` — data only changes when the model re-runs). Keys: manifest (`latest.json`, never cached) → current bundle by name. `sitesStore` mirrors for sites. `HabitationDetailPage` keeps a single `/api/villages/:id` call.
- **Filtering**: the map, table, kanban, and analytics all filter the in-memory compact/full arrays by SelectionContext — region switches are millisecond client-side operations, **zero DB round trips per navigation**.
- **Loading UX**: shared `BrandedLoader` (spinning VYOMA ring + animated dots + shimmer skeletons) on Analytics and Villages first loads; `SkeletonLoader` elsewhere; `ErrorState` with retry everywhere.
- **Map** (`GisMap`, MapLibre GL): risk-colored circles at **every** zoom (no heatmap swap — the old zoomed-out heatmap blurred all three colors into red); RED pulse halo only above zoom 8; district selection flies the viewport.

---

## 11. End-to-End Data Flows (three paths)

**A. One-time build path (training):** raw datasets → feature matrix → labels → train both models → predict → downstream modules → exports → bundles → seed. Run by hand with the scripts in order (documentation.md §6).

**B. Refresh path (sync button):** §8 — re-predict → re-plan → re-export → re-bundle → re-seed → cache cleared. Deterministic given unchanged data; produces a new `predicted_at` and new bundle filenames.

**C. Read path (browser):**
1. First load: `latest.json` (no-store) → current `vyoma_compact_*.json` + `vyoma_sites_*.json` (immutable-cached after first download). **Database not touched.**
2. Region filters/table/map: pure client-side over the cached array.
3. Village detail / analytics full records: one `/api/villages/:id` or full `/api/villages` call (Tier-1 cached server-side).
4. The `Predicted <date> · v1.1-susceptibility` chip reads the bundle meta; the sync button triggers path B and refetches.

---

## 12. Configuration & Ports

| Var | Where | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | backend/.env | — | required Postgres/Neon URL |
| `PORT` | backend | 3001 | **quirk:** shells that export `PORT=0` must start with `PORT=3001` |
| `AUTH_SECRET` | backend/.env | dev fallback | **required** when `NODE_ENV=production` |
| `STATIC_DATA_DIR` | backend | `../data/processed/static` | static bundle root |
| `CACHE_MAX_AGE_SECONDS` | backend | 300 | Tier-1 GET cache TTL |
| `LOGIN_RATE_*` | backend | 10 / 900000 | login failure limiter |
| `SEED_*` | backend | data/processed | seed input overrides |
| `PYTHONIOENCODING` | model runs | utf-8 | **required on Windows** (emoji in script output) |
| `VITE_API_URL` | frontend/.env | http://localhost:3001 | API base for dev |

---

## 13. Deployment Topologies

1. **Local dev** — Postgres (local or Neon) + `backend npm run dev` (:3001) + `frontend npm run dev` (:5173). Requires seeded DB or the Mizoram fixture.
2. **Production-ish** — `backend npm run build && npm start` + frontend static build served by any static host (Vite preview / CDN); `NODE_ENV=production` for immutable bundles + secret enforcement. Neon region choice matters: ap-southeast-1 (Singapore) cuts cold-query latency ~4× vs us-east-2.
3. **Scale notes** — the app is designed for a single small instance: in-memory cache + static bundles make read-heavy loads cheap; the DB is only needed for detail lookups. The response cache and rate limiter are single-instance state by design.

---

## 14. Known Bottlenecks & Honest Limits

- **Spatial generalization**: susceptibility LOSO AUC (~0.696) is far below random CV (~0.962) — genuine spatial autocorrelation; reported openly rather than hidden (see design.md §5).
- **Data coverage**: 62.9% of villages carry `low_confidence` (missing land cover mainly). Fixes (ESRI/NRSC land cover, Copernicus DEM) are scoped but not yet applied.
- **First-load cost**: compact bundle ~11 MB (~1.5 MB gzipped); rendering 43,996 table rows occupies the main thread briefly — table is not yet virtualized.
- **Read API stays public** (auth gates the UI only) and cache/rate-limit state is single-instance.
