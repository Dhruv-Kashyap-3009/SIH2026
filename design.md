# Design Document — NE India Hazard Red Zone Platform (VYOMA)

**Intelligent Identification of Hazard-Based Red Zones, Carrying Capacity Assessment, and Immediate Relocation Needs for Vulnerable Habitations**

**Problem Statement ID:** 26191 · **Organization:** Ministry of Home Affairs / NDRF · **SIH 2026**

This document records the *decisions* behind the system — the options considered, the trade-offs accepted, and the rationale a reviewer/judge can probe. Where a choice is a simplifying assumption rather than an empirical result, that is stated explicitly.

Companion docs: [`documentation.md`](documentation.md) (how to operate everything), [`architecture.md`](architecture.md) (system structure & data flow), [`README.md`](README.md) (quick start + headline numbers).

> **Currency note.** Every number below is quoted from the current canonical data (`prediction_output.csv`, `relocation_plan.csv`, `relocation_sites.json`, `models/*`) as of the Sep 4, 2026 pipeline run — 43,996 villages, RED ≥ 0.9 / ORANGE 0.4–0.9 / GREEN < 0.4, susceptibility model canonical. When a number changed across versions the before/after is shown so a judge can see the history; the full history is in `CHANGELOG.md`.

---

## 1. Problem framing and design goals

### 1.1 The problem

The NDRF must decide where 44,000+ habitations in 7 North-Eastern states are too hazardous to keep people, which villages can safely absorb relocated populations, and who should move first. Two hard realities shape the design:

1. **Disaster inventories are incomplete.** A village that has *not yet* been hit can still be physically susceptible — the decision-relevant signal is terrain + rainfall + exposure, not just "was there a past event nearby."
2. **Spatially correlated data inflates model scores.** Villages near past disasters share similar terrain; a model trained and validated on random splits can appear near-perfect while generalizing poorly to unseen districts/states.

### 1.2 Design goals (ranked)

| # | Goal | Why |
|---|------|-----|
| 1 | **Honest generalization metrics** | A ~0.999 AUC that collapses under spatial CV is worse than useless — it misleads deployment |
| 2 | **No label leakage** | Distance-to-past-event features trained against event-buffer labels are circular; the model must learn physics, not proximity |
| 3 | **Decision-ready outputs** | The export must tell the frontend exactly one thing per field: risk level, priority, per-hazard score, recommended action |
| 4 | **Actionable relocation math** | Who moves where, how far, and does the destination actually have capacity — with every coefficient defensible |
| 5 | **Explainability per village** | SHAP top-factors for every prediction so a district officer can see *why* |

### 1.3 Non-goals (deliberately out of scope)

- Real-time hazard *forecasting* (this is susceptibility/planning, not nowcasting). A rainfall-refresh hook (`refresh_rainfall.py`) demonstrates re-scoring, not forecasting.
- Sub-village modelling — the analysis unit is the Census village (44,000+ points), which is also the scale the NDRF operates at.

---

## 2. Two-model architecture — the core decision

### 2.1 The leakage problem, quantified

Labels are built from event buffers (GSI landslides within 10 km, EM-DAT disasters within 15 km, DFO flood density). The original single model included features derived from the *same* event sets — `dist_to_nearest_landslide_km`, densities, flood distances — producing random-CV AUC **0.9994**. That score is largely circular: the model was detecting "near a recorded past event" rather than genuine susceptibility.

### 2.2 Decision: keep both models, make the leakage-free one canonical

| Option considered | Verdict |
|-------------------|---------|
| Delete the historical model | Rejected — it is a useful *validation instrument* (does the system catch historically-confirmed zones?) |
| Delete the leakage features only | Done — but as a *second* model, so the comparison is visible |
| Ship one "union" score (RED if either model says RED) | Rejected — inflates RED count with no methodological story; instead the models serve different roles |

**Design:** two binary XGBoost models over the same `high_risk` label:

