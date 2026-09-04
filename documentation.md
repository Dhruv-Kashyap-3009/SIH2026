# VYOMA — Technical & Operations Documentation

**NE India Hazard Red Zone Platform** · SIH 2026 Problem Statement #26191 · Ministry of Home Affairs / NDRF

This is the *operations manual*: prerequisites, environment setup, how to run every piece (model pipeline **and** the web app), what each file is, and how to troubleshoot. For *why* the design is what it is, see [`design.md`](design.md); for the layer-by-layer structure and data flows, see [`architecture.md`](architecture.md); for headline numbers and quick start, see [`README.md`](README.md).

---

## 1. System overview

| Piece | What it is | Where | Runs on |
|---|---|---|---|
| Model pipeline | ~30 Python scripts: features → labels → 2 XGBoost models → predictions → decision modules → exports | `scripts/` | Python 3.10+ |
| Data artifacts | feature matrix, prediction master, relocation plan, exports, static bundles | `data/processed/` | — |
| Model artifacts | weights (gitignored) + diagnostics (tracked) | `models/` | — |
| Backend API | Express + TypeScript + Prisma, serves villages/sites/dashboard/auth/refresh | `backend/` | Node 18+, Postgres (Neon) |
| Frontend | React 18 + Vite + Tailwind + MapLibre GL dashboard | `frontend/` | Node 18+ |
| Tests | 6 Python suites (pipeline, readme-consistency, VYOMA schema + behavior, ground truth) | `tests/` | pytest-style, plain `python` |

**Key current numbers** (Sep 4, 2026 run, 43,996 villages): RED **20,129** · ORANGE **12,496** · GREEN **11,371**; priorities IMMEDIATE 16,030 · SHORT_TERM 4,099 · MEDIUM_TERM 12,496 · MONITOR 11,371; relocation sources 29,105 → **8,431 assigned** (mean 35.3 km); relocation sites register **10,603** (406 `is_ideal`); novel red zones **131**; susceptibility CV: random 0.962 · LOSO 0.696 · LODO 0.770.

> **The rule that governs everything downstream:** all public risk output = the **leakage-free susceptibility model**; RED ≥ 0.9 · ORANGE 0.4–0.9 · GREEN < 0.4 on `susceptibility_score`; `relocation_timeline` uses the same score and the same cutoffs so tier never contradicts zone.

---

## 2. Prerequisites & environment

### 2.1 Repository

```bash
git clone https://github.com/Dhruv-Kashyap-3009/SIH2026.git
cd SIH2026
```

### 2.2 Python (model pipeline)

```bash
pip install -r requirements.txt   # numpy pandas xgboost scikit-learn shap rasterio
                                  # geopandas fiona pyproj osmium netcdf4 xarray
                                  # scipy networkx matplotlib seaborn openpyxl
```

Windows note: **always run Python with `PYTHONIOENCODING=utf-8`** — script output contains emoji and Windows' default cp1252 console will raise `UnicodeEncodeError`:

```bash
PYTHONIOENCODING=utf-8 python scripts/predict.py
```

### 2.3 Node + Postgres (web app)

- Node 18+, npm.
- A Postgres database — the project targets **Neon**; the demo account uses `backend/.env`'s `DATABASE_URL` (Singapore region `ap-southeast-1` recommended for latency from India — see §4.6).

```bash
cd backend
cp .env.example .env        # then edit DATABASE_URL (+ AUTH_SECRET)
npm install
```

Frontend:

```bash
cd frontend
npm install
# optional: cp .env.example .env   # VITE_API_URL defaults to http://localhost:3001
```

### 2.4 Environment variables

