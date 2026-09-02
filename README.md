# 🚨 NE India Hazard Red Zone Platform

**Intelligent Identification of Hazard-Based Red Zones, Carrying Capacity Assessment, and Immediate Relocation Needs for Vulnerable Habitations**

> **Problem Statement ID:** 26191 | **Organization:** Ministry of Home Affairs (NDRF/DM Division) | **Theme:** Disaster Management

An AI-driven GIS platform that predicts hazard-based Red Zones across 7 North-Eastern Indian states, identifies safe Green Zones for relocation, and prioritizes 44,000+ vulnerable villages for immediate action.

---

## 📊 Key Results

| Metric | Value |
|--------|-------|
| Villages Assessed | **43,996** across 7 states |
| **Historical Model** AUC-ROC | **99.94%** (random CV) |
| Historical Model Features | **66** (60 original + 6 flood) |
| **Susceptibility Model** Random CV AUC | **0.978** |
| Susceptibility Model Spatial CV AUC | **0.685** (LOSO), **0.770** (LODO) |
| Susceptibility Model Features | **59** (leakage-free) |
| EM-DAT Ground Truth Validation | **99.9%** detection rate |
| HIGH Priority Villages | **13,199** (30%) |
| Model Version | **v1.0** |

### Risk Zone Distribution

| Zone | Villages | Percentage | Description |
|------|----------|------------|-------------|
| 🔴 RED | 22,739 | 51.7% | High hazard — immediate relocation needed |
| 🟠 ORANGE | 15,048 | 34.2% | Medium hazard — monitor and plan |
| 🟢 GREEN | 6,209 | 14.1% | Low hazard — safe for habitation |

### Risk by State

| State | Total Villages | RED Zone | RED % |
|-------|---------------|----------|-------|
| Mizoram | 830 | 804 | 96.9% |
| Nagaland | 1,428 | 1,361 | 95.3% |
| Manipur | 2,581 | 2,424 | 93.9% |
| Meghalaya | 6,839 | 4,548 | 66.5% |
| Arunachal Pradesh | 5,589 | 3,247 | 58.1% |
| Assam | 25,854 | 10,135 | 39.2% |
| Tripura | 875 | 223 | 25.5% |

---

## 🧠 Model Architecture

### Algorithm: XGBoost Classifier

| Hyperparameter | Value |
|----------------|-------|
| `n_estimators` | 500 |
| `max_depth` | 8 |
| `learning_rate` | 0.1 |
| `subsample` | 0.8 |
| `colsample_bytree` | 0.8 |
| `reg_alpha` | 1.0 |
| `reg_lambda` | 1.0 |
| `early_stopping_rounds` | 50 |
| `objective` | `binary:logistic` |
| `eval_metric` | `auc` |

### Training Details

- **Algorithm:** XGBoost (Extreme Gradient Boosting)
- **Task:** Binary classification — predict whether a village is in a hazard Red Zone
- **Training samples:** 43,996 villages
- **Features used:** 66 (selected from 430+ via feature importance analysis)
- **Validation:** 5-fold Stratified Cross-Validation
- **Risk zones:** RED (≥0.7), ORANGE (0.4–0.7), GREEN (<0.4)
- **Label sources:** GSI landslide inventory + EM-DAT historical disasters + DFO flood database

### Cross-Validation Results

| Fold | Accuracy | AUC-ROC | Recall | Precision | F1-Score |
|------|----------|---------|--------|-----------|----------|
| 1 | 98.81% | 0.9995 | 98.98% | 99.26% | 99.12% |
| 2 | 98.78% | 0.9993 | 98.98% | 99.23% | 99.10% |
| 3 | 98.92% | 0.9994 | 99.05% | 99.36% | 99.20% |
| 4 | 98.84% | 0.9994 | 98.83% | 99.46% | 99.14% |
| 5 | 98.81% | 0.9995 | 98.86% | 99.38% | 99.12% |
| **Mean** | **98.83%** | **0.9994** | **98.94%** | **99.34%** | **99.14%** |
| Std | ±0.05% | ±0.0001 | ±0.09% | ±0.09% | ±0.04% |

### Why XGBoost?

1. **Handles mixed feature types** — numerical (elevation, rainfall) and binary (infrastructure status)
2. **Robust to missing values** — 5% of features have NaN (WorldCover coverage gaps)
3. **Feature importance via SHAP** — provides explainability for every prediction
4. **Fast inference** — can score 44K villages in <1 second
5. **Proven for geospatial tabular data** — outperforms neural networks on structured datasets

