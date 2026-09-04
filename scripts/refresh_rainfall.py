"""
Refresh Rainfall Data — Real-Time Updating Demo Hook

This script demonstrates the "dynamically updates in real time" capability:
1. Accepts a CSV with updated rainfall data (village_id, updated_rainfall_columns)
2. Merges new rainfall values into the feature matrix
3. Re-scores only affected villages using the existing trained model (no retraining)
4. Reports which villages changed risk zone as a result

Usage:
    python scripts/refresh_rainfall.py                          # Use built-in demo data
    python scripts/refresh_rainfall.py --input updated_rain.csv # Use custom CSV
    python scripts/refresh_rainfall.py --demo                   # Simulate rainfall spike in Assam
"""

import os
import sys
import json
import hashlib
import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import argparse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE_DIR, 'models')
DATA_DIR = os.path.join(BASE_DIR, 'data', 'processed')


def load_model_and_features():
    model = xgb.XGBClassifier()
    model.load_model(os.path.join(MODEL_DIR, 'red_zone_xgboost.json'))
    with open(os.path.join(MODEL_DIR, 'features.json')) as f:
        features = json.load(f)
        if isinstance(features, dict):
            features = features['features']
    return model, features


def load_current_predictions():
    path = os.path.join(DATA_DIR, 'prediction_output.csv')
    df = pd.read_csv(path, low_memory=False)
    return df


def simulate_rainfall_spike(df):
    """
    Simulate a realistic monsoon rainfall spike in Assam.
    Increases max_daily_rainfall_mm and mean_daily_rainfall_mm for
    villages in Assam districts known for flooding.
    """
    target_districts = ['Dhemaji', 'Tinsukia', 'Dibrugarh', 'Sivasagar',
                        'Jorhat', 'Morigaon', 'Lakhimpur', 'Nagaon',
                        'Dhubri', 'Kokrajhar', 'Barpeta', 'Nalbari']

    mask = df['District Name'].isin(target_districts)
    affected = mask.sum()

    # Simulate 40-80% increase in max daily rainfall
    np.random.seed(42)
    spike_factor = np.random.uniform(1.4, 1.8, size=affected)

    df = df.copy()
    if 'max_daily_rainfall_mm' in df.columns:
        df.loc[mask, 'max_daily_rainfall_mm'] = df.loc[mask, 'max_daily_rainfall_mm'] * spike_factor
    if 'mean_daily_rainfall_mm' in df.columns:
        df.loc[mask, 'mean_daily_rainfall_mm'] = df.loc[mask, 'mean_daily_rainfall_mm'] * (spike_factor * 0.8)
    if 'rain_days_per_year' in df.columns:
        df.loc[mask, 'rain_days_per_year'] = df.loc[mask, 'rain_days_per_year'] + np.random.randint(5, 20, size=affected)
    if 'rainfall_90th_percentile_mm' in df.columns:
        df.loc[mask, 'rainfall_90th_percentile_mm'] = df.loc[mask, 'rainfall_90th_percentile_mm'] * (spike_factor * 0.9)

    return df, mask


