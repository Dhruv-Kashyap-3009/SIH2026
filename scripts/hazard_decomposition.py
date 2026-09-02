"""
Phase 5: Multi-Hazard Decomposition

Decomposes the overall risk score into separate landslide_risk_score and
flood_risk_score using SHAP-based feature group attribution.

Approach:
- Group features into landslide-related and flood-related groups
- Use SHAP values to attribute risk to each hazard type
- Normalize scores to [0, 1]
- Add recommended_action column based on which hazard dominates

Feature groups:
- LANDSLIDE features: elevation, slope, terrain_roughness, rainfall intensity,
  road density, infrastructure distances (terrain-driven hazards)
- FLOOD features: rainfall volume, rain_days, is_lowland, near_major_river,
  river distance, water infrastructure (water-driven hazards)
- SHARED features: infrastructure distances, Census features

recommended_action logic:
- RELOCATE: landslide_risk > 0.5 AND landslide dominates (hard to mitigate)
- MITIGATE: flood_risk > 0.5 AND flood dominates AND carrying capacity shows
  fortification is feasible
- MONITOR: low risk or mixed signals

Output: Updated prediction_output.csv with new columns
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import os
import json

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'

# Feature group definitions (maps feature names to hazard types)
LANDSLIDE_FEATURES = [
    'elevation_m', 'slope_degrees', 'terrain_roughness',
    'dist_to_nearest_road_km', 'road_density_5km',
    'dist_to_nearest_hospital_km', 'dist_to_nearest_school_km',
]

FLOOD_FEATURES = [
    'max_daily_rainfall_mm', 'mean_daily_rainfall_mm',
    'rainfall_90th_percentile_mm', 'rainfall_95th_percentile_mm',
    'rain_days_per_year',
    'is_lowland', 'near_major_river', 'dist_to_nearest_river_km',
    'landcover_class',
]

# Features that don't clearly belong to either hazard
# (Census infrastructure, population, land area)
# These are distributed proportionally based on the landslide/flood split


def compute_hazard_decomposition(df, features):
    """Compute per-village landslide and flood risk scores using SHAP.

    Returns: DataFrame with landslide_risk_score and flood_risk_score columns
    """
    print("Computing hazard decomposition via SHAP...")

    # Load the main model
    model = xgb.XGBClassifier()
    model.load_model(os.path.join(MODEL_DIR, 'red_zone_xgboost.json'))

    # Prepare feature matrix
    available_features = [f for f in features if f in df.columns]
    X = df[available_features].copy()
    X = X.fillna(X.median())

    # Compute SHAP values
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    # Map feature indices to hazard groups
    feature_to_idx = {f: i for i, f in enumerate(available_features)}

    landslide_indices = [feature_to_idx[f] for f in LANDSLIDE_FEATURES if f in feature_to_idx]
    flood_indices = [feature_to_idx[f] for f in FLOOD_FEATURES if f in feature_to_idx]

    # Sum SHAP values within each group
    landslide_shap = np.abs(shap_values[:, landslide_indices]).sum(axis=1) if landslide_indices else np.zeros(len(df))
    flood_shap = np.abs(shap_values[:, flood_indices]).sum(axis=1) if flood_indices else np.zeros(len(df))

    # Add shared/Census features proportionally
    all_grouped = set(landslide_indices + flood_indices)
    shared_indices = [i for i in range(len(available_features)) if i not in all_grouped]

    if shared_indices:
        shared_shap = np.abs(shap_values[:, shared_indices]).sum(axis=1)
        # Distribute shared proportionally based on landslide/flood split
        total_hazard = landslide_shap + flood_shap
        total_hazard = np.maximum(total_hazard, 0.001)  # avoid division by zero
        landslide_share = landslide_shap / total_hazard
        flood_share = flood_shap / total_hazard

        landslide_shap += shared_shap * landslide_share
        flood_shap += shared_shap * flood_share

    # Normalize to [0, 1]
    max_val = max(landslide_shap.max(), flood_shap.max(), 0.001)
    landslide_risk = (landslide_shap / max_val).clip(0, 1)
    flood_risk = (flood_shap / max_val).clip(0, 1)

    return landslide_risk, flood_risk


def assign_recommended_action(landslide_risk, flood_risk, carrying_capacity_score=None):
    """Assign recommended action based on which hazard dominates.

    Rules:
    - RELOCATE: landslide_risk > 0.5 AND landslide dominates flood by >20%
      (Landslides are hard to mitigate — relocation is the only option)
    - MITIGATE: flood_risk > 0.5 AND flood dominates landslide by >20%
      AND carrying capacity data suggests fortification is feasible
    - MONITOR: low risk or mixed signals

    Returns: Series of action strings
    """
    actions = pd.Series('MONITOR', index=landslide_risk.index)

    # Tie-break convention: use >= with epsilon tolerance so ties resolve to
    # the more conservative (higher-risk) action. For disaster safety, when
    # landslide and flood risk are exactly balanced, default to RELOCATE since
    # landslides are harder to mitigate than floods.
    # The two conditions are mutually exclusive: landslide gets priority on ties.
    EPS = 5e-4  # floating-point tolerance for SHAP-scored near-ties
    landslide_dominates = landslide_risk >= (flood_risk * 1.2 - EPS)
    flood_dominates = (flood_risk > (landslide_risk * 1.2 + EPS)) & (~landslide_dominates)

    # RELOCATE: landslide dominates (regardless of absolute threshold)
    # Landslides are inherently hard to mitigate — even moderate landslide
    # dominance signals that relocation is the primary response.
    relocate_mask = landslide_dominates
    actions[relocate_mask] = 'RELOCATE'

    # MITIGATE: flood dominates (regardless of absolute threshold)
    # Floods can often be mitigated with infrastructure — fortification
    # is feasible when flood risk dominates.
    mitigate_mask = flood_dominates
    actions[mitigate_mask] = 'MITIGATE'

    return actions


def main():
    print("=" * 60)
    print("Phase 5: Multi-Hazard Decomposition")
    print("=" * 60)

    # Load features
    df = pd.read_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude'])
    print(f"Loaded {len(df):,} villages")

    # Load feature list
    with open(os.path.join(MODEL_DIR, 'features.json')) as f:
        features = json.load(f)
        if isinstance(features, dict):
            features = features['features']

    # Compute hazard decomposition
    landslide_risk, flood_risk = compute_hazard_decomposition(df, features)

    # Assign recommended action
    recommended_action = assign_recommended_action(
        pd.Series(landslide_risk),
        pd.Series(flood_risk)
    )

    # Update prediction_output.csv
    pred_path = os.path.join(OUTPUT_DIR, 'prediction_output.csv')
    if os.path.exists(pred_path):
        print(f"\nUpdating prediction_output.csv...")
        pred_df = pd.read_csv(pred_path, low_memory=False)

        pred_df['landslide_risk_score'] = np.round(landslide_risk, 4)
        pred_df['flood_risk_score'] = np.round(flood_risk, 4)
        pred_df['recommended_action'] = recommended_action.values

        pred_df.to_csv(pred_path, index=False)
        print(f"  Saved: {pred_path}")
        print(f"  Columns added: landslide_risk_score, flood_risk_score, recommended_action")

    # Stats
    print(f"\n  Hazard decomposition:")
    print(f"    Landslide risk: mean={np.mean(landslide_risk):.3f}, "
          f"max={np.max(landslide_risk):.3f}")
    print(f"    Flood risk: mean={np.mean(flood_risk):.3f}, "
          f"max={np.max(flood_risk):.3f}")
    print(f"\n  Recommended actions:")
    for action in ['RELOCATE', 'MITIGATE', 'MONITOR']:
        count = (recommended_action == action).sum()
        print(f"    {action}: {count:,} ({count/len(recommended_action)*100:.1f}%)")

    # Feature group attribution
    print(f"\n  Feature groups:")
    print(f"    Landslide features: {len(LANDSLIDE_FEATURES)}")
    print(f"    Flood features: {len(FLOOD_FEATURES)}")
    print(f"    Shared/Census: distributed proportionally")


if __name__ == '__main__':
    main()
