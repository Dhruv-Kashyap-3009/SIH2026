# 🚨 NE India Hazard Red Zone Platform

**Intelligent Identification of Hazard-Based Red Zones, Carrying Capacity Assessment, and Immediate Relocation Needs for Vulnerable Habitations**

> **Problem Statement ID:** 26191 | **Organization:** Ministry of Home Affairs (NDRF/DM Division) | **Theme:** Disaster Management

An AI-driven GIS platform that predicts hazard-based Red Zones across 7 North-Eastern Indian states, identifies safe Green Zones for relocation, and prioritizes 44,000+ vulnerable villages for immediate action.

---

## 📊 Key Results

| Metric | Value |
|--------|-------|
| Villages Assessed | **43,996** across 7 states |
| Model AUC-ROC | **99.8%** |
| Model Recall | **97.4%** |
| Model Precision | **98.4%** |
| EM-DAT Ground Truth Validation | **98.9%** detection rate |
| CRITICAL Priority Villages | **4,400** |
| IDEAL Relocation Sites | **236** |

### Risk Zone Distribution

| Zone | Villages | Percentage | Description |
|------|----------|------------|-------------|
| 🔴 RED | 23,452 | 53.3% | High hazard — immediate relocation needed |
| 🟠 ORANGE | 1,054 | 2.4% | Medium hazard — monitor and plan |
| 🟢 GREEN | 19,490 | 44.3% | Low hazard — safe for habitation |

### Risk by State

| State | Total Villages | RED Zone | RED % |
|-------|---------------|----------|-------|
| Mizoram | 830 | 803 | 96.7% |
| Nagaland | 1,428 | 1,360 | 95.2% |
| Manipur | 2,581 | 2,411 | 93.4% |
| Meghalaya | 6,839 | 4,526 | 66.2% |
| Arunachal Pradesh | 5,589 | 3,212 | 57.5% |
| Assam | 25,854 | 10,919 | 42.2% |
| Tripura | 875 | 221 | 25.3% |

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
| `scale_pos_weight` | 0.819 (class imbalance adjustment) |
| `early_stopping_rounds` | 50 |
| `objective` | `binary:logistic` |
| `eval_metric` | `auc` |

### Training Details

- **Algorithm:** XGBoost (Extreme Gradient Boosting)
- **Task:** Binary classification — predict whether a village is in a hazard Red Zone
- **Training samples:** 43,996 villages
- **Features used:** 60 (selected from 430+ via feature importance analysis)
- **Validation:** 5-fold Stratified Cross-Validation
- **Threshold:** 0.5 (probability > 0.5 → RED zone)
- **Risk zones:** RED (>0.7), ORANGE (0.3–0.7), GREEN (<0.3)

### Cross-Validation Results

| Fold | Accuracy | AUC-ROC | Recall | Precision | F1-Score |
|------|----------|---------|--------|-----------|----------|
| 1 | 97.73% | 0.9980 | 97.66% | 98.18% | 97.92% |
| 2 | 97.91% | 0.9979 | 97.47% | 98.70% | 98.08% |
| 3 | 97.69% | 0.9980 | 97.26% | 98.51% | 97.88% |
| 4 | 97.45% | 0.9977 | 97.09% | 98.24% | 97.66% |
| 5 | 97.73% | 0.9980 | 97.39% | 98.48% | 97.93% |
| **Mean** | **97.70%** | **0.9979** | **97.37%** | **98.41%** | **97.89%** |
| Std | ±0.17% | ±0.0002 | ±0.22% | ±0.27% | ±0.16% |

### Why XGBoost?

1. **Handles mixed feature types** — numerical (elevation, rainfall) and binary (infrastructure status)
2. **Robust to missing values** — 5% of features have NaN (WorldCover coverage gaps)
3. **Feature importance via SHAP** — provides explainability for every prediction
4. **Fast inference** — can score 44K villages in <1 second
5. **Proven for geospatial tabular data** — outperforms neural networks on structured datasets

---

## 🔬 Feature Engineering

### 60 Features Used by the Model (ranked by SHAP importance)