def refresh(input_csv=None, demo=False):
    """Main refresh logic."""
    print("\n" + "="*60)
    print("  🔄 RAINFALL REFRESH — Real-Time Update Demo")
    print("="*60)

    model, features = load_model_and_features()
    df = load_current_predictions()
    print(f"\n  📊 Loaded {len(df):,} villages with current predictions")

    # Ensure habitation_id
    if 'habitation_id' not in df.columns:
        df['habitation_id'] = (
            df['State Code'].astype(str) + '-' +
            df['District Code'].astype(str) + '-' +
            df['Sub District Code'].astype(str) + '-' +
            df['Village Code'].astype(str)
        )

    # Save old zones
    old_zones = df['predicted_risk_zone'].copy()
    old_timeline = df['relocation_timeline'].copy() if 'relocation_timeline' in df.columns else pd.Series(['MONITOR'] * len(df))

    # Save old risk_scores for unaffected villages (to avoid drift)
    old_risk_scores = df['risk_score'].copy()

    # Pre-compute medians BEFORE any modification (consistent with training)
    global_medians = df[features].median()

    # Apply new rainfall data
    if input_csv and os.path.exists(input_csv):
        print(f"\n  📥 Loading updated rainfall from: {input_csv}")
        new_data = pd.read_csv(input_csv, low_memory=False)
        merge_col = 'habitation_id' if 'habitation_id' in new_data.columns else None
        if merge_col:
            rainfall_cols = [c for c in new_data.columns if 'rainfall' in c.lower() or 'rain' in c.lower()]
            df = df.drop(columns=[c for c in rainfall_cols if c in df.columns], errors='ignore')
            df = df.merge(new_data[[merge_col] + rainfall_cols], on=merge_col, how='left')
            affected_mask = df[merge_col].isin(new_data[merge_col])
        else:
            print("  ⚠️  No habitation_id in input — using all villages")
            affected_mask = pd.Series([True] * len(df))
    elif demo:
        print("\n  🎭 DEMO MODE: Simulating monsoon rainfall spike in Assam")
        df, affected_mask = simulate_rainfall_spike(df)
    else:
        print("  ❌ No input provided. Use --input <csv> or --demo")
        return

    # Re-score ONLY affected villages (preserve old scores for unaffected)
    affected_idx = df.index[affected_mask]
    print(f"\n  ⚡ Re-scoring {len(affected_idx):,} affected villages (preserving {len(df)-len(affected_idx):,} unaffected)...")

    X_affected = df.loc[affected_idx, features].fillna(global_medians)
    new_probs = model.predict_proba(X_affected)[:, 1]

    # Only update affected villages
    df.loc[affected_idx, 'risk_score'] = new_probs
    df.loc[affected_idx, 'model_risk_score'] = new_probs
    # Unaffected villages keep their old risk_score
    df.loc[~affected_mask, 'risk_score'] = old_risk_scores[~affected_mask]
    df.loc[~affected_mask, 'model_risk_score'] = old_risk_scores[~affected_mask]

    # Update zones (canonical thresholds: GREEN<0.4, ORANGE 0.4-0.9, RED>=0.9
    # — RED cutoff raised 0.7 -> 0.9 on user request; must match predict.py)
    df['predicted_risk_zone'] = 'GREEN'
    df.loc[df['risk_score'] >= 0.9, 'predicted_risk_zone'] = 'RED'
    df.loc[(df['risk_score'] >= 0.4) & (df['risk_score'] < 0.9), 'predicted_risk_zone'] = 'ORANGE'

    # Update relocation timeline
    in_disaster = (df.get('gsi_landslide_zone', 0) == 1) | (df.get('emdat_disaster_zone', 0) == 1)
    pop_col = 'Total Population of Village'
    if pop_col in df.columns:
        pop = df[pop_col].fillna(0)
        area_col = 'Total Geographical Area (in Hectares)'
        if area_col in df.columns:
            area = df[area_col].replace(0, 1).fillna(1)
            density = pop / area
            high_density = density > density.quantile(0.8)
        else:
            high_density = pop > pop.quantile(0.8)
    else:
        high_density = False

    # Demo path: this script re-scores with the HISTORICAL model only, so its
    # zones AND timeline are both derived from risk_score with the canonical
    # 0.9/0.4 cutoffs (kept mutually consistent here). After a real rainfall
    # refresh, re-run scripts/refresh_predictions.py + the export chain so the
    # canonical susceptibility-based timeline is restored.
    df['relocation_timeline'] = 'MONITOR'
    df.loc[(df['risk_score'] >= 0.4) & (df['risk_score'] < 0.9), 'relocation_timeline'] = 'MEDIUM_TERM'
    df.loc[(df['risk_score'] >= 0.9) & ~(in_disaster | high_density), 'relocation_timeline'] = 'SHORT_TERM'
    df.loc[(df['risk_score'] >= 0.9) & (in_disaster | high_density), 'relocation_timeline'] = 'IMMEDIATE'

    # Add timestamp
    df['predicted_at'] = datetime.now(timezone.utc).isoformat()

    # ── Detect zone changes ───────────────────────────────────────────────
    new_zones = df['predicted_risk_zone']
    new_timeline = df['relocation_timeline']

    zone_changed = old_zones != new_zones
    timeline_changed = old_timeline != new_timeline
    changed = zone_changed | timeline_changed

    n_zone_changed = zone_changed.sum()
    n_timeline_changed = timeline_changed.sum()
    n_changed = changed.sum()

    print(f"\n  📊 RESULTS:")
    print(f"     Zone changes:     {n_zone_changed:,} villages")
    print(f"     Timeline changes: {n_timeline_changed:,} villages")
    print(f"     Total changed:    {n_changed:,} villages")

    # Show specific changes
    if n_zone_changed > 0:
        changed_df = df[zone_changed][['habitation_id', 'Village Name', 'District Name',
                                       'predicted_risk_zone', 'risk_score']].copy()
        changed_df['old_zone'] = old_zones[zone_changed].values
        changed_df = changed_df.nlargest(20, 'risk_score')

        print(f"\n  🔴 Top 20 Zone Changes (worst cases):")
        print(f"     {'Village':<25s} {'District':<20s} {'Old':>8s} → {'New':>8s} {'Score':>8s}")
        print(f"     {'-'*73}")
        for _, row in changed_df.iterrows():
            print(f"     {str(row['Village Name'])[:25]:<25s} "
                  f"{str(row['District Name'])[:20]:<20s} "
                  f"{row['old_zone']:>8s} → {row['predicted_risk_zone']:>8s} "
                  f"{row['risk_score']:>7.3f}")

    # ── Save updated predictions ──────────────────────────────────────────
    output_path = os.path.join(DATA_DIR, 'prediction_output.csv')
    df.to_csv(output_path, index=False)
    print(f"\n  💾 Updated predictions saved to: prediction_output.csv")

    # Print CHANGED lines for the backend to parse
    if n_zone_changed > 0:
        for _, row in df[zone_changed].head(50).iterrows():
            print(f"  CHANGED: {row['Village Name']} ({row['District Name']}) "
                  f"{old_zones[row.name]} → {row['predicted_risk_zone']} "
                  f"(score={row['risk_score']:.3f})")

    print(f"\n  ✅ Refresh complete at {datetime.now(timezone.utc).isoformat()}")
    print("="*60 + "\n")

    return df


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Refresh rainfall data and re-score villages')
    parser.add_argument('--input', type=str, help='CSV with updated rainfall columns')
    parser.add_argument('--demo', action='store_true', help='Simulate monsoon spike in Assam')
    args = parser.parse_args()

    refresh(input_csv=args.input, demo=args.demo)