---

## 🧬 Two-Model Approach

This platform uses **two complementary models** to distinguish between historically-confirmed hazard zones and genuinely susceptible terrain:

### Model 1: Historical Validation Model (Original)
- **Purpose**: Validates that the model correctly identifies villages near past disasters
- **Features**: 66 features including 7 distance/density features derived from GSI landslide and DFO flood records
- **Label**: `high_risk = GSI landslide zone OR EM-DAT disaster zone OR DFO flood zone`
- **Random CV AUC**: 0.9994
- **Known limitation**: Top features (`dist_to_nearest_landslide_km`, `flood_density_50km`) are derived from the same historical events used to create the label — making the model partly circular

### Model 2: Susceptibility Model (Phase 1 — Leakage-Free)
- **Purpose**: Identifies villages that are **physically susceptible** to hazards based on terrain, rainfall, and infrastructure — regardless of whether a disaster has been recorded there
- **Features**: 59 features (physical drivers + Census infrastructure), **zero** distance/density features from historical events
- **Label**: Same `high_risk` binary label, but the model must learn from physical drivers alone
- **Key features**: `elevation_m`, `max_daily_rainfall_mm`, `rain_days_per_year`, `slope_degrees`, `terrain_roughness`

### Spatial Cross-Validation Results

| Strategy | AUC | Recall | F1 | What it measures |
|----------|-----|--------|-----|------------------|
| Random 5-Fold CV | 0.978 | 0.954 | 0.947 | May overestimate due to spatial autocorrelation |
| Leave-One-State-Out (7 folds) | 0.685 | 0.875 | 0.799 | Generalizes to unseen states |
| Leave-One-District-Out (62 folds) | 0.770 | 0.911 | 0.760 | Generalizes to unseen districts |

The **gap between random CV (0.978) and spatial CV (0.685)** reveals that the original model's 0.999 AUC was inflated by spatial autocorrelation — villages near past disasters share similar terrain features. The susceptibility model's spatial CV numbers are an honest measure of generalization.

### Novel Red Zone Detection

`is_novel_red_zone = TRUE` when the susceptibility model flags a village RED/HIGH but **no recorded landslide, flood, or EM-DAT event exists within the standard buffer distance**. These are the villages that current disaster inventories have missed — potentially the most important finding for proactive relocation planning.

---

## 🔬 Feature Engineering

### 66 Features Used by the Model (ranked by SHAP importance)

| Rank | Feature | Source | Description |
|------|---------|--------|-------------|
| 1 | `dist_to_nearest_landslide_km` | GSI | Distance to nearest recorded landslide |
| 2 | `dist_to_nearest_flood_km` | DFO | Distance to nearest historical flood |
| 3 | `landslide_density_100km` | GSI | Number of landslides within 100km radius |
| 4 | `landslide_density_50km` | GSI | Number of landslides within 50km radius |
| 5 | `rainfall_90th_percentile_mm` | IMD | 90th percentile daily rainfall |
| 6 | `flood_density_50km` | DFO | Number of flood events within 50km |
| 7 | `elevation_m` | SRTM DEM | Village elevation in meters |
| 8 | `max_daily_rainfall_mm` | IMD | Maximum single-day rainfall in 5 years |
| 9 | `flood_density_100km` | DFO | Number of flood events within 100km |
| 10 | `mean_daily_rainfall_mm` | IMD | Average daily rainfall over 5 years |
| 11 | `flood_proxy_score` | Derived | Combined flood risk: low elevation + flat + near river + high rainfall |
| 12 | `dist_to_nearest_school_km` | OSM | Distance to nearest school |
| 13 | `slope_degrees` | SRTM DEM | Terrain slope in degrees |
| 14 | `rain_days_per_year` | IMD | Number of rainy days per year |
| 15 | `road_density_5km` | OSM | Road length within 5km buffer |

*Plus 51 more features (terrain, rainfall, infrastructure, Census data).*

### Feature Categories

| Category | Count | Examples |
|----------|-------|---------|
| **Terrain** | 3 | Elevation, slope, terrain roughness |
| **Rainfall** | 5 | Max, mean, 90th/95th percentile, rain days |
| **Landslide Proximity** | 3 | Distance to nearest, density 50km, density 100km |
| **Flood Features** | 6 | Distance to flood, flood density 50/100km, proxy score, is_lowland, near_major_river |
| **Infrastructure** | 5 | Distance to roads, rivers, hospitals, schools, road density |
| **Water Sources** | 18 | Tap water, wells, hand pumps, springs, tube wells |
| **Power Supply** | 12 | Domestic, agriculture, commercial — summer/winter hours |
| **Land Use** | 6 | Forest area, barren land, fallows, cultivated area |
| **Population** | 2 | Total population, geographical area |
| **Roads** | 2 | Pucca road, all-weather road |
| **Other** | 4 | Drainage, waterfall area, etc. |

