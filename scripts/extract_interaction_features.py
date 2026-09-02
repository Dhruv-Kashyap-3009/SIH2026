"""
Interaction Feature Extraction — Physically-Motivated Feature Combinations

Adds interaction features that capture known physical hazard mechanisms:
1. slope_x_rainfall: slope_degrees × max_daily_rainfall_mm
   — The actual landslide trigger mechanism: steep slopes + heavy rain = failure
2. twi_proxy: Simplified Topographic Wetness Index
   — TWI = ln(a / tan(β)) where a = upslope contributing area, β = slope
   — Proxy: elevation_inverse × slope_inverse × dist_to_river_inverse
   — Low elevation + gentle slope + near river = high wetness = flood prone

These features help the susceptibility model capture non-linear hazard
mechanisms that single features miss, potentially improving spatial
generalization by encoding known physics rather than data-driven patterns.

Usage:
    python scripts/extract_interaction_features.py
"""

import numpy as np
import pandas as pd
import os
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'processed')


def compute_slope_x_rainfall(df):
    """
    Landslide trigger interaction: slope × rainfall intensity.

    Physical rationale: Landslides are triggered when soil on steep slopes
    becomes saturated by intense rainfall. Neither slope alone nor rainfall
    alone is sufficient — the INTERACTION captures the actual failure mechanism.

    Units: degrees × mm/day (interpretation: "rainfall intensity per unit steepness")
    """
    slope = df['slope_degrees'].fillna(0)
    rainfall = df['max_daily_rainfall_mm'].fillna(0)
    return slope * rainfall


def compute_twi_proxy(df):
    """
    Simplified Topographic Wetness Index (TWI) proxy.

    Full TWI = ln(a / tan(β)) where:
      a = upslope contributing area (requires flow accumulation from DEM)
      β = local slope angle

    Since full flow-accumulation computation requires PyGeoHydro or similar
    heavy libraries, we use a simplified proxy based on available features:

    twi_proxy = (1 / (1 + elevation_m/1000)) × (1 / (1 + slope_degrees)) × (1 / (1 + dist_to_nearest_river_km))

    This captures the three key TWI components:
    - Low elevation → more water accumulation
    - Gentle slope → water doesn't drain quickly
    - Near river → in a drainage convergence zone

    Range: (0, 1), higher = wetter/more flood-prone

    NOTE: This is a simplification. Full TWI requires D8 flow direction
    from the DEM and is computationally expensive at 44K village scale.
    """
    elevation = df['elevation_m'].fillna(df['elevation_m'].median())
    slope = df['slope_degrees'].fillna(df['slope_degrees'].median())
    dist_river = df['dist_to_nearest_river_km'].fillna(df['dist_to_nearest_river_km'].median())

    # Inverse contributions (normalized to [0,1] range)
    elev_inv = 1.0 / (1.0 + elevation / 1000.0)      # Low elevation → high wetness
    slope_inv = 1.0 / (1.0 + slope)                     # Gentle slope → high wetness
    river_inv = 1.0 / (1.0 + dist_river)                # Near river → high wetness

    # Combined TWI proxy (product of the three components)
    twi_proxy = elev_inv * slope_inv * river_inv

    return twi_proxy


def add_interaction_features(df):
    """
    Add all interaction features to the DataFrame.
    Returns the updated DataFrame and list of new feature names.
    """
    new_features = []

    # 1. Slope × Rainfall (landslide trigger)
    df['slope_x_rainfall'] = compute_slope_x_rainfall(df)
    new_features.append('slope_x_rainfall')

    # 2. TWI proxy (flood susceptibility)
    df['twi_proxy'] = compute_twi_proxy(df)
    new_features.append('twi_proxy')

    print(f"  Added {len(new_features)} interaction features:")
    for f in new_features:
        print(f"    {f}: mean={df[f].mean():.4f}, std={df[f].std():.4f}")

    return df, new_features


def main():
    print("=" * 60)
    print("Interaction Feature Extraction")
    print("=" * 60)

    # Load feature matrix
    features_path = os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv')
    print(f"Loading: {features_path}")
    df = pd.read_csv(features_path, low_memory=False)
    print(f"  Villages: {len(df):,}, Columns: {len(df.columns)}")

    # Check required source features exist
    required = ['slope_degrees', 'max_daily_rainfall_mm', 'elevation_m',
                'dist_to_nearest_river_km']
    missing = [f for f in required if f not in df.columns]
    if missing:
        print(f"  ❌ Missing required features: {missing}")
        return

    # Add interaction features
    df, new_features = add_interaction_features(df)

    # Save updated feature matrix
    df.to_csv(features_path, index=False)
    print(f"\n  Saved updated feature matrix: {features_path}")
    print(f"  Total columns: {len(df.columns)} (was {len(df.columns) - len(new_features)})")

    # Verify features are valid
    for f in new_features:
        nans = df[f].isna().sum()
        zeros = (df[f] == 0).sum()
        print(f"  {f}: NaN={nans}, zeros={zeros}, "
              f"range=[{df[f].min():.4f}, {df[f].max():.4f}]")


if __name__ == '__main__':
    main()