- **Historical model** (`models/red_zone_xgboost.json`, 66 features incl. 7 event-proximity features) — validates detection of historically confirmed hazard zones. Kept because its near-perfect score is itself the exhibit that motivates everything else.
- **Susceptibility model** (`models/susceptibility_xgboost.json`, 59 leakage-free features: terrain, rainfall, land cover, drainage geometry, Census infrastructure) — predicts physical susceptibility; **the canonical source of `risk_score`/`risk_level` in every public export and the UI**.

### 2.3 Novel red zones — the differentiator

The susceptibility model enables `is_novel_red_zone = TRUE` when a village is susceptibility-RED but **no** recorded landslide/flood/EM-DAT event lies within the standard buffer. These are villages current inventories have missed — the proactive-planning signal the problem statement rewards. **Current run: 131 of 20,129 RED villages (0.65%) are novel** (earlier runs reported 361/27,881 under the old 0.7 cutoff — the fraction fell as the RED bar rose, because novel villages tend to sit just above the threshold).

---

## 3. Spatial cross-validation — measuring generalization honestly

### 3.1 Why random CV lies

Random 5-fold CV on spatially autocorrelated data leaks *between folds*: a validation village shares a district (and its terrain/rainfall regime) with training villages. Random CV AUC for the susceptibility model is ~0.962; that is an upper bound, not a deployment estimate.

### 3.2 Decision: LOSO + LODO as the acceptance metric

- **Leave-One-State-Out (7 folds):** each fold trains on 6 states, validates on the held-out state — a Tripura village is never "remembered" by neighbours in a training fold.
- **Leave-One-District-Out (62 folds):** stricter local check.
- **Random 5-fold retained** purely for comparison, reported side by side so the gap is visible.

Results (susceptibility model): **LOSO 0.696, LODO 0.770, random 0.962** (tuning closed ~1.1%: 0.685 → 0.696). Worst per-state LOSO folds are Tripura (0.569) and Arunachal (0.603) — reported per-state in `models/spatial_cv_scores.json`, never averaged away.

### 3.3 Evaluation policy (binding)

- Hyperparameter search is scored on **mean LOSO AUC**, never random CV (`models/hyperparam_search_spatial.csv`).
- A feature/interaction is kept only if it improves LOSO/LODO — *random-CV-only gains are rejected and reported as such*.
- New model artifacts only overwrite the incumbent after beating it on spatial CV.

**Negative results are published** (§9): slope×rainfall and TWI-proxy interactions each *hurt* LOSO by ~−0.005 and were dropped from the model (columns remain in the matrix); the logistic-regression baseline (LOSO 0.573) documents that XGBoost's complexity buys real spatial transfer.

---

## 4. Labels — construction and conventions

### 4.1 Label composition

`high_risk = 1` if a village is within a 10 km GSI landslide buffer, a 15 km EM-DAT disaster buffer, or a high-density DFO flood zone. Buffer radii are fixed constants documented in `create_labels.py` comments; they define both the label and (for the historical model) the leakage features, so they are called out as the single most defensible-but-probable review target.

### 4.2 Training label vs. prediction zones — never conflated

The training label is a RED/ORANGE/GREEN *zone derived from event context*. Prediction zones come from **thresholding the model probability**. The two are different objects and the docs/tests keep them apart. A regression test asserts per-state predicted RED counts sum to the headline RED count — guarding against the stale-table class of bug found mid-development (two README tables disagreed by ~6,400 villages because one was never regenerated after a model change).

### 4.3 Tie-break convention

All threshold comparisons use `>=`, so a value exactly on a boundary resolves to the **higher-risk class** — the conservative direction for a disaster-safety product. Locked in by a regression test on Gandhia No.2 (risk 0.5741 vs. boundary 0.57408 → higher tier).

### 4.4 Soft labels — diagnostic only

`create_soft_labels.py` emits distance-decay risk scores (`exp(-distance/decay)`, decay 5 km landslide / 7 km flood) for label-quality analysis. Because they are derived from leakage features they are block-listed in `LEAKAGE_FEATURES` (assert-enforced in the trainer) and documented at the top of the script as **diagnostic only — never a model input**.

