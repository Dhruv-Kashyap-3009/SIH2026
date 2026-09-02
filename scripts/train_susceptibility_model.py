"""
Phase 1: Susceptibility Model — Leakage-Free Hazard Prediction

Trains an XGBoost model using ONLY physical/spatial drivers and Census
infrastructure features. NO distance/density features derived from
historical disaster events (GSI landslides, DFO floods, EM-DAT records).

This model answers: "Given the terrain and infrastructure, is this
village inherently susceptible to hazards?" — NOT "Was this village
near a past disaster?"

Usage:
    python scripts/train_susceptibility_model.py
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import os
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warnings
warnings.filterwarnings('ignore')
from spatial_cv import run_all_cv_strategies, _default_params

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'
os.makedirs(MODEL_DIR, exist_ok=True)

# ============================================================
# LEAKAGE-FREE FEATURE DEFINITIONS
# ============================================================
# These features capture genuine physical susceptibility drivers
# and Census infrastructure — none are derived from historical
# disaster event locations used to construct the label.

# Physical/spatial drivers from remote sensing
PHYSICAL_FEATURES = [
    'elevation_m',
    'slope_degrees',
    'terrain_roughness',
    'max_daily_rainfall_mm',
    'mean_daily_rainfall_mm',
    'rainfall_90th_percentile_mm',
    'rainfall_95th_percentile_mm',
    'rain_days_per_year',
    'dist_to_nearest_road_km',
    'dist_to_nearest_river_km',
    'dist_to_nearest_hospital_km',
    'dist_to_nearest_school_km',
    'road_density_5km',
    'is_lowland',
    'near_major_river',
    'landcover_class',
]

# Census infrastructure features (water, power, roads, land area)
CENSUS_INFRA_FEATURES = [
    'Total Geographical Area (in Hectares)',
    'Total Population of Village',
    'Tap Water-Treated (Status A(1)/NA(2))',
    'Tap Water-Treated Functioning All round the year (Status A(1)/NA(2))',
    'Tap Water-Treated Functioning in Summer months (April-September) (Status A(1)/NA(2))',
    'Tap Water Untreated (Status A(1)/NA(2))',
    'Tap Water Untreated Functioning All round the year (Status A(1)/NA(2))',
    'Tap Water Untreated Functioning in Summer months (April-September) (Status A(1)/NA(2))',
    'Covered Well (Status A(1)/NA(2))',
    'Covered Well Functioning All round the year (Status A(1)/NA(2))',
    'Covered Well Functioning in Summer months (April-September) (Status A(1)/NA(2))',
    'Uncovered  Well (Status A(1)/NA(2))',
    'Uncovered  Well Functioning All round the year (Status A(1)/NA(2))',
    'Uncovered  Well Functioning in Summer months (April-September) (Status A(1)/NA(2))',
    'Hand Pump (Status A(1)/NA(2))',
    'Hand Pump Functioning All round the year (Status A(1)/NA(2))',
    'Hand Pump Functioning in Summer months (April-September) (Status A(1)/NA(2))',
    'Tube Wells/Borehole (Status A(1)/NA(2))',
    'Tube Wells/Borehole Functioning All round the year (Status A(1)/NA(2))',
    'Tube Wells/Borehole Functioning in Summer months (April-September) (Status A(1)/NA(2))',
    'Spring (Status A(1)/NA(2))',
    'Spring Functioning All round the year (Status A(1)/NA(2))',
    'Spring Functioning in Summer months (April-September) (Status A(1)/NA(2))',
    'Black Topped (pucca) Road (Status A(1)/NA(2))',
    'All Weather Road (Status A(1)/NA(2))',
    'Power Supply For Domestic Use  (Status A(1)/NA(2))',
    'Power Supply For Domestic Use Summer (April-Sept.) per day (in Hours)',
    'Power Supply For Domestic Use Winter (Oct.-March) per day (in Hours)',
    'Power Supply For Agriculture Use (Status A(1)/NA(2))',
    'Power Supply For Agriculture Use Summer (April-Sept.) per day (in Hours)',
    'Power Supply For Agriculture Use Winter (Oct.-March)per day (in Hours)',
    'Power Supply For Commercial Use (Status A(1)/NA(2))',
    'Power Supply For Commercial Use Summer (April-Sept.) per day (in Hours)',
    'Power Supply For Commercial Use Winter (Oct.-March) per day (in Hours)',
    'Power Supply For All Users (Status A(1)/NA(2))',
    'Power Supply For All Users Summer (April-Sept.) per day (in Hours)',
    'Power Supply For All Users Winter (Oct.-March) per day (in Hours)',
    'Wells/Tube Wells Area (in Hectares)',
    'Whether Drain water is discharged directly into water bodies or to sewar plant (For Water Bodies-1/Sewar Plants-2)',
    'Waterfall Area (in Hectares)',
    'Forest Area (in Hectares)',
    'Barren & Un-cultivable Land Area (in Hectares)',
    'Fallows Land other than Current Fallows Area (in Hectares)',
    'Current Fallows Area (in Hectares)',
]

# Explicitly forbidden features — derived from label sources
LEAKAGE_FEATURES = [
    'dist_to_nearest_landslide_km',
    'landslide_density_50km',
    'landslide_density_100km',
    'dist_to_nearest_flood_km',
    'flood_density_50km',
    'flood_density_100km',
    'flood_proxy_score',
]

# Combined leakage-free feature list
SUSCEPTIBILITY_FEATURES = PHYSICAL_FEATURES + CENSUS_INFRA_FEATURES


def verify_feature_count():
    """Programmatically verify feature counts — not manually counted."""
    physical = len(PHYSICAL_FEATURES)
    census = len(CENSUS_INFRA_FEATURES)
    total = len(SUSCEPTIBILITY_FEATURES)
    leakage = len(LEAKAGE_FEATURES)

    # Sanity checks
    assert physical == 16, f"Expected 16 physical features, got {physical}"
    assert total == physical + census, f"Total mismatch: {physical} + {census} != {total}"
    assert len(set(SUSCEPTIBILITY_FEATURES)) == total, "Duplicates in feature list"
    assert len(set(SUSCEPTIBILITY_FEATURES) & set(LEAKAGE_FEATURES)) == 0, \
        "Feature list contains leakage features!"

    print(f"Feature counts verified:")
    print(f"  Physical drivers:    {physical}")
    print(f"  Census infrastructure: {census}")
    print(f"  Total kept:          {total}")
    print(f"  Leakage dropped:     {leakage}")
    return total


def load_data():
    """Load feature matrix and select leakage-free features."""
    print("Loading feature matrix...")
    df = pd.read_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude', 'high_risk'])
    print(f"Total villages: {len(df):,}")

    # Filter to available features
    available = [f for f in SUSCEPTIBILITY_FEATURES if f in df.columns]
    missing = [f for f in SUSCEPTIBILITY_FEATURES if f not in df.columns]
    if missing:
        print(f"  ⚠ Missing {len(missing)} features (will be excluded):")
        for f in missing:
            print(f"    - {f}")

    # Filter to features with >50% non-null
    good_features = []
    for f in available:
        if df[f].notna().mean() > 0.5:
            good_features.append(f)

    print(f"  Selected {len(good_features)} features from {len(SUSCEPTIBILITY_FEATURES)} planned")

    # Verify NO leakage features are included
    leakage_in_features = set(good_features) & set(LEAKAGE_FEATURES)
    assert len(leakage_in_features) == 0, \
        f"CRITICAL: Leakage features found in model: {leakage_in_features}"

    # Create feature matrix
    X = df[good_features].copy()
    y = df['high_risk'].copy()

    # Fill NaN with median
    for col in X.columns:
        if X[col].isna().sum() > 0:
            X[col] = X[col].fillna(X[col].median())

    X = X.astype(float)

    return df, X, y, good_features


def train_final_model(X, y, features):
    """Train the final susceptibility model on all data (after CV evaluation)."""
    print(f"\n=== Training Final Susceptibility Model ===")
    print(f"Features: {len(features)}")
    print(f"Samples: {X.shape[0]:,}")
    print(f"Positive class: {int(y.sum()):,} ({y.mean()*100:.1f}%)")

    params = _default_params()
    params.pop('early_stopping_rounds', None)

    model = xgb.XGBClassifier(**params)
    model.fit(X, y, verbose=False)

    # Save model
    model_path = os.path.join(MODEL_DIR, 'susceptibility_xgboost.json')
    model.save_model(model_path)
    print(f"  Saved: {model_path}")

    # Save feature list
    features_path = os.path.join(MODEL_DIR, 'susceptibility_features.json')
    with open(features_path, 'w') as f:
        json.dump(features, f, indent=2)
    print(f"  Saved: {features_path}")

    return model


def compute_shap_explanations(model, X, features, n_samples=1000):
    """Compute SHAP values for feature importance."""
    print("\nComputing SHAP explanations...")
    explainer = shap.TreeExplainer(model)
    sample_idx = np.random.choice(len(X), min(n_samples, len(X)), replace=False)
    shap_values = explainer.shap_values(X.iloc[sample_idx])

    # Global feature importance
    importance = pd.DataFrame({
        'feature': features,
        'importance': np.abs(shap_values).mean(axis=0)
    }).sort_values('importance', ascending=False)

    print("  Top 10 features:")
    for _, row in importance.head(10).iterrows():
        print(f"    {row['feature']:<50} {row['importance']:.4f}")

    # Save
    importance.to_csv(os.path.join(MODEL_DIR, 'susceptibility_feature_importance.csv'), index=False)
    return importance


def main():
    print("=" * 60)
    print("Phase 1: Susceptibility Model (Leakage-Free)")
    print("=" * 60)

    # Verify feature counts
    n_features = verify_feature_count()

    # Load data
    df, X, y, features = load_data()

    # Verify feature count matches
    assert len(features) == n_features or len(features) <= n_features, \
        f"Feature count mismatch: planned {n_features}, got {len(features)}"

    # Run spatial CV
    states = df['State Name']
    districts = df['District Name']

    cv_results = run_all_cv_strategies(X, y, states, districts, features)

    # Train final model on all data
    model = train_final_model(X, y, features)

    # SHAP explanations
    importance = compute_shap_explanations(model, X, features)

    # Save metadata with both random and spatial CV results
    metadata = {
        'model_type': 'susceptibility_xgboost',
        'description': 'Leakage-free hazard susceptibility model using physical drivers and Census infrastructure only',
        'n_features': len(features),
        'n_samples': len(X),
        'n_positive': int(y.sum()),
        'positive_rate': float(y.mean()),
        'features_dropped_due_to_leakage': LEAKAGE_FEATURES,
        'n_leakage_features_dropped': len(LEAKAGE_FEATURES),
        'feature_categories': {
            'physical_drivers': len(PHYSICAL_FEATURES),
            'census_infrastructure': len(CENSUS_INFRA_FEATURES),
        },
        'cv_results': {
            'random_cv': {k: v for k, v in cv_results['random_cv'].items() if k != 'fold_results'},
            'spatial_cv_leave_one_state': {k: v for k, v in cv_results['spatial_cv_leave_one_state'].items() if k != 'fold_results'},
            'spatial_cv_leave_one_district': {k: v for k, v in cv_results['spatial_cv_leave_one_district'].items() if k != 'fold_results'},
        },
    }

    metadata_path = os.path.join(MODEL_DIR, 'susceptibility_model_metadata.json')
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\n  Saved metadata: {metadata_path}")

    print("\n" + "=" * 60)
    print("Susceptibility Model Training Complete")
    print("=" * 60)
    return model, features, cv_results


if __name__ == '__main__':
    main()