| Rank | Feature | SHAP Value | Source | Description |
|------|---------|-----------|--------|-------------|
| 1 | `dist_to_nearest_landslide_km` | 5.104 | GSI | Distance to nearest recorded landslide |
| 2 | `mean_daily_rainfall_mm` | 0.547 | IMD | Average daily rainfall over 5 years |
| 3 | `landslide_density_100km` | 0.390 | GSI | Number of landslides within 100km radius |
| 4 | `landslide_density_50km` | 0.377 | GSI | Number of landslides within 50km radius |
| 5 | `elevation_m` | 0.340 | SRTM DEM | Village elevation in meters |
| 6 | `max_daily_rainfall_mm` | 0.315 | IMD | Maximum single-day rainfall in 5 years |
| 7 | `dist_to_nearest_school_km` | 0.297 | OSM | Distance to nearest school |
| 8 | `rainfall_90th_percentile_mm` | 0.271 | IMD | 90th percentile daily rainfall |
| 9 | `rain_days_per_year` | 0.238 | IMD | Number of rainy days per year |
| 10 | `Total Geographical Area` | 0.177 | Census | Village area in hectares |
| 11 | `road_density_5km` | 0.170 | OSM | Road length within 5km buffer |
| 12 | `dist_to_nearest_hospital_km` | 0.164 | OSM | Distance to nearest hospital |
| 13 | `rainfall_95th_percentile_mm` | 0.133 | IMD | 95th percentile daily rainfall |
| 14 | `Total Population of Village` | 0.067 | Census | Total village population |
| 15 | `Power Supply Domestic Winter` | 0.059 | Census | Hours of domestic power in winter |

*Plus 45 more Census infrastructure features (water sources, roads, health facilities, land use).*

### Feature Categories

| Category | Count | Examples |
|----------|-------|---------|
| **Terrain** | 3 | Elevation, slope, terrain roughness |
| **Rainfall** | 5 | Max, mean, 90th/95th percentile, rain days |
| **Landslide Proximity** | 3 | Distance to nearest, density 50km, density 100km |
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
│  Census → infrastructure features                               │
│  Output: ne_india_village_features.csv (43,996 × 430)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    PHASE 2: LABEL CREATION                      │
│  GSI landslides (10km buffer) + EM-DAT (15km buffer)           │
│  → Binary: high_risk = 1 (disaster zone) / 0 (safe)            │
│  → Multiclass: RED / ORANGE / GREEN                             │
│  Output: 54.8% positive, 45.2% negative                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   PHASE 3: MODEL TRAINING                       │
│  Feature selection (60 from 430+) via importance ranking        │
│  XGBoost Classifier with 5-fold stratified CV                   │
│  SHAP explainability for every prediction                       │
│  Output: trained model (1.9 MB), metrics, SHAP plots            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│               PHASE 4: PRIORITIZATION & VISUALIZATION           │
│  Priority scoring: risk_score × population_vulnerability        │
│  → CRITICAL / HIGH / MEDIUM / LOW relocation priority           │
│  → Interactive Folium map with color-coded villages             │
│  Output: risk map (HTML), ranked CSV, state reports             │
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

### 2. Run the Pipeline

```bash
# Phase 0: Join Census with SHRUG coordinates
python scripts/join_census_shrug.py

# Phase 1: Extract spatial features
python scripts/extract_raster_features.py
python scripts/extract_vector_features.py
python scripts/combine_features.py

# Phase 2: Create labels
python scripts/create_labels.py

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
├── scripts/                           # Pipeline scripts (3,248 lines)
│   ├── join_census_shrug.py           # Phase 0: Census + SHRUG coordinate join
│   ├── extract_raster_features.py     # Phase 1: SRTM + WorldCover extraction
│   ├── extract_vector_features.py     # Phase 1: OSM + Landslide distances
│   ├── combine_features.py            # Phase 1: Merge all features
│   ├── create_labels.py               # Phase 2: Binary + multiclass labels
│   ├── train_model.py                 # Phase 3: XGBoost + SHAP training
│   ├── phase4_visualization.py        # Phase 4: Maps + prioritization
│   └── predict.py                     # Standalone prediction script
│
├── models/                            # Trained model artifacts
│   ├── red_zone_xgboost.json          # Trained XGBoost model (1.9 MB)
│   ├── model_metadata.json            # Hyperparameters, metrics, features
│   ├── feature_importance.csv         # 60 features ranked by SHAP
│   ├── cv_scores.csv                  # 5-fold CV metrics
│   ├── features.json                  # Feature list
│   ├── model_evaluation.png           # Confusion matrix, ROC, PR curves
│   └── shap_summary.png              # SHAP feature importance plot
│
├── tests/                             # End-to-end validation
│   ├── test_pipeline.py               # 115 assertions across 10 categories
│   └── validate_predictions.py        # EM-DAT, GSI, domain knowledge checks
│
├── data/
│   ├── raw/                           # Raw datasets (gitignored, ~5.6 GB)
│   │   ├── census/                    # Census 2011 xlsx files
│   │   ├── srtm/                      # SRTM DEM tiles
│   │   ├── imd_rainfall/              # IMD NetCDF files
│   │   ├── gsi_landslide/             # GSI landslide shapefiles
│   │   ├── emdat/                     # EM-DAT Excel
│   │   ├── worldcover/                # ESA WorldCover GeoTIFFs
│   │   ├── osm/                       # OpenStreetMap PBF
│   │   └── shrug/                     # SHRUG village polygons
│   │
│   └── processed/                     # Generated data (gitignored)
│       ├── ne_india_census_with_coords.csv  # Census + SHRUG join
│       ├── ne_india_village_features.csv     # Full feature matrix
│       ├── village_risk_labels.csv           # Binary + multiclass labels
│       ├── village_srtm_wc_features.csv      # SRTM + WorldCover
│       ├── village_rainfall_features.csv     # IMD rainfall stats
│       ├── village_osm_features.csv          # OSM distances
│       ├── village_vector_features.csv       # Hospital/school/landslide
│       ├── reports/                          # Generated reports
│       └── maps/                             # Interactive HTML maps
```

