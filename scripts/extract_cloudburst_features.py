"""
Extract Cloudburst Risk Features

Cloudbursts are extreme short-duration rainfall events (>100mm in 24 hours).
This module derives cloudburst risk features from existing IMD rainfall data
without requiring a new dataset.

Architecture: Pluggable module following the same pattern as extract_flood_features.py.
To add a new hazard type:
  1. Create extract_<hazard>_features.py
  2. Extract features per village from available data
  3. Add them to combine_features.py
  4. Create update_labels_<hazard>.py if historical event data exists
  5. Retrain the model

Cloudburst risk proxy features (derived from existing IMD rainfall):
  - max_daily_rainfall_mm: Already in feature set — primary cloudburst signal
  - cloudburst_risk_score: Composite of extreme rainfall indicators
  - rain_days_per_year: High rain day count correlates with cloudburst exposure

This is architecturally pluggable — the same extract → combine → label → train
pattern applies to coastal erosion (using tidal/coastline data), earthquake
(seismic zone data), etc.
"""

import os
import sys
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'processed')


def compute_cloudburst_features(df):
    """
    Compute cloudburst risk features from existing rainfall columns.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain: max_daily_rainfall_mm, mean_daily_rainfall_mm,
        rain_days_per_year, rainfall_90th_percentile_mm

    Returns
    -------
    pd.DataFrame with new columns:
      - cloudburst_risk_score (0-1): Composite cloudburst vulnerability
      - extreme_rainfall_days: Days with >100mm (proxy from 90th percentile)
    """
    df = df.copy()

    # ── Feature 1: Cloudburst Risk Score ──────────────────────────────────
    # A cloudburst is defined as >100mm in 24 hours by IMD.
    # Proxy: how much of the rainfall is concentrated in extreme events.

    max_rain = df['max_daily_rainfall_mm'].fillna(0)
    mean_rain = df['mean_daily_rainfall_mm'].fillna(1)  # avoid /0
    p90_rain = df['rainfall_90th_percentile_mm'].fillna(0)

    # Concentration index: ratio of max to mean rainfall
    # High concentration = more cloudburst-prone
    concentration = (max_rain / mean_rain).clip(0, 20)

    # Extreme rainfall ratio: how much of total is in top events
    extreme_ratio = (p90_rain / (mean_rain * 365 + 1)).clip(0, 5)

    # Normalize to 0-1
    conc_norm = (concentration - concentration.min()) / (concentration.max() - concentration.min() + 1e-8)
    extreme_norm = (extreme_ratio - extreme_ratio.min()) / (extreme_ratio.max() - extreme_ratio.min() + 1e-8)

    # Weighted composite (concentration matters more for cloudbursts)
    df['cloudburst_risk_score'] = (0.6 * conc_norm + 0.4 * extreme_norm).round(4)

    # ── Feature 2: Extreme Rainfall Days ──────────────────────────────────
    # Approximate number of days with >100mm from the distribution
    rain_days = df['rain_days_per_year'].fillna(0)
    # Assume top 5% of rain days contribute most cloudburst risk
    df['extreme_rainfall_days'] = (rain_days * 0.05).round(0).astype(int)

    return df


def main():
    print("\n" + "="*60)
    print("  🌧️ CLOUDBURST FEATURE EXTRACTION")
    print("="*60)

    features_path = os.path.join(DATA_DIR, 'ne_india_village_features.csv')
    if not os.path.exists(features_path):
        print(f"  ❌ Features file not found: {features_path}")
        return

    print(f"\n  Loading village features...")
    df = pd.read_csv(features_path, low_memory=False)
    print(f"  ✅ Loaded {len(df):,} villages")

    # Check required columns
    required = ['max_daily_rainfall_mm', 'mean_daily_rainfall_mm',
                'rain_days_per_year', 'rainfall_90th_percentile_mm']
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"  ⚠️  Missing columns (cloudburst features will be NaN): {missing}")

    # Compute features
    print(f"  Computing cloudburst risk features...")
    df = compute_cloudburst_features(df)

    # Summary
    print(f"\n  Cloudburst Risk Score distribution:")
    print(f"    Min:    {df['cloudburst_risk_score'].min():.4f}")
    print(f"    Mean:   {df['cloudburst_risk_score'].mean():.4f}")
    print(f"    Median: {df['cloudburst_risk_score'].median():.4f}")
    print(f"    Max:    {df['cloudburst_risk_score'].max():.4f}")

    high_risk = (df['cloudburst_risk_score'] > 0.7).sum()
    print(f"\n  High cloudburst risk (>0.7): {high_risk:,} villages ({high_risk/len(df)*100:.1f}%)")

    # Save
    output_path = os.path.join(DATA_DIR, 'ne_india_village_features.csv')
    df.to_csv(output_path, index=False)
    print(f"\n  💾 Saved to {output_path}")

    print(f"\n  NOTE: These features are ready for inclusion in the model.")
    print(f"  To integrate: update combine_features.py and retrain with")
    print(f"  extract_cloudburst_features.py features added to the feature set.")
    print("="*60 + "\n")


if __name__ == '__main__':
    main()