| Var | File | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | `backend/.env` | — | Postgres/Neon connection string (**required**) |
| `AUTH_SECRET` | `backend/.env` | dev fallback | session-token signing; **required when `NODE_ENV=production`** |
| `PORT` | backend | 3001 | API port. ⚠️ Shells that export `PORT=0` must start with `PORT=3001` |
| `STATIC_DATA_DIR` | backend | `../data/processed/static` | where the versioned bundles + `latest.json` live |
| `CACHE_MAX_AGE_SECONDS` | backend | 300 | Tier-1 GET-cache TTL |
| `LOGIN_RATE_MAX_ATTEMPTS` / `LOGIN_RATE_WINDOW_MS` | backend | 10 / 900000 | login-failure limiter |
| `SEED_VILLAGES_FILE` / `SEED_SITES_FILE` / `SEED_DATA_DIR` | backend | `data/processed` | seed input overrides |
| `VITE_API_URL` | `frontend/.env` | `http://localhost:3001` | API base the browser calls |
| `PYTHONIOENCODING` | shell | — | utf-8 on Windows (model runs) |

---

## 3. Quick start (web app)

There are two paths; the README's "Download and Run" section mirrors this.

### Path A — Demo with the bundled Mizoram fixture (no big data)

```bash
# Terminal 1 — backend (needs backend/.env with a real DATABASE_URL)
cd backend
npm install
npx prisma db push          # create tables (no migration files needed — push schema)
npm run seed                # loads the small Mizoram fixture (830 villages / 32 sites)
PORT=3001 npm run dev       # API on http://localhost:3001
```