---

## 5. Threshold policy — what "RED" means in the field

### 5.1 The decision history (why the cutoffs are what they are today)

Zones are thresholds on the canonical `susceptibility_score`:

| Date | Rule | RED | ORANGE | GREEN |
|---|---|---|---|---|
| Original | RED ≥ 0.7 · ORANGE 0.4–0.7 · GREEN < 0.4 | 26,576 (60.4%) | 6,049 (13.7%) | 11,371 (25.8%) |
| **Current (Sep 4, 2026)** | **RED ≥ 0.9 · ORANGE 0.4–0.9 · GREEN < 0.4** | **20,129 (45.8%)** | **12,496 (28.4%)** | **11,371 (25.8%)** |

**Why RED moved from 0.7 to 0.9:** field review showed too many villages (60%+) labeled RED for the label to guide prioritization — "everything is red" is operationally the same as "nothing is red." Raising the bar to the top of the score scale makes RED mean *high confidence hazard*, ORANGE absorbs the mid band as a genuine "monitor and plan" tier, and GREEN is untouched (its cutoff was never in question). The scores and the model did not change — only the decision rule — and the whole chain (exports, sites, plan, bundles, DB, tests, README) was re-run from the corrected rule, not hand-edited.

### 5.2 Why RED is not cost-optimized in the shipped export

`optimize_thresholds.py` searches a threshold that minimizes an asymmetric cost (missing a hazard weighted 5× a false alarm) on **out-of-fold** predictions of the susceptibility model: cost-optimal **0.28** → 65.0% cost reduction. That answer is reported honestly as a *research* result in `models/threshold_metadata.json` and in the `predicted_risk_zone_fixed`/`predicted_risk_zone_quantile` side columns — **but it is not the shipped zone**, because (a) a 0.28 bar would flag 32,937 villages RED, recreating the "everything is red" problem, and (b) the fixed 0.9/0.4 contract is stable and interpretable for a frontend. Both variants remain exported so the team can compare before demo day.

An early in-sample version of this analysis claimed 90.4% cost reduction; it was retracted (measuring overfitting) and replaced with the out-of-fold 65.0% figure. A regression test forces the threshold-calibration column and the zone-assignment column to be the same model's scores.

### 5.3 Relocation priority is zone-aligned by construction

`relocation_timeline` (the shipped priority) is derived **from the same canonical score with the same cutoffs** as the displayed zone, so the tier can never contradict the color a user sees:

| Zone | Rule | Priority | Count |
|---|---|---|---|
| RED, urgent context | score ≥ 0.9 & high density/disaster context | ⚡ IMMEDIATE | 16,030 |
| RED, otherwise | score ≥ 0.9 | 📋 SHORT_TERM | 4,099 |
| ORANGE | 0.4 ≤ score < 0.9 | 📋 MEDIUM_TERM | 12,496 |
| GREEN | score < 0.4 | ✅ MONITOR | 11,371 |

The zone × tier cross-tab over 43,996 villages is a **perfect diagonal** (0 contradictions) and is regression-tested. This replaced an earlier design where the tier came from the *historical* model's score — which let an ORANGE village appear SHORT_TERM (a contradiction a user could find in two clicks). `priority_level` (HIGH/MEDIUM/LOW quantiles, internal-only) is a separate bucketing used to widen the relocation-source set; it is **not** the urgency scale (see §10).

---

## 6. Calibration & uncertainty

### 6.1 Calibration: measured, then *not* applied

Reliability analysis showed XGBoost probabilities already well-calibrated (**ECE 0.021**). Platt scaling (ECE 0.224) and isotonic regression (ECE 0.205) both *worsened* it, so no wrapper was applied. The decision to leave the model uncalibrated is itself documented, evidence-backed choice: "we tried two standard methods and both degraded a 0.021 ECE" is a defensible answer to a judge; "we didn't get around to it" would not be.