---

## 🧪 Testing & Validation

### End-to-End Tests (115 assertions)

| Test Category | Assertions | Status |
|---------------|-----------|--------|
| Data Integrity | 19 | ✅ |
| Model Predictions | 12 | ✅ |
| Label Integrity | 9 | ✅ |
| Spatial Features | 44 | ✅ |
| Prioritization | 7 | ✅ |
| Green Zone | 7 | ✅ |
| Model Artifacts | 13 | ✅ |
| Map/Report Files | 17 | ✅ |
| Model Load+Predict | 5 | ✅ |
| CV Consistency | 6 | ✅ |

Run tests:
```bash
python tests/test_pipeline.py
python tests/validate_predictions.py
```

### Ground Truth Validation

| Validation Method | Result |
|-------------------|--------|
| EM-DAT disaster zones → RED/ORANGE | **98.9%** detected |
| GSI landslide clusters → state ranking | **Perfect correlation** |
| Hill states vs Plains states RED% | **71.3% vs 41.7%** (correct) |
| Villages within 5km of landslide | **100% flagged RED** |
| Villages >50km from landslides, low density | **81.6% flagged GREEN** |
| Mizoram (most landslide-prone) | **96.7% RED** |
| Assam (flatter Brahmaputra valley) | **42.2% RED** |

---

## 🏛️ How It Works

### Label Creation (Training Data)

Villages are labeled as **high_risk = 1** if they fall within:
- **10 km buffer** around any of 30,842 GSI landslide points
- **15 km buffer** around any of 124 EM-DAT historical disaster locations in NE India

This creates a binary classification problem: **disaster-affected (1) vs safe (0)**.

### Feature Extraction

For each village, 60 features are computed:
1. **Raster sampling** — Elevation from SRTM, land cover from WorldCover, rainfall from IMD
2. **Spatial joins** — Distance to nearest landslide, road, river, hospital, school using KDTree
3. **Buffer analysis** — Landslide density within 50km and 100km radii
4. **Census columns** — Water sources, power supply, roads, population

### Model Training

- XGBoost trained on 60 selected features
- 5-fold stratified cross-validation for robust evaluation
- Early stopping prevents overfitting
- SHAP values computed for explainability

### Risk Scoring

Each village gets a **risk_score** (0.0–1.0):
- **RED zone:** score > 0.7 → high hazard, immediate relocation needed
- **ORANGE zone:** 0.3 < score ≤ 0.7 → medium hazard, monitor and plan
- **GREEN zone:** score ≤ 0.3 → low hazard, safe for habitation

### Prioritization

Villages are ranked by **priority_score = risk_score × vulnerability_multiplier**:
- **CRITICAL:** Top 10% — immediate relocation
- **HIGH:** Next 20% — short-term action
- **MEDIUM:** Next 30% — monitoring and planning
- **LOW:** Bottom 40% — routine monitoring

---

## 🔍 Explainability (SHAP)

The model uses **SHAP (SHapley Additive exPlanations)** to explain every prediction:

**Global explanation** — Top risk factors across all villages:
1. **Distance to nearest landslide** (10x more important than any other feature)
2. **Mean daily rainfall** — heavy monsoon rainfall drives landslide risk
3. **Landslide density** — regions with many historical landslides remain dangerous
4. **Elevation** — higher villages in mountainous terrain are at greater risk
5. **Distance to school/hospital** — proxy for remoteness and limited emergency access

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
| Model trained on landslide + flood labels | May miss other hazards (erosion, earthquake) | Expand GSI data for other hazard types |

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
