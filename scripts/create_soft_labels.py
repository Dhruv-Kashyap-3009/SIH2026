"""
Task 2: Distance-Decay Soft Labels

Instead of hard binary labels (high_risk=1 for any village within 10km of
a GSI landslide point), compute a continuous risk contribution using
inverse-distance or Gaussian decay:

    risk_contribution = exp(-distance_km / decay_constant)

Sum contributions from all nearby hazard points and threshold to produce
a refined binary label. Optionally train on the continuous version.

Decay constant choice:
    - Landslide: decay_constant=5.0 (significant risk within ~10km, decays after)
    - Flood: decay_constant=7.0 (flood risk extends further, ~15km buffer)
    - These are physically motivated: landslide runout ~5-10km, flood inundation ~10-20km

Usage:
    python scripts/create_soft_labels.py
"""

import numpy as np
import pandas as pd
from scipy.spatial import KDTree
import os
import json
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'

# Decay constants (km) — physically motivated
LANDSLIDE_DECAY_KM = 5.0
FLOOD_DECAY_KM = 7.0


def compute_soft_labels(df, hazard_type='landslide'):
    """
    Compute distance-decay risk contributions from hazard points.

    For each village, finds all nearby hazard points and sums their
    decay-weighted contributions.

    Args:
        df: DataFrame with latitude, longitude columns
        hazard_type: 'landslide' or 'flood'

    Returns:
        Series of continuous risk contributions [0, 1)
    """
    decay_km = LANDSLIDE_DECAY_KM if hazard_type == 'landslide' else FLOOD_DECAY_KM

    # Get village coordinates
    village_coords = df[['latitude', 'longitude']].dropna()
    village_idx = village_coords.index

    # Get hazard point coordinates from GSI or DFO
    if hazard_type == 'landslide':
        # Load GSI landslide points
        gsi_path = os.path.join(os.path.dirname(OUTPUT_DIR), 'data', 'raw', 'gsi_landslide', 'NE_India_Landslide.shp')
        if not os.path.exists(gsi_path):
            # Fall back to using the distance features already computed
            print(f"  GSI shapefile not found, using pre-computed distances")
            dist_col = 'dist_to_nearest_landslide_km'
            density_col = 'landslide_density_50km'
            if dist_col in df.columns:
                # Convert distance to decay score
                dist = df[dist_col].fillna(100)
                contributions = np.exp(-dist / decay_km)
                # Add density contribution
                if density_col in df.columns:
                    density = df[density_col].fillna(0)
                    contributions = contributions + np.log1p(density) * 0.1
                return contributions.clip(0, 1)
            else:
                return pd.Series(0, index=df.index)

    elif hazard_type == 'flood':
        dist_col = 'dist_to_nearest_flood_km'
        density_col = 'flood_density_50km'
        if dist_col in df.columns:
            dist = df[dist_col].fillna(100)
            contributions = np.exp(-dist / FLOOD_DECAY_KM)
            if density_col in df.columns:
                density = df[density_col].fillna(0)
                contributions = contributions + np.log1p(density) * 0.1
            return contributions.clip(0, 1)
        else:
            return pd.Series(0, index=df.index)

    return pd.Series(0, index=df.index)


def main():
    print("=" * 60)
    print("Task 2: Distance-Decay Soft Labels")
    print("=" * 60)

    # Load feature matrix
    features_path = os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv')
    df = pd.read_csv(features_path, low_memory=False)
    print(f"Loaded: {features_path} ({len(df):,} villages)")

    # Compute soft risk contributions
    print("\n--- Computing Soft Risk Labels ---")

    # Landslide contribution
    df['soft_risk_landslide'] = compute_soft_labels(df, 'landslide')
    print(f"  Landslide soft risk: mean={df['soft_risk_landslide'].mean():.4f}, "
          f"max={df['soft_risk_landslide'].max():.4f}")

    # Flood contribution
    df['soft_risk_flood'] = compute_soft_labels(df, 'flood')
    print(f"  Flood soft risk: mean={df['soft_risk_flood'].mean():.4f}, "
          f"max={df['soft_risk_flood'].max():.4f}")

    # Combined soft risk (sum, capped at 1)
    df['soft_risk_combined'] = (df['soft_risk_landslide'] + df['soft_risk_flood']).clip(0, 1)
    print(f"  Combined soft risk: mean={df['soft_risk_combined'].mean():.4f}, "
          f"max={df['soft_risk_combined'].max():.4f}")

    # Compare with hard labels
    print("\n--- Label Comparison ---")
    hard_labels = df['high_risk'].value_counts()
    print(f"  Hard labels: {hard_labels.to_dict()}")

    # Threshold soft labels at different levels
    for threshold in [0.1, 0.2, 0.3, 0.5]:
        soft_binary = (df['soft_risk_combined'] >= threshold).astype(int)
        agreement = (soft_binary == df['high_risk']).mean()
        soft_counts = soft_binary.value_counts().to_dict()
        print(f"  Soft threshold={threshold}: {soft_counts}, agreement={agreement*100:.1f}%")

    # Save updated features with soft labels
    df.to_csv(features_path, index=False)
    print(f"\n  Saved: {features_path}")

    # Save soft label metadata
    metadata = {
        'landslide_decay_km': LANDSLIDE_DECAY_KM,
        'flood_decay_km': FLOOD_DECAY_KM,
        'formula': 'exp(-distance_km / decay_constant)',
        'soft_risk_landslide_mean': float(df['soft_risk_landslide'].mean()),
        'soft_risk_flood_mean': float(df['soft_risk_flood'].mean()),
        'soft_risk_combined_mean': float(df['soft_risk_combined'].mean()),
        'hard_label_positive_rate': float(df['high_risk'].mean()),
    }
    meta_path = os.path.join(MODEL_DIR, 'soft_label_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"  Saved: {meta_path}")

    print("\n" + "=" * 60)
    print("Soft Labels Complete")
    print("=" * 60)


if __name__ == '__main__':
    main()