### 6.2 Uncertainty: bootstrap ensemble

7 models trained on bootstrap resamples → per-village `prediction_uncertainty` (variance across members, normalized to [0,1]); top quartile of variance marks statistically low-confidence villages (25%, concentrated in Tripura/Arunachal — the same states with the weakest LOSO folds, an internal consistency check between two independent uncertainty signals). This is **distinct** from the data-coverage `low_confidence` boolean (missing SRTM/WorldCover inputs, 27,668 villages = 62.9%, driven by the WorldCover tile gap) — the two are deliberately separate concepts and the UI now words the badge accordingly ("partial source data", not "limited training data").

---

## 7. Downstream decision modules

### 7.1 Carrying capacity (Phase 2)

For every low-risk village, four measurements (coefficients in `data/processed/carrying_capacity_assumptions.json`):

| Component | What it is | Key design choices |
|-----------|-----------|--------------------|
| `buildable_land_ha` | WorldCover non-forest/non-water/non-wetland/non-built-up land intersected with slope < 15° | 15° = standard engineering "developable" cutoff; runs on the **corrected** slope (see §8.1) |
| `water_capacity_margin` | Census water-source availability vs. per-capita demand | per-capita coefficient is a stated, adjustable assumption |
| `infra_headroom_score` | school/hospital/road access vs. current population | weights documented in the assumptions JSON |
| `estimated_absorbable_population` | people the village can absorb | bounded by buildable land; combines the above with explicit coefficients |

Measurements exist for **14,109** candidates (`carrying_capacity.csv`). Not every low-risk village is a usable destination: the planner pool restricts to villages that are canonical-**GREEN** (never relocate people into a village the platform itself flags RED/ORANGE — a safety rule added after adversarial review). Pool = **10,603 sites** (`relocation_capacity_pool.csv`), of which **406** are flagged `is_ideal` (carrying_capacity_score ≥ 0.8).

### 7.2 Relocation planning (Phase 3)

**Problem:** assign RED (+HIGH-priority ORANGE) villages to GREEN destinations, minimize travel, respect capacity, decrement capacity as assignments accumulate.

**Algorithm choice:** greedy nearest-available-capacity, benchmarked against `scipy.optimize.linprog` at 44K-village scale. The LP matched the greedy objective on samples but scaled far worse; greedy was selected for deterministic, auditable behaviour (it is also the fallback if the LP is ever too slow).

**Safety constraint:** destinations restricted to canonical-GREEN sites from the pool file (§7.1) — enforced by passing `--capacity data/processed/relocation_capacity_pool.csv` to the planner.

**Current output:** `relocation_plan.csv` — 29,105 high-priority sources considered → **8,431 assigned** (mean 35.3 km, ≤ 50 km CLI-configurable); the remaining 20,674 are explicitly flagged `no feasible relocation site within range` rather than silently dropped.

### 7.3 Social vulnerability (Phase 4)

`vulnerability_score` = weighted composite of risk (0.40), population (0.15), SC/ST exposure (0.10), access (0.15), evacuation difficulty (0.10), terrain (0.10). `priority_score` folds this in so **vulnerability, not raw population, drives prioritization** (weights in `social_vulnerability_assumptions.json`).

**Assumption flagged:** `relocation_sensitivity_flag` (LOW/MEDIUM/HIGH) uses tribal population % as a proxy for likely social resistance to relocation. This is a *documented simplifying proxy*, not a definitive sociological claim — the README and assumptions JSON say so explicitly.

### 7.4 Hazard decomposition (Phase 5)

`landslide_risk_score` / `flood_risk_score` are derived by summing SHAP over disjoint feature groups (landslide: elevation, slope, roughness, rainfall, `slope_x_rainfall`; flood: lowland flags, river distance, `twi_proxy`, rainfall). Action rule: RELOCATE when landslide SHAP ≥ 1.2 × flood SHAP (landslides are hard to mitigate in situ), MITIGATE when flood dominates (fortification feasible), MONITOR otherwise — `>=` tie-breaks resolve conservatively.