---

## 📁 Datasets Used

### 1. Census 2011 Village Directory
- **Source:** Ministry of Home Affairs / Census of India
- **Content:** 396 columns per village — population, literacy, SC/ST counts, infrastructure (water, power, roads, health, education)
- **Coverage:** 7 NE India states, ~44,537 villages
- **Key columns:** Population, SC/ST%, literacy, water sources, power supply, road connectivity

### 2. SHRUG Village Polygons
- **Source:** Stanford DevDataLab (https://www.devdatalab.org/shrug)
- **Content:** 648,878 village boundary polygons for all of India, keyed to Census 2011
- **Usage:** Compute village centroids → latitude/longitude coordinates
- **Match rate:** 98.8% (43,996 of 44,537 villages matched)

### 3. SRTM DEM (Digital Elevation Model)
- **Source:** NASA/USGS Shuttle Radar Topography Mission
- **Resolution:** 30m (1 arc-second)
- **Coverage:** 92 tiles covering NE India (21°N–27°N, 88°E–98°E)
- **Derived features:** Elevation, slope (3×3 gradient), terrain roughness (local standard deviation)

### 4. IMD Gridded Rainfall
- **Source:** India Meteorological Department
- **Resolution:** 0.25° × 0.25° (~28km grid cells)
- **Period:** 2020–2024 (5 years, daily)
- **Variable:** Rainfall in mm/day
- **Derived features:** Max daily rainfall, mean daily, 90th/95th percentile, rain days per year

### 5. GSI Landslide Inventory
- **Source:** Geological Survey of India
- **Content:** 30,842 landslide point locations with attributes
- **Attributes:** Triggering mechanism, material type, movement type, geomorphology, casualties
- **Usage:** Primary label source — villages within 10km of a landslide = high risk
- **NE India records:** 10,408 landslide points

### 6. EM-DAT Disaster Database
- **Source:** Centre for Research on the Epidemiology of Disasters (CRED)
- **Content:** 672 disaster records for India (1916–2026)
- **NE India records:** 124 disasters (89 floods, 20 storms, 14 landslides, 1 extreme temperature)
- **Usage:** Historical validation — villages within 15km of EM-DAT disaster = high risk

### 7. ESA WorldCover
- **Source:** European Space Agency
- **Resolution:** 10m
- **Coverage:** 15 tiles covering NE India
- **Classes:** Tree (10), Shrub (20), Grass (30), Cropland (40), Built-up (50), Bare (60), Water (80), Wetland (90)
- **Coverage gap:** ~40% of villages (tiles on 3° grid miss parts of Assam/Mizoram/Tripura)

### 8. OpenStreetMap (OSM)
- **Source:** OpenStreetMap contributors
- **Content:** NE India PBF file (105 MB) — roads, buildings, waterways, amenities
- **Derived features:** Distance to nearest road/river/hospital/school, road density within 5km

### 9. DFO Global Flood Database
- **Source:** Dartmouth Flood Observatory (Zenodo)
- **Content:** 5,503 global flood event records with polygon geometries
- **NE India records:** 274 flood events (1985–2023)
- **Usage:** Label source — villages in high-density flood zones = high risk
- **Derived features:** Flood density 50/100km, distance to nearest flood, flood proxy score

---

## 🔄 Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 0: DATA PREPARATION                    │
│  Census xlsx + SHRUG polygons → Join → CSV with coordinates    │
│  Output: ne_india_census_with_coords.csv (44,537 villages)     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  PHASE 1: FEATURE ENGINEERING                   │
│  SRTM → elevation, slope, roughness                            │
│  IMD → rainfall statistics                                      │
│  WorldCover → land cover class                                  │
│  OSM → distances to infrastructure                              │
│  GSI → landslide proximity & density                            │
│  DFO → flood proximity & density                                │
│  Census → infrastructure features                               │
│  Output: ne_india_village_features.csv (43,996 × 430)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    PHASE 2: LABEL CREATION                      │
│  GSI landslides (10km buffer) + EM-DAT (15km buffer)           │
│  + DFO flood zones (high-density areas)                        │
│  → Binary: high_risk = 1 (disaster zone) / 0 (safe)            │
│  → Multiclass: RED / ORANGE / GREEN                             │
│  Output: 68.0% positive, 32.0% negative                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   PHASE 3: MODEL TRAINING                       │
│  Feature selection (66 from 430+) via importance ranking        │
│  XGBoost Classifier with 5-fold stratified CV                   │
│  SHAP explainability for every prediction                       │
│  Output: trained model (1.9 MB), metrics, SHAP plots            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│               PHASE 4: PRIORITIZATION & VISUALIZATION           │
│  Priority scoring: risk_score × population_vulnerability        │
│  → HIGH / MEDIUM / LOW relocation priority                      │
│  → Per-village output with SHAP explanations                    │
│  Output: prediction_output.csv (14 columns per village)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

```bash
pip install numpy pandas xgboost scikit-learn shap rasterio geopandas osmium folium matplotlib seaborn openpyxl netcdf4 xarray fiona pyproj
```

### 1. Download Datasets

Download the following into `data/raw/`:

| Dataset | Size | Location |
|---------|------|----------|
| Census 2011 (7 states) | ~85 MB | Census of India Village Directory |
| SRTM DEM | ~2.4 GB | NASA Earthdata (92 tiles) |
| IMD Rainfall | ~122 MB | IMD Open Data (NetCDF) |
| GSI Landslide | ~5 MB | GSI Open Data Portal |
| EM-DAT | ~2 MB | https://public.emdat.be |
| ESA WorldCover | ~1.1 GB | ESA WorldCover Portal |
| OSM PBF | ~105 MB | Geofabrik Download Server |
| DFO Flood Database | ~50 MB | Zenodo (Dartmouth Flood Observatory) |

### 2. Run the Pipeline

```bash
# Phase 0: Join Census with SHRUG coordinates
python scripts/join_census_shrug.py

# Phase 1: Extract spatial features
python scripts/extract_raster_features.py
python scripts/extract_vector_features.py
python scripts/extract_flood_features.py
python scripts/combine_features.py

# Phase 2: Create labels
python scripts/create_labels.py
python scripts/update_labels_flood.py

# Phase 3: Train model
python scripts/train_model.py

# Phase 4: Prioritization and visualization
python scripts/phase4_visualization.py
```

### 3. Make Predictions

```bash
# Predict all villages
python scripts/predict.py

# Filter by state
python scripts/predict.py --state Mizoram

# Search specific village
python scripts/predict.py --village "Betanipam"

# Show top N highest risk
python scripts/predict.py --top 20

# Save results to CSV
python scripts/predict.py --save results.csv
```

---

## 📂 Project Structure

```
SIH2026/
├── README.md                          # This file
├── .gitignore                         # Excludes raw data (5.6 GB)
│
├── scripts/                           # Pipeline scripts
│   ├── join_census_shrug.py           # Phase 0: Census + SHRUG coordinate join
│   ├── extract_raster_features.py     # Phase 1: SRTM + WorldCover extraction
│   ├── extract_vector_features.py     # Phase 1: OSM + Landslide distances
│   ├── extract_flood_features.py      # Phase 1: DFO flood feature extraction
│   ├── extract_cloudburst_features.py # Phase 1: Cloudburst risk proxy (pluggable stub)
│   ├── combine_features.py            # Phase 1: Merge all features
│   ├── create_labels.py               # Phase 2: Binary + multiclass labels
│   ├── update_labels_flood.py         # Phase 2: Add DFO flood zones as label source
│   ├── train_model.py                 # Phase 3: XGBoost + SHAP training
│   ├── phase4_visualization.py        # Phase 4: Prioritization + reports
│   ├── predict.py                     # Standalone prediction script
│   ├── carrying_capacity.py           # Carrying capacity engine for GREEN zones
│   ├── match_relocation_sites.py      # Greedy relocation site matcher
│   └── refresh_rainfall.py            # Real-time rainfall refresh (demo hook)
│
├── backend/                           # FastAPI GIS dashboard backend
│   ├── main.py                        # API server (villages, SHAP, matches, refresh)
│   └── requirements.txt               # Backend dependencies
│
├── frontend/                          # GIS dashboard frontend
│   └── index.html                     # Leaflet map + marker clustering + sidebar
│
├── run_dashboard.sh                   # One-command dashboard startup
│
├── models/                            # Trained model artifacts
│   ├── red_zone_xgboost.json          # Trained XGBoost model (1.9 MB)
│   ├── model_metadata.json            # Hyperparameters, metrics, features
│   ├── feature_importance.csv         # 66 features ranked by SHAP
│   ├── cv_scores.csv                  # 5-fold CV metrics
│   ├── features.json                  # Feature list
│   ├── model_evaluation.png           # Confusion matrix, ROC, PR curves
│   └── shap_summary.png              # SHAP feature importance plot
│
├── tests/                             # End-to-end validation
│   ├── test_pipeline.py               # 159 assertions across 12 categories
│   ├── validate_predictions.py        # EM-DAT, GSI, domain knowledge checks
│   └── validate_real_world.py         # Ground truth validation against real disasters
│
├── data/
│   ├── raw/                           # Raw datasets (gitignored, ~5.6 GB)
│   │   ├── census/                    # Census 2011 xlsx files
│   │   ├── shrug/                     # SHRUG village polygons
│   │   ├── srtm/                      # SRTM DEM tiles
│   │   ├── imd_rainfall/              # IMD NetCDF files
│   │   ├── gsi_landslide/             # GSI landslide shapefiles
│   │   ├── emdat/                     # EM-DAT Excel
│   │   ├── worldcover/                # ESA WorldCover GeoTIFFs
│   │   ├── openstreetmap/             # OpenStreetMap PBF
│   │   └── floods/                    # DFO Global Flood Database
│   │
│   └── processed/                     # Generated data (gitignored)
│       ├── ne_india_census_with_coords.csv  # Census + SHRUG join
│       ├── ne_india_village_features.csv     # Full feature matrix
│       ├── village_risk_labels.csv           # Binary + multiclass labels
│       └── prediction_output.csv             # Final prediction output
```

---

## 🧪 Testing & Validation

### End-to-End Tests (159 assertions)

| Test Category | Assertions | Status |
|---------------|-----------|--------|
| Data Integrity | 19 | ✅ |
| Model Predictions | 12 | ✅ |
| Label Integrity | 9 | ✅ |
| Spatial Features | 44 | ✅ |
| Prioritization | 7 | ✅ |
| Green Zone | 7 | ✅ |
| Model Artifacts | 13 | ✅ |
| Model Load+Predict | 5 | ✅ |
| CV Consistency | 6 | ✅ |
| Prediction Output Fields | 31 | ✅ |
| Bug Fix Regression | 12 | ✅ |

Run tests:
```bash
python tests/test_pipeline.py
python tests/validate_predictions.py
python tests/validate_real_world.py
```

### Ground Truth Validation

| Validation Method | Result |
|-------------------|--------|
| EM-DAT disaster zones → RED/ORANGE | **99.9%** detected |
| GSI landslide clusters → state ranking | **Perfect correlation** |
| Hill states vs Plains states RED% | **71.3% vs 41.7%** (correct) |
| Villages within 5km of landslide | **100% flagged RED** |
| Villages >50km from landslides, low density | **81.6% flagged GREEN** |
| Mizoram (most landslide-prone) | **96.9% RED** |
| Assam (flatter Brahmaputra valley) | **39.2% RED** |
| Dhemaji (flood district) | **94% RED** ✅ |
| Dibrugarh (flood district) | **54% RED** ✅ |
| Sivasagar (flood district) | **40% RED** ✅ |

---

## 🏛️ How It Works

### Label Creation (Training Data)

Villages are labeled as **high_risk = 1** if they fall within:
- **10 km buffer** around any of 30,842 GSI landslide points
- **15 km buffer** around any of 124 EM-DAT historical disaster locations in NE India
- **High-density DFO flood zones** (areas with multiple historical flood events)

This creates a binary classification problem: **disaster-affected (1) vs safe (0)**.

### Feature Extraction

For each village, 66 features are computed:
1. **Raster sampling** — Elevation from SRTM, land cover from WorldCover, rainfall from IMD
2. **Spatial joins** — Distance to nearest landslide, road, river, hospital, school using KDTree
3. **Buffer analysis** — Landslide density within 50km and 100km radii
4. **Flood analysis** — DFO flood proximity, density, and proxy score
5. **Census columns** — Water sources, power supply, roads, population

### Model Training

- XGBoost trained on 66 selected features
- 5-fold stratified cross-validation for robust evaluation
- Early stopping prevents overfitting
- SHAP values computed for explainability

### Risk Scoring

Each village gets a **risk_score** (0.0–1.0):
- **RED zone:** score ≥ 0.7 → high hazard, immediate relocation needed
- **ORANGE zone:** 0.4 ≤ score < 0.7 → medium hazard, monitor and plan
- **GREEN zone:** score < 0.4 → low hazard, safe for habitation

### Prioritization

Villages are ranked by **priority_score = risk_score × vulnerability_multiplier**:
- **HIGH:** Top 30% — short-term action
- **MEDIUM:** Middle 30% — monitoring and planning
- **LOW:** Bottom 40% — routine monitoring

---

## 🌊 Hazard Scope

The problem statement names four hazard types: **landslides**, **floods**, **coastal erosion**, and **cloudbursts**. The current pipeline covers the first two (NE India's dominant hazards) and is architected to be extensible to the others.

### Currently Implemented

| Hazard | Label Source | Feature Sources | Status |
|--------|-------------|----------------|--------|
| **Landslides** | GSI landslide inventory (10,408 points) | Distance to landslide, landslide density 50/100km, slope, elevation, terrain roughness | ✅ Production |
| **Floods** | DFO Global Flood Database (274 NE India events) | Flood density 50/100km, distance to flood zone, flood proxy score, is_lowland, near_major_river | ✅ Production |

### Architecturally Pluggable (Not Yet Implemented)

| Hazard | Proposed Data Source | How to Add |
|--------|-------------------|------------|
| **Coastal Erosion** | ISRO/NRSC shoreline change data, CWPRS erosion maps | Create `extract_coastal_features.py` — compute distance to coast, erosion rate proxy (elevation + wave exposure), shoreline change index |
| **Cloudbursts** | IMD 1-min/5-min rainfall data, satellite-based rainfall estimates | Create `extract_cloudburst_features.py` — already stubbed, derives features from existing IMD rainfall (max_daily_rainfall_mm, rain_days_per_year, concentration index) |

### How to Add a New Hazard Module

Follow the existing pattern used for flood features:

```
1. extract_<hazard>_features.py  → Extract per-village features from new data
2. combine_features.py            → Add new columns to the feature matrix
3. update_labels_<hazard>.py      → Add new label source (if historical events available)
4. Retrain model with updated labels + features
```

The cloudburst extraction script (`scripts/extract_cloudburst_features.py`) is already implemented as a reference stub — it computes `cloudburst_risk_score` and `extreme_rainfall_days` from existing IMD data without requiring any new datasets.

---

## 🔍 Explainability (SHAP)

The model uses **SHAP (SHapley Additive exPlanations)** to explain every prediction:

**Global explanation** — Top risk factors across all villages:
1. **Distance to nearest landslide** (most important feature)
2. **Distance to nearest flood** — historical flood proximity drives risk
3. **Landslide density** — regions with many historical landslides remain dangerous
4. **Flood density** — areas with frequent flooding are high-risk
5. **Rainfall intensity** — heavy monsoon rainfall drives both landslide and flood risk

**Local explanation** — For any village, SHAP shows exactly which features pushed the prediction toward RED or GREEN.

---

## ⚠️ Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| SRTM missing 28 tiles (northern Arunachal) | ~500 villages lack elevation data | Interpolate from neighboring tiles |
| WorldCover only covers 40% of villages | Land cover feature missing for 60% | Model still performs well without it |
| EM-DAT only 18/124 NE India records have coordinates | Geocoding needed for 105 records | Used district centroids as proxy |
| Census 2011 data is 15 years old | Population/growth data outdated | Spatial features are current (2021–2024) |
| Sikkim Census data is a PDF (not xlsx) | 462 villages missing from dataset | Could OCR the PDF in future |
| DFO flood data has coverage gaps | Tinsukia, Dhubri flood events underrepresented | Model captures relative flood risk well |
| Model captures relative risk, not absolute | Flat districts near flood plains may score lower | Add more flood zone data in future |

---

## 🛠️ Dependencies

```
numpy>=1.24
pandas>=2.0
xgboost>=2.0
scikit-learn>=1.3
shap>=0.42
rasterio>=1.3
geopandas>=0.14
osmium>=3.7
folium>=0.15
matplotlib>=3.7
seaborn>=0.12
openpyxl>=3.1
netCDF4>=1.6
xarray>=2023.1
fiona>=1.9
pyproj>=3.6
```

---

## 👥 Team

**Smart India Hackathon 2026 — Problem Statement #26191**

Ministry of Home Affairs | National Disaster Response Force (NDRF) | DM Division

---

## 📜 License

This project was developed for Smart India Hackathon 2026. Datasets are sourced from open government data portals.
