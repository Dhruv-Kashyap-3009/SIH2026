# Changelog

All notable changes to the NE India Hazard Red Zone Platform.

## [Unreleased] — Model Improvement Pass (Tasks 1-6)

### Task 1: Close Spatial Generalization Gap
- **Hyperparameter search**: Grid search over max_depth (4,6), n_estimators (300,500), learning_rate (0.05), optimized for LOSO AUC. Best: max_depth=4, n_estimators=500.
- **LOSO AUC improved**: 0.685 → 0.696 (+1.1%). Still a large gap vs random CV (0.962) — reveals fundamental spatial autocorrelation in features.
- **Interaction features (slope×rainfall, TWI proxy) HURT**: LOSO decreased by -0.005. Dropped from feature set. Physical interactions don't help when single features already capture the signal.
- **LogReg baseline**: LOSO AUC=0.573 (much worse than XGBoost's 0.696). Extra model complexity IS warranted for spatial transfer.
- **Per-state LOSO**: Worst states: Tripura (0.569), Arunachal Pradesh (0.603). Best: Meghalaya (0.807), Nagaland (0.769).
- **Output**: models/hyperparam_search_spatial.csv, models/spatial_cv_scores.json (with loso_per_state)

### Task 5: Threshold Optimization
- **Cost-optimal threshold**: 0.38 (vs current 0.7). With FN cost weight=5x, lowering threshold dramatically reduces missed-risk cost (90.4% reduction).
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