**Critically, decomposition runs on the susceptibility model** — a regression test pins its feature count to `susceptibility_features.json` so nobody can silently repoint it at the leaky model (an early version did, and it was fixed). Current output:

| Action | Villages | % | Reading |
|---|---|---|---|
| RELOCATE | 6,986 | 15.9% | landslide-dominant — move people |
| MITIGATE | 29,964 | 68.1% | flood-dominant — fortify/drain |
| MONITOR | 7,046 | 16.0% | low or mixed |

**Independence verified with numbers:** Pearson correlation(landslide, flood) = **−0.145** across all villages; within narrow overall-risk bins the (landslide − flood) spread stays ~0.10–0.14 — the per-hazard scores carry independent signal, not a repackaged overall score (evidence: `models/hazard_decomposition_validation.json`).

---

## 8. Data-quality engineering

### 8.1 The slope bug (fixed, documented)

An early extraction computed slope as `arctan(√(dx²+dy²))` with the gradient over **degree** spacing while elevation was in **meters** — collapsing the horizontal run and pushing ~95% of villages above 15° with a median of 89.99°. Re-extraction with a meter-projected pixel size (`pixel_degrees × 111320 × cos(lat)`) yields physically plausible values (median 4.06°, max < 80°), sanity-verified on known terrain (Mizoram/Meghalaya hills steep; Assam valley flat). The fix propagated through the carrying-capacity slope<15° filter and changed SHAP rankings. Corrupted-snapshot exports were deleted, never "restored".

### 8.2 Coverage gaps → honest flags

- SRTM tile gaps in northern Arunachal (~500 villages) and WorldCover tile gaps (~60% of villages) mean missing model inputs are **flagged** (`low_confidence = True`, 27,668 villages) instead of silently imputed; median fill is applied only inside training where a model requires it. Backfill options (ESRI/NRSC land cover, Copernicus GLO-30 DEM) are scoped in the README's limitations but not yet applied.

---

## 9. Negative results register

| Experiment | Hypothesis | Outcome | Decision |
|-----------|-----------|---------|----------|
| slope×rainfall interaction | adds landslide-trigger signal | −0.005 LOSO AUC | Dropped from model |
| TWI-proxy interaction | adds flood signal | −0.005 LOSO AUC | Dropped from model |
| Platt scaling | lower ECE | ECE 0.021 → 0.224 | Not applied |
| Isotonic regression | lower ECE | ECE 0.021 → 0.205 | Not applied |
| Logistic regression baseline | comparable spatial transfer | LOSO 0.573 vs XGB 0.696 | XGBoost kept |
| In-sample threshold optimization | fast cost estimate | overstates gains (90.4%) | Retracted; out-of-fold 65.0% adopted |
| Union score (RED if either model says RED) | single headline count | no methodological story | Rejected (two-model design) |
| Priority tier from historical score | reuse existing field | ORANGE could look SHORT_TERM | Replaced — zone-aligned tier |

Keeping a visible negative-results register is itself a design decision: it pre-empts the judge question "did you try X?" with evidence, and it prevents silently reverting to random-CV-tuned choices later.

---

## 10. Interface design — what the frontend sees

`scripts/generate_vyoma_export.py` is the **single source of truth for what VYOMA sees**: exactly **18 canonical fields** per village, zero raw Census columns, zero alternate zone/score variants. The contract is enforced by a schema validator (22 checks/file) + an end-to-end behavioral suite (41 checks) every run.