```bash
# Terminal 2 — frontend
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

Open **http://localhost:5173** → login with **`admin@vyoma.in` / `admin123`** → `/dashboard`.

> The Mizoram fixture (`data/processed/vyoma_export_mizoram.json`) is git-tracked so a fresh clone can demo the full app without any datasets. The fixture is loadable with `SEED_VILLAGES_FILE=vyoma_export_mizoram.json SEED_SITES_FILE=vyoma_sites_export_mizoram.json npm run seed`.

### Path B — Full 43,996-village dataset

Requires the exports to exist. They are gitignored, so on a fresh clone either regenerate them (§5.4/§7) or restore them, then:

```bash
cd backend && npm run seed   # loads vyoma_export_all_states.json (43,996) + sites (10,603)
```

After seeding, both demo accounts work the same. The dashboard, map, analytics then show the full national dataset.

---

## 4. Web application — operations

### 4.1 Backend routes (API contract)

| Method + path | Purpose |
|---|---|
| `GET /api/health` | liveness probe |
| `GET /api/villages` | list; filters `?state= ?district= ?risk_level= ?relocation_priority=`; `?compact=1` slim projection; `?limit= ?offset=` pagination (sorted by risk desc). **Never exposes raw model columns** |
| `GET /api/villages/districts?state=` | distinct districts (must be registered **before** `/:id`) |
| `GET /api/villages/:id` | full village record (18 export fields, incl. `top_factors`) |
| `GET /api/sites` · `GET /api/sites/:id` | relocation-site register (same filters/pagination) |
| `GET /api/dashboard` | headline aggregates (risk/priority counts, population at risk, low-confidence count, sites, `predicted_at`, `model_version`) |
| `POST /api/auth/login` · `GET /api/auth/me` · `POST /api/auth/logout` | session auth |
| `POST /api/admin/refresh` · `GET /api/admin/refresh/status` | run / poll the model-refresh chain (§4.5) |
| `GET /static/latest.json` + bundles | Tier-3 static data |

Request pipeline (order matters): `cors → express.json → compression (gzip) → Tier-1 GET cache → static files → routers → 404`. Successful GET responses carry `X-Cache: HIT|MISS`. `/api/health`, `/api/auth/*`, `/api/admin/*` bypass the cache.

### 4.2 Database (Prisma models)

Three tables (see `backend/prisma/schema.prisma`):

- **Village** — `village_id` (PK = habitation_id), name, district, state, lat/lon, population, `risk_score`, `risk_level`, `relocation_priority`, `vulnerability_multiplier`, `top_factors` (Json), `low_confidence`, `recommended_site_id?`/`_distance_km?`/`_fit?`, `prediction_timestamp`, `model_version`; indexes on district/state/risk_level/relocation_priority.
- **RelocationSite** — `site_id` (PK), name, district, state, lat/lon, `suitability_score`, `total_capacity`, `occupied`, `available`, `is_ideal`, `infrastructure` (Json: 6 booleans — water_supply, electricity, road_access, shelter, medical_facility, sanitation).
- **User** — cuid id, unique email, name, scrypt `passwordHash`, role, createdAt.

Schema changes: run `npx prisma db push` (dev; no migration files in the repo) or `npx prisma migrate dev` if you adopt migrations. The seed **clears and rebuilds** Village + RelocationSite — it is a snapshot loader, not an upsert patcher.

### 4.3 Users & auth

Create a user:

```bash
cd backend
npm run create-user -- admin@vyoma.in 'aStrongPassword' 'Admin'   # or: npx tsx src/scripts/create-user.ts ...
```

Demo account (documented in README): **`admin@vyoma.in` / `admin123`**. Reset a password by re-running `create-user` with the same email.

Auth mechanics: passwords hashed with **scrypt** (`salt:hash`); sessions are **HMAC-signed stateless tokens** (payload.signature). The frontend stores the token in `localStorage` (`vyoma_auth`), validates it via `/api/auth/me` at startup, and only a definitive **401** clears the session (network/DB blips keep you signed in optimistically). Login failures are rate-limited (HTTP 429 + `Retry-After`). Logout shows a confirmation dialog in the UI.

### 4.4 Frontend routes

| Path | Page | Data |
|---|---|---|
| `/` | login | — |
| `/dashboard` | national Overview: stat cards, hazard map, critical habitations, priority & capacity summaries | compact bundle (client-aggregated) |
| `/map` | full-screen hazard map | compact bundle |
| `/villages` | all-villages table (filter/sort) | compact bundle |
| `/villages/:id` | village detail: risk, top factors, relocation plan, confidence badge | `GET /api/villages/:id` |
| `/priority` | relocation kanban (IMMEDIATE → ROUTINE) | compact bundle |
| `/sites` · `/capacity` | relocation sites / capacity view | sites bundle |
| `/analytics` | 6 charts (lazy-loads full records once — needs `top_factors`) | `GET /api/villages` full |
| `/help` | user guide with live stat cards | `/api/dashboard` |
| `/logout`, `*` | sign-out, 404 | — |

Data flow: `villagesStore` / `sitesStore` (TanStack Query, `staleTime/gcTime: Infinity`) fetch the compact/sites bundles once per session; state/district filters are applied **client-side** via `SelectionContext`; the detail page makes one API call; Analytics fetches full records once. Shared `BrandedLoader` (spinner + shimmer skeletons) covers the heavy first loads.

### 4.5 The refresh chain (top-bar sync button)

The button runs a **deterministic re-run** of the fixed pipeline — it does **not** retrain XGBoost. Orchestrated by `backend/src/lib/refreshJob.ts` (single in-flight job; UI polls `/api/admin/refresh/status`):

1. `python scripts/refresh_predictions.py` — re-run BOTH models over all 43,996 rows (in place on `prediction_output.csv`), stamp a **new `predicted_at`**
2. `python scripts/generate_relocation_sites.py` — site register from fresh zones + capacity pool
3. `python scripts/relocation_planner.py --capacity data/processed/relocation_capacity_pool.csv` — re-solve assignments
4. `python scripts/generate_relocation_sites.py` — fold occupancy into the register
5. `python scripts/generate_vyoma_export.py` (all states) and `--state Mizoram` (fixture)
6. `python scripts/generate_frontend_static.py` — new run-tagged bundles + `latest.json`
7. `npx tsx src/seed.ts` (from `backend/`) — reload Postgres
8. clear the response cache

After a successful run the `Predicted <date> · v1.1-susceptibility` chip in the top bar updates from the bundle metadata, and new versioned filenames force browsers off stale `immutable`-cached bundles.

**When to refresh:** after any model/data change (new labels, re-trained model, threshold change) — run the model steps by hand, then click refresh (or run step 7+8 manually). Retraining (`train_model.py`, `train_susceptibility_model.py`) needs the raw data and is always a manual step.

### 4.6 Performance notes & Neon

- The compact village bundle (~11 MB, ~1.5 MB gzipped) is served as a static immutable file; gzip + HTTP caching + client-side filtering is why 43,996 villages render without jank on repeat visits.
- Server-side, the Tier-1 cache turns a ~40 s cold query on remote Neon into ~0.05 s (TTL 300 s, 200 entries, 16 MB cap).
- The `/analytics` page needs full records (for `top_factors`) — the first fetch is ~41 MB; the branded loader explains this on first load.
- **Neon region:** use `ap-southeast-1` (Singapore). The project moved from `us-east-2`; the pooler endpoint (`-pooler.`) is for serverless; direct endpoints work too — keep `sslmode=require`.

---

## 5. Model pipeline — running everything

### 5.1 Script map (in execution order)

| Phase | Script | Produces |
|---|---|---|
| 0 — coordinates | `join_census_shrug.py` | `ne_india_census_with_coords.csv` (43,996 matched) |
| 1 — features | `extract_raster_features.py` | elevation, slope (meter-corrected), roughness, land cover |
| | `extract_vector_features.py` | OSM road/river/hospital/school distances + road density; GSI proximity/density (historical only) |
| | `extract_flood_features.py` | DFO flood distances/density + `is_lowland`/`near_major_river` |
| | `extract_interaction_features.py` | `slope_x_rainfall`, `twi_proxy` (columns kept; **not in the trained model**) |
| | `combine_features.py` | `ne_india_village_features.csv` (43,996 × ~450) + slim model-input copy |
| 2 — labels | `create_labels.py` · `update_labels_flood.py` | ground-truth `high_risk` + `risk_zone` label |
| | `create_soft_labels.py` | distance-decay soft labels (**diagnostic only**) |
| 3 — models | `train_model.py` | historical XGBoost (`red_zone_xgboost.json`) |
| | `spatial_cv.py` | reusable LOSO / LODO / random CV |
| | `train_susceptibility_model.py` | susceptibility XGBoost (`susceptibility_xgboost.json`) — tuned on LOSO |
| | `calibrate_model.py` | ECE report (calibration **not** applied) |
| | `optimize_thresholds.py` | cost-optimal threshold + quantile zones (research columns) |
| | `uncertainty_quantification.py` | `prediction_uncertainty` / `prediction_std` (bootstrap) |
| 4 — predict | `predict.py` | scores, zones, timeline, SHAP top factors → `prediction_output.csv` |
| | `refresh_predictions.py` | **in-place** re-run of both models over the master (keeps downstream columns) |
| | `refresh_rainfall.py` | demo hook: re-score from changed rainfall (historical model) |
| 4b — modules | `social_vulnerability.py` · `hazard_decomposition.py` | vulnerability columns; landslide/flood scores + `recommended_action` |
| | `carrying_capacity.py` | `carrying_capacity.csv` (14,109 measured) + assumptions JSON |
| | `generate_relocation_sites.py` | site register + **safe pool** (canonical-GREEN) |
| | `relocation_planner.py` | `relocation_plan.csv` (assignments) |
| | `generate_relocation_sites.py` (again) | fold occupancy into the register |
| 5 — exports | `generate_vyoma_export.py` | `vyoma_export_all_states.json` + sites export (+ `--state Mizoram` fixture) |
| | `generate_frontend_static.py` | Tier-3 versioned bundles + `latest.json` into `data/processed/static/` |

### 5.2 Full end-to-end run (needs `data/raw/`)

```bash
# Phase 0 + 1
python scripts/join_census_shrug.py
python scripts/extract_raster_features.py
python scripts/extract_vector_features.py
python scripts/extract_flood_features.py
python scripts/combine_features.py
python scripts/extract_interaction_features.py      # optional experiments
# Phase 2
python scripts/create_labels.py
python scripts/update_labels_flood.py
python scripts/create_soft_labels.py                # diagnostic
# Phase 3 (train — slow; needs raw data + GPU optional)
python scripts/train_model.py
python scripts/train_susceptibility_model.py
python scripts/calibrate_model.py
python scripts/optimize_thresholds.py
python scripts/uncertainty_quantification.py
# Phase 4
python scripts/predict.py
python scripts/social_vulnerability.py
python scripts/hazard_decomposition.py
python scripts/carrying_capacity.py
# Relocation (safe pool order matters)
python scripts/generate_relocation_sites.py
python scripts/relocation_planner.py --capacity data/processed/relocation_capacity_pool.csv
python scripts/generate_relocation_sites.py
# Phase 5 exports
python scripts/generate_vyoma_export.py --state Mizoram
python scripts/generate_vyoma_export.py
python scripts/generate_frontend_static.py
```

Then load the DB and restart the backend (§3). **If you skipped training**, the gitignored model weights may be absent on a fresh clone — the refresh chain and `predict.py` need them; regenerate with the training scripts or restore the files.

### 5.3 predict.py CLI

```bash
python scripts/predict.py                          # predict all villages (writes prediction_output.csv)
python scripts/predict.py --state Mizoram          # filter by state
python scripts/predict.py --village "Manikpur"     # search a specific village
python scripts/predict.py --top-n 50               # top 50 highest risk
python scripts/predict.py --output out.csv         # custom output path
python scripts/relocation_planner.py --village <id> --capacity data/processed/relocation_capacity_pool.csv  # inspect one plan
python scripts/relocation_planner.py --max-distance 75 --capacity ...  # custom radius (km)
```

### 5.4 Regenerating a single piece (no full re-run)

- Zones/timeline changed? `refresh_predictions.py` re-scores the master in place.
- Sites stale? `generate_relocation_sites.py`.
- Assignments stale? re-run the planner with `--capacity`, then regenerate sites to fold occupancy.
- Exports/bundles stale? `generate_vyoma_export.py` + `generate_frontend_static.py`, then `npm run seed` in `backend/`.
- Tests fail on numbers? You changed upstream data — re-run the suite (§6) and update `test_readme_consistency.py` constants *from the data*, never by hand-guessing.

---

## 6. Tests & validation

All suites run from the repo root with `PYTHONIOENCODING=utf-8 python …`:

| Command | What it verifies | Green state |
|---|---|---|
| `tests/test_pipeline.py` | 293 regression assertions across 18+ categories (features, zones, CV, tie-breaks, capacity bounds, zone×tier diagonal, export columns, canonical top_factors, …) | 293/293 |
| `tests/test_readme_consistency.py` | README headline numbers match the actual data (per-state RED sums = headline RED, etc.) | 7/7 |
| `tests/behavioral_vyoma.py` | 41 end-to-end checks of the VYOMA export contract | 41/41 |
| `tests/validate_vyoma_export.py` | 22 schema-contract checks per export file (field set, types, ISO timestamps, vocabularies, no dangling site refs, capacity bookkeeping) | PASS |
| `tests/validate_predictions.py` | domain-knowledge checks (RED villages closer to landslides, wetter, denser) | PASS (notes only) |
| `tests/validate_real_world.py` | ground-truth checks (EM-DAT detection, hill-vs-plains RED ordering) | PASS (3 documented pre-existing warnings) |

Run the whole model-side suite:

```bash
PYTHONIOENCODING=utf-8 python tests/test_pipeline.py
PYTHONIOENCODING=utf-8 python tests/test_readme_consistency.py
PYTHONIOENCODING=utf-8 python tests/validate_vyoma_export.py
PYTHONIOENCODING=utf-8 python tests/behavioral_vyoma.py
PYTHONIOENCODING=utf-8 python tests/validate_predictions.py
PYTHONIOENCODING=utf-8 python tests/validate_real_world.py
```

Frontend/backend checks: `cd frontend && npm run build` (production build compiles), backend `npm run build` + `npm start`; typecheck via the build scripts.

---

## 7. Data files — what lives where

### 7.1 `data/raw/` (gitignored, ~5.6 GB; download per README "Datasets Used")

```
census/ (7 state xlsx, ~111 MB) · shrug/ (village gpkg + coords) · srtm/ (~2.4 GB tifs)
imd_rainfall/ (5 netcdf) · gsi_landslide/ (shapefile) · emdat/ (xlsx)
worldcover/ (15 tifs, ~1.1 GB) · openstreetmap/ (NE pbf ~105 MB) · floods/ (DFO)
```

### 7.2 `data/processed/` (generated; gitignored except fixtures + assumptions JSONs)

| File | Contents |
|---|---|
| `ne_india_village_features.csv` | full feature matrix 43,996 × ~450 (raw Census + engineered) — read by extraction/combine scripts and downstream modules that need raw Census columns |
| `ne_india_village_features_model_input.csv` | slim: habitation_id, coords, state/district + the 59 susceptibility features (declared model-input space) |
| `prediction_output.csv` | **canonical master** — 43,996 × 463: both models' scores/zones, timeline, vulnerability, hazard decomposition, capacity refs, exports read from here |
| `carrying_capacity.csv` | 14,109 measured GREEN candidates + `estimated_absorbable_population` |
| `carrying_capacity_assumptions.json` / `social_vulnerability_assumptions.json` | methodology docs (every coefficient) — tracked |
| `relocation_capacity_pool.csv` | 10,603 canonical-GREEN safe sites (planner input) |
| `relocation_plan.csv` | 29,105 source rows → 8,431 assignments (single best per village, ≤50 km) |
| `relocation_sites.csv` / `.json` | 10,603-site register with capacity bookkeeping + `is_ideal` (406) |
| `vyoma_export_all_states.json` / `vyoma_sites_export_all_states.json` | full-state frontend exports (43,996 villages × 18 fields / 10,603 sites × 12 fields) |
| `vyoma_export_mizoram.json` / `vyoma_sites_export_mizoram.json` | **git-tracked** demo fixture (830 villages / 32 sites) |
| `static/` | Tier-3 bundles: `vyoma_compact_<version>-<tag>.json`, `vyoma_sites_<version>-<tag>.json`, `latest.json` manifest |

### 7.3 `models/` (weights gitignored; diagnostics tracked)

Weights: `red_zone_xgboost.json`, `susceptibility_xgboost.json`. Tracked diagnostics: `model_metadata.json`, `susceptibility_model_metadata.json`, `features.json`, `susceptibility_features.json`, `cv_scores.csv`, `feature_importance.csv`, `susceptibility_feature_importance.csv`, `spatial_cv_scores.json` (LOSO/LODO/random + per-state + logreg baseline), `hyperparam_search_spatial.csv`, `shap_state_consistency.csv`, `threshold_metadata.json`, `threshold_cost_curve.csv`, `calibration_metadata.json` + png, `uncertainty_metadata.json`, `hazard_decomposition_validation.json`, eval/shap pngs.

---

## 8. Dataset & label reference (condensed)

| Dataset | Role | Key facts / caveats |
|---|---|---|
| Census 2011 Village Directory | demographics + infra backbone | ~396 cols/village, 44,537 villages; no coordinates (join with SHRUG); Sikkim is PDF-only → excluded (462) |
| SHRUG village polygons | coordinates | 98.8% join → 43,996 on the composite Census key; centroids computed in UTM 46N |
| SRTM DEM 30 m | elevation/slope/roughness | ~500 villages in N-Arunachal lack tiles → part of `low_confidence`; slope computed in **meter** space (bug fixed, see design.md §8.1) |
| IMD rainfall 0.25°, 2020–24 | rainfall features | 99.1% coverage, vectorized extraction |
| GSI landslides | label + historical features | 10,408 NE points; 10 km buffer = positive label |
| EM-DAT | label + ground truth | 124 NE disasters; 15 km buffer; 105/124 geocoded by district/state |
| ESA WorldCover 10 m | land-cover class | only ~60% village coverage → the main `low_confidence` driver (backfill options documented) |
| OSM | distances/density | roads, rivers, hospitals, schools via cKDTree |
| DFO floods | flood label + historical features | 274 NE events 1985–2023 |

Labels: `high_risk = 1` if within 10 km GSI **or** 15 km EM-DAT **or** high-density DFO zone. All threshold comparisons use `>=` (ties → higher-risk class, conservative for disaster safety). Soft labels (`create_soft_labels.py`) are diagnostics only and block-listed from the model.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `python` script crashes with UnicodeEncodeError on Windows | prefix `PYTHONIOENCODING=utf-8` |
| Backend starts on a random port / nothing on :3001 | your shell exports `PORT=0` — start with `PORT=3001 npm run dev` |
| `P1001: Can't reach database server` | `DATABASE_URL` wrong / Neon paused — check `backend/.env`; `sslmode=require` |
| API works but login fails | wrong creds or rate-limited (10 fails/15 min → wait or restart); re-create user with `npm run create-user` |
| Server refuses to start in production | `AUTH_SECRET` unset — set it in `backend/.env` |
| Dashboard shows old numbers after refresh | hard-refresh the browser (new versioned bundle is fetched automatically; the *page* may hold an old one) |
| Seed is very slow on Neon | expected for full 43,996 rows (minutes); the fixture seed is fast. Bulk `createMany` 5,000/batch is used deliberately (per-row upserts were ~4 rows/s) |
| Stale data on a page | the Tier-1 cache holds GETs for 300 s — refresh clears it; or wait |
| `latest.json` 404 | `STATIC_DATA_DIR` wrong or `generate_frontend_static.py` not run for this data dir |
| Charts/table blank forever with spinner | first fetch is large (~11 MB compact / ~41 MB full for analytics); check network tab; the BrandedLoader explains the wait |
| `validate_real_world` warnings | documented pre-existing data facts (e.g., Tinsukia district RED share below an assumed 30% floor) — read the validator header before "fixing" |
| README numbers ≠ data | run `test_readme_consistency.py`; if it fails, regenerate exports/predictions and update constants from the data |

---

## 10. Known limitations (honest list)

1. **Spatial generalization gap** — susceptibility LOSO 0.696 vs random 0.962; structural spatial autocorrelation, reported openly, per-state in `spatial_cv_scores.json`.
2. **Data coverage** — 62.9% of villages carry `low_confidence` (mainly WorldCover gaps); backfill (ESRI/NRSC LULC, Copernicus GLO-30 DEM) scoped but not applied.
3. **Census 2011 is 15 years old** — population figures stale; spatial features are current (2020–2024).
4. **~70% of high-priority sources unassigned** in the relocation plan — capacity + 50 km range limits; explicitly flagged `no feasible relocation site within range`, never silently dropped.
5. **30 m SRTM** may miss micro-terrain — acceptable at village analysis scale.
6. **Single-instance design** — response cache and login limiter are in-memory; fine for a demo/small deployment, would need shared storage to scale horizontally.
7. **Read API + static data are public by design** — auth gates the UI only (documented decision, design.md §11).

---

*Maintained for SIH 2026 Problem Statement #26191 — Ministry of Home Affairs / NDRF. Companion documents: [`README.md`](README.md) (quick start), [`design.md`](design.md) (decisions & rationale), [`architecture.md`](architecture.md) (structure & data flow), [`CHANGELOG.md`](CHANGELOG.md) (dated history).*
