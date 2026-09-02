# Changelog

All notable changes to the NE India Hazard Red Zone Platform.

## [Unreleased] — Phase 1-5 + Bug Fixes

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