Key contracts (the decisions VYOMA's schema questions resolved — see CHANGELOG for the audit trail):

- `village_id` = `habitation_id` — the stable Census/SHRUG composite `{state}-{district}-{subdistrict}-{village}` (unique 43,996/43,996, deterministic across re-runs).
- `risk_level` / `risk_score` ← **susceptibility model** (canonical). The six zone/score variants that existed in the raw CSV were audited and exactly two were chosen for the export.
- `relocation_priority` ← `relocation_timeline` (the 4 verified action tiers above — zone-aligned). `priority_level` (HIGH/MEDIUM/LOW quantiles) is **internal-only**: it widens the relocation source set and must not surface as the urgency scale.
- `recommended_site_id` (+ `_distance_km`, `_fit`) ← the relocation plan; **null** when no feasible site exists (the frontend handles null).
- `vulnerability_multiplier` ← `vulnerability_score`.
- `top_factors` passed through as the **susceptibility model's** SHAP JSON (top-5 contributors with value/impact) — the explanation always matches the canonical `risk_level` it accompanies (a regression guard keeps leaky-feature names out of this column; see CHANGELOG 2026-09-04).
- `low_confidence` boolean passed through.
- `prediction_timestamp` ISO-8601; `model_version` = `v1.1-susceptibility` (marks the export as susceptibility-based even though the model file hash is recorded in the master CSV).

Relocation sites are a second, separately validated array/file with 12 fields (`site_id` … `available`, `is_ideal`, `infrastructure` with 6 booleans derived from Census "Status A(1)/NA(2)" columns — `A(1)` → true, missing → false).

**A note on honesty to teammates:** the audit that produced these answers found and fixed real inconsistencies (stale zone tables, an in-sample threshold figure, a priority field that contradicted zones, a "236 ideal sites" claim with no code behind it — replaced by the code-derived 406 `is_ideal` register). The export exists so VYOMA never has to guess again.

---

## 11. Web-application design decisions

The platform ships with a full web app (`frontend/` React, `backend/` Express+Prisma). Product-layer decisions, and why:

1. **`/` is the login page; `/dashboard` is the dashboard.** Browsing to the site lands on login; post-login goes to `/dashboard`. All data pages sit behind an auth gate.
2. **Auth gates the UI, not the read API.** Sessions are HMAC-signed stateless tokens with scrypt-hashed passwords (Node `crypto` only — zero extra deps); rate-limited login (10 failures / 15 min). The read API + static data stay public by design (public government data; keeps the performance path dependency-free). Demo account `admin@vyoma.in / admin123`.
3. **The browser never talks to the model.** The Python pipeline writes static JSON; a seed step loads it into Postgres; the API + pre-built bundles serve it. Re-running the model = re-running the chain → re-exporting → re-seeding. This boundary is what makes the app fast and the model reproducible.
4. **Three performance tiers, all kept:** Tier 1 = server response cache (cold 44k-row API call ~40 s on remote Neon → 0.05 s cached, TTL 300 s); Tier 2 = fetch the compact village list once at startup and filter state/district **client-side** (region switches are instant, zero DB round trips); Tier 3 = serve the compact JSON as **versioned immutable static files** with a `latest.json` pointer, so even the first page load skips the database. The run tag in the filename embeds `predicted_at`, so browsers holding an old `immutable`-cached bundle automatically fetch the new one after a model run.
5. **The sync/refresh button is an honest orchestration**: it deterministically re-runs the fixed pipeline steps (re-predict → re-plan → re-export → re-bundle → re-seed → clear cache) and updates the `Predicted <date> · v1.1-susceptibility` chip. It deliberately does **not** retrain XGBoost (training needs the 5.6 GB raw data and is a manual step by design) — documented in the UI and README so nobody believes the button "trains the model".
6. **Vocabulary translation at the boundary:** model CSVs say `SHORT_TERM / MEDIUM_TERM / MONITOR`; the DB/UI speak `SHORT-TERM / MEDIUM-TERM / ROUTINE`. Translation happens in the seed and the static-bundle generator, so the raw master keeps its original strings while the UI is consistent everywhere.
7. **The map shows colors at every zoom.** An earlier zoomed-out heatmap blurred all three risk colors into red; the map now renders colored circles at all zoom levels (with a pulse halo on RED only at high zoom) so RED/ORANGE/GREEN stay distinguishable at national view — the exact bug a reviewer flagged and the reason for the rule.
8. **Branded loading UX** — a shared animated loader + shimmer skeletons on data-heavy pages (Analytics, Villages) so a 41 MB first fetch never shows a blank screen.
9. **Neon region matters** — moving the Postgres instance to ap-southeast-1 (Singapore) cut cold-query latency ~4× vs us-east-2 for a Delhi/NE-India demo.

---

## 12. Assumption register (summary)

| Assumption | Value / choice | Where documented |
|------------|----------------|------------------|
| Label buffer radii | 10 km GSI, 15 km EM-DAT | `create_labels.py` comments |
| Zone thresholds (canonical) | RED ≥ 0.9 · ORANGE ≥ 0.4 · GREEN < 0.4 on `susceptibility_score` | README, export header, CHANGELOG |
| Priority tiers | derived from canonical score with **identical** cutoffs (zone-aligned) | `predict.py` `compute_relocation_timeline`, regression-tested |
| Cost weights (research) | FN = 5× FP, evaluated out-of-fold | `optimize_thresholds.py` |
| Soft-label decay | 5 km landslide, 7 km flood (diagnostic only) | `create_soft_labels.py` |
| Carrying-capacity coefficients | land need/household, per-capita water demand, infra weights | `carrying_capacity_assumptions.json` |
| Social-vulnerability weights | risk .40, pop .15, SC/ST .10, access .15, evacuation .10, terrain .10 | `social_vulnerability_assumptions.json` |
| Relocation sensitivity proxy | tribal % ⇒ resistance (documented proxy) | README |
| Max relocation distance | 50 km (CLI-configurable) | `relocation_planner.py` |
| Developable slope cutoff | < 15° | `carrying_capacity.py` |
| Ideal-site cutoff | carrying_capacity_score ≥ 0.8 → 406 of 10,603 sites | `generate_relocation_sites.py` |
| Destination safety rule | relocate only into canonical-GREEN sites (never RED/ORANGE) | `relocation_capacity_pool.csv`, planner CLI |
| Tie-break direction | `>=` ⇒ higher-risk class | create_labels + hazard_decomposition, regression-tested |
| Conservative action rule | RELOCATE/MITIGATE at 1.2× SHAP dominance | `hazard_decomposition.py` |

---

## 13. Validation strategy (how we know it's right)

1. **Spatial CV** (§3) — honest generalization with per-state breakdown.
2. **Ground-truth checks** — EM-DAT disaster zones detected ~99.9% (RED+ORANGE); GSI-cluster state ranking perfect; hill-vs-plains RED ordering correct; Mizoram (most landslide-prone) highest RED share.
3. **Domain-knowledge checks** (`validate_predictions.py`, `validate_real_world.py`) — RED villages closer to landslides, higher rainfall extremes, etc. (3 warnings there are pre-existing data facts, e.g. one Assam district's RED share vs. an assumed 30% floor — documented in the validator).
4. **Structural invariants** — susceptibility feature list has zero leakage features; per-state RED sums equal headline RED; export fields are type-correct with no dangling site references; capacity bookkeeping balances (`available = max(0, total − occupied)`); slope distribution physically plausible; tie-breaks deterministic; zone×tier diagonal is exact.
5. **Full suite (last green run):** `test_pipeline.py` **293/293** · `test_readme_consistency.py` **7/7** · `behavioral_vyoma.py` **41/41** · `validate_vyoma_export.py` **22 checks/file** · `validate_predictions.py` / `validate_real_world.py` (documented pre-existing warnings only). The README-consistency suite pins the *documentation* to the *data*, preventing the stale-number class of bug that plagued early versions.

---

*Design decisions current as of the Sep 4, 2026 pipeline run (43,996 villages, susceptibility model canonical, RED ≥ 0.9). See [`CHANGELOG.md`](CHANGELOG.md) for the dated history of every decision and its revision.*
