"""
Prediction Script: Load trained model and predict risk zones for NE India villages.

Outputs per-village records with:
  - habitation_id        Stable Census/SHRUG village code
  - district / state     Administrative metadata
  - risk_score           Model probability (0.0–1.0)
  - predicted_risk_zone  GREEN / ORANGE / RED
  - priority_score       Risk × vulnerability
  - priority_level       HIGH / MEDIUM / LOW
  - top_factors          Top 5 SHAP contributors (JSON list)
  - low_confidence       True if elevation_m or landcover_class is missing
  - predicted_at         ISO timestamp of this run
  - model_version        Hash of the trained model file

Usage:
    python scripts/predict.py                        # Predict all villages
    python scripts/predict.py --state Assam           # Predict one state
    python scripts/predict.py --village "Betanipam"   # Predict one village
    python scripts/predict.py --top 20                # Show top N highest risk
    python scripts/predict.py --save results.csv      # Save to CSV
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import json
import os
import sys
import hashlib
import argparse
from datetime import datetime, timezone

MODEL_DIR = 'models'
DATA_DIR = 'data/processed'

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _model_version():
    """Compute a short hash of the trained model file for versioning."""
    path = os.path.join(MODEL_DIR, 'red_zone_xgboost.json')
    with open(path, 'rb') as f:
        h = hashlib.sha256(f.read()).hexdigest()[:12]
    return f"v1.0-{h}"


def _format_value(feature, value):
    """Human-readable value for a feature."""
    if pd.isna(value):
        return "N/A"
    if 'km' in feature:
        return f"{value:.1f} km"
    if 'mm' in feature:
        return f"{value:.1f} mm"
    if 'degrees' in feature:
        return f"{value:.1f}°"
    if 'density' in feature:
        return f"{int(value)}"
    if 'hectares' in feature:
        return f"{value:.0f} ha"
    if 'hours' in feature:
        return f"{value:.1f} hrs"
    return f"{value:.2f}"


# ─── Load Model ──────────────────────────────────────────────────────────────

def load_model():
    model = xgb.XGBClassifier()
    model.load_model(os.path.join(MODEL_DIR, 'red_zone_xgboost.json'))

    with open(os.path.join(MODEL_DIR, 'features.json')) as f:
        features = json.load(f)
        if isinstance(features, dict):
            features = features['features']

    with open(os.path.join(MODEL_DIR, 'model_metadata.json')) as f:
        metadata = json.load(f)

    return model, features, metadata


# ─── Load Data ───────────────────────────────────────────────────────────────

def load_data():
    df = pd.read_csv(os.path.join(DATA_DIR, 'ne_india_village_features.csv'), low_memory=False)
    return df


# ─── Add habitation_id ──────────────────────────────────────────────────────

def add_habitation_id(df):
    """Create stable Census 2011 village identifier."""
    df = df.copy()  # defragment for performance
    df['habitation_id'] = (
        df['State Code'].astype(str) + '-' +
        df['District Code'].astype(str) + '-' +
        df['Sub District Code'].astype(str) + '-' +
        df['Village Code'].astype(str)
    )
    return df


# ─── Add low_confidence flag ────────────────────────────────────────────────

def add_low_confidence(df):
    """Flag villages missing key source data used as model features."""
    missing_elevation = df['elevation_m'].isna()
    missing_landcover = df['landcover_class'].isna()
    df['low_confidence'] = missing_elevation | missing_landcover
    return df


# ─── Compute per-village SHAP top factors ───────────────────────────────────

def compute_top_factors(model, X, features, n_top=5):
    """Compute per-village top SHAP contributors and return as a list of JSON strings."""
    print("    Computing per-village SHAP values...")
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    top_factors_list = []
    abs_shap = np.abs(shap_values)

    for i in range(len(X)):
        # Get indices of top N features by absolute SHAP
        top_idx = np.argsort(abs_shap[i])[-n_top:][::-1]

        factors = []
        for rank, fi in enumerate(top_idx):
            feat_name = features[fi]
            feat_val = X.iloc[i, fi]
            shap_val = shap_values[i, fi]

            # Impact bucketing: rank 1–2 = high, 3 = medium, 4–5 = low
            if rank < 2:
                impact = "high"
            elif rank < 3:
                impact = "medium"
            else:
                impact = "low"

            factors.append({
                "feature": feat_name,
                "value": _format_value(feat_name, feat_val),
                "impact": impact,
                "shap_value": round(float(shap_val), 4)
            })

        top_factors_list.append(json.dumps(factors))

    return top_factors_list


# ─── Predict ─────────────────────────────────────────────────────────────────

def predict_all(model, features, df):
    """Predict risk for all villages."""
    X = df[features].copy()

    # Handle NaN
    X = X.fillna(X.median())

    # Predict
    risk_probabilities = model.predict_proba(X)[:, 1]
    df = df.copy()
    df['model_risk_score'] = risk_probabilities
    df['risk_score'] = risk_probabilities  # alias for frontend

    # Assign risk zone — must match train_model.py thresholds exactly
    # train_model.py: GREEN<0.4, ORANGE 0.4-0.7, RED>=0.7
    df['predicted_risk_zone'] = 'GREEN'
    df.loc[df['risk_score'] >= 0.7, 'predicted_risk_zone'] = 'RED'
    df.loc[(df['risk_score'] >= 0.4) & (df['risk_score'] < 0.7), 'predicted_risk_zone'] = 'ORANGE'

    # ── Relocation Timeline (PS-aligned tiers) ──────────────────────────────
    # IMMEDIATE: risk_score >= 0.85 AND (in disaster zone OR high density)
    # SHORT_TERM: risk_score >= 0.7 but not IMMEDIATE
    # MEDIUM_TERM: ORANGE zone with score 0.55-0.7
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

    df['relocation_timeline'] = 'MONITOR'
    df.loc[
        (df['risk_score'] >= 0.7) & ~(in_disaster | high_density),
        'relocation_timeline'] = 'SHORT_TERM'
    df.loc[
        (df['risk_score'] >= 0.55) & (df['risk_score'] < 0.7),
        'relocation_timeline'] = 'MEDIUM_TERM'
    df.loc[
        (df['risk_score'] >= 0.85) & (in_disaster | high_density),
        'relocation_timeline'] = 'IMMEDIATE'
    df.loc[
        (df['risk_score'] >= 0.7) & (df['risk_score'] < 0.85) & (in_disaster | high_density),
        'relocation_timeline'] = 'IMMEDIATE'

    # Compute per-village SHAP top factors
    df['top_factors'] = compute_top_factors(model, X, features, n_top=5)

    return df, X


# ─── Display Results ─────────────────────────────────────────────────────────

def print_summary(df):
    """Print prediction summary."""
    print("\n" + "="*70)
    print("  🎯 RED ZONE PREDICTION RESULTS")
    print("="*70)

    print(f"\n  Total villages assessed: {len(df):,}")

    # Zone distribution
    zone_counts = df['predicted_risk_zone'].value_counts()
    print(f"\n  Risk Zone Distribution:")
    for zone in ['RED', 'ORANGE', 'GREEN']:
        count = zone_counts.get(zone, 0)
        pct = count / len(df) * 100
        emoji = {'RED': '🔴', 'ORANGE': '🟠', 'GREEN': '🟢'}[zone]
        print(f"    {emoji} {zone:8s}: {count:6,} villages ({pct:5.1f}%)")

    # Confidence
    low_conf = df['low_confidence'].sum()
    print(f"\n  Data Confidence:")
    print(f"    ✅ Full confidence: {(len(df)-low_conf):,} villages")
    print(f"    ⚠️  Partial data:   {low_conf:,} villages")

    # State breakdown
    print(f"\n  Risk by State:")
    print(f"    {'State':<25s} {'RED':>8s} {'ORANGE':>8s} {'GREEN':>8s} {'RED%':>8s}")
    print(f"    {'-'*57}")
    state_col = 'State Name' if 'State Name' in df.columns else 'State'
    for state in sorted(df[state_col].unique()):
        state_df = df[df[state_col] == state]
        red = (state_df['predicted_risk_zone'] == 'RED').sum()
        orange = (state_df['predicted_risk_zone'] == 'ORANGE').sum()
        green = (state_df['predicted_risk_zone'] == 'GREEN').sum()
        red_pct = red / len(state_df) * 100
        print(f"    {state:<25s} {red:>8,} {orange:>8,} {green:>8,} {red_pct:>7.1f}%")

    # Top 10 highest risk villages
    print(f"\n  🔴 Top 10 Highest Risk Villages:")
    state_c = 'State Name' if 'State Name' in df.columns else 'State'
    dist_c = 'District Name' if 'District Name' in df.columns else 'District'
    vill_c = 'Village Name' if 'Village Name' in df.columns else 'Village'
    print(f"    {'State':<20s} {'District':<20s} {'Village':<25s} {'Score':>8s}")
    print(f"    {'-'*73}")

    top10 = df.nlargest(10, 'risk_score')
    for _, row in top10.iterrows():
        print(f"    {str(row[state_c])[:20]:<20s} {str(row[dist_c])[:20]:<20s} "
              f"{str(row[vill_c])[:25]:<25s} {row['risk_score']:>7.3f}")

    # Top 10 safest villages
    print(f"\n  🟢 Top 10 Safest Villages:")
    print(f"    {'State':<20s} {'District':<20s} {'Village':<25s} {'Score':>8s}")
    print(f"    {'-'*73}")

    bottom10 = df.nsmallest(10, 'risk_score')
    for _, row in bottom10.iterrows():
        print(f"    {str(row[state_c])[:20]:<20s} {str(row[dist_c])[:20]:<20s} "
              f"{str(row[vill_c])[:25]:<25s} {row['risk_score']:>7.3f}")

    # Show top factors for #1 village
    top1 = df.nlargest(1, 'risk_score').iloc[0]
    print(f"\n  📋 Top Factors for Highest-Risk Village:")
    print(f"    {top1.get('Village Name', 'N/A')} ({top1.get('District Name', 'N/A')})")
    factors = json.loads(top1['top_factors'])
    for f in factors:
        arrow = '↑' if f['shap_value'] > 0 else '↓'
        print(f"    {arrow} {f['feature']}: {f['value']} ({f['impact']})")

    print("\n" + "="*70)


def predict_village(model, features, df, village_name):
    """Predict risk for a specific village."""
    village_col = 'Village Name' if 'Village Name' in df.columns else 'Village'
    matches = df[df[village_col].str.contains(village_name, case=False, na=False)]

    if len(matches) == 0:
        print(f"\n  ❌ No village found matching '{village_name}'")
        return

    print(f"\n  🔍 Found {len(matches)} village(s) matching '{village_name}':")

    # Precompute global medians for consistent imputation with training pipeline
    global_medians = df[features].median()

    for _, row in matches.iterrows():
        print(f"\n  {'─'*50}")
        vn = row.get('Village Name', row.get('Village', 'N/A'))
        dn = row.get('District Name', row.get('District', 'N/A'))
        sn = row.get('State Name', row.get('State', 'N/A'))
        hid = row.get('habitation_id', 'N/A')
        print(f"  Village:       {vn}")
        print(f"  District:      {dn}")
        print(f"  State:         {sn}")
        print(f"  Habitation ID: {hid}")
        print(f"  Coordinates:   {row['latitude']:.4f}°N, {row['longitude']:.4f}°E")
        print(f"  Low Confidence: {'Yes' if row.get('low_confidence', False) else 'No'}")
        print(f"  {'─'*50}")

        # Key features
        print(f"  Key Features:")
        key_features = [
            ('elevation_m', 'Elevation'),
            ('slope_degrees', 'Slope'),
            ('max_daily_rainfall_mm', 'Max Rainfall'),
            ('dist_to_nearest_landslide_km', 'Dist to Landslide'),
            ('landslide_density_50km', 'Landslide Density (50km)'),
        ]

        for feat, label in key_features:
            if feat in row.index:
                val = row[feat]
                if pd.notna(val):
                    print(f"    {label:<30s}: {val:>10.2f}")

        # Prediction — use global medians for imputation (matches predict_all)
        X_row = row[features].fillna(global_medians).values.reshape(1, -1).astype(float)

        prob = model.predict_proba(X_row)[0][1]
        # Thresholds must match train_model.py: GREEN<0.4, ORANGE 0.4-0.7, RED>=0.7
        zone = 'RED' if prob >= 0.7 else 'ORANGE' if prob >= 0.4 else 'GREEN'

        print(f"\n  🎯 PREDICTION:")
        emoji = '🔴' if prob >= 0.7 else '🟠' if prob >= 0.4 else '🟢'
        print(f"    Risk Score: {prob:.3f} {emoji}")
        print(f"    Risk Zone:  {zone}")

        # Show top factors
        if 'top_factors' in row.index and pd.notna(row['top_factors']):
            factors = json.loads(row['top_factors'])
            print(f"\n  📋 Top Risk Factors:")
            for f in factors:
                arrow = '↑' if f['shap_value'] > 0 else '↓'
                print(f"    {arrow} {f['feature']}: {f['value']} ({f['impact']})")

        if prob >= 0.7:
            print(f"\n    ⚠️  HIGH RISK — Immediate relocation recommended")
        elif prob >= 0.4:
            print(f"\n    ⚠️  MEDIUM RISK — Monitor and plan")
        else:
            print(f"\n    ✅ LOW RISK — Safe for habitation")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Red Zone Prediction')
    parser.add_argument('--state', type=str, help='Filter by state name')
    parser.add_argument('--village', type=str, help='Search village by name')
    parser.add_argument('--top', type=int, default=0, help='Show top N highest risk')
    parser.add_argument('--save', type=str, help='Save results to CSV')
    args = parser.parse_args()

    print("\n  Loading model...")
    model, features, metadata = load_model()
    model_ver = _model_version()
    print(f"  ✅ Model loaded ({metadata['n_features']} features, {metadata['model_type']}, {model_ver})")

    print("  Loading village data...")
    df = load_data()
    print(f"  ✅ Loaded {len(df):,} villages")

    # ── Add habitation_id ────────────────────────────────────────────────
    print("  Adding habitation_id...")
    df = add_habitation_id(df)
    print(f"  ✅ habitation_id: {df['habitation_id'].nunique():,} unique IDs")

    # ── Add low_confidence ───────────────────────────────────────────────
    print("  Computing data confidence flags...")
    df = add_low_confidence(df)
    n_low = df['low_confidence'].sum()
    print(f"  ✅ low_confidence: {n_low:,} villages ({n_low/len(df)*100:.1f}%)")

    # Filter by state if specified
    if args.state:
        sc = 'State Name' if 'State Name' in df.columns else 'State'
        df = df[df[sc].str.contains(args.state, case=False, na=False)]
        if len(df) == 0:
            print(f"\n  ❌ No villages found for state '{args.state}'")
            return
        print(f"  📍 Filtered to {len(df):,} villages in {args.state}")

    # Village-specific prediction
    if args.village:
        predict_village(model, features, df, args.village)
        return

    # ── Predict all ──────────────────────────────────────────────────────
    print("  Running predictions + per-village SHAP...")
    df, X = predict_all(model, features, df)
    print("  ✅ Predictions complete")

    # ── Add timestamps + model version ───────────────────────────────────
    predicted_at = datetime.now(timezone.utc).isoformat()
    df['predicted_at'] = predicted_at
    df['model_version'] = model_ver

    # ── Ensure district/state columns are present ────────────────────────
    # (they already exist as 'District Name' / 'State Name' / 'Village Name')
    # Rename to cleaner names for frontend consumption
    df['district'] = df['District Name']
    df['state'] = df['State Name']
    df['village'] = df['Village Name']
    # Drop redundant originals to keep output clean
    df.drop(columns=['model_prediction'], errors='ignore', inplace=True)

    # Summary
    print_summary(df)

    # Top N
    if args.top > 0:
        print(f"\n  🔴 Top {args.top} Highest Risk Villages:")
        print(f"    {'#':>4s} {'State':<20s} {'District':<20s} {'Village':<25s} {'ID':<25s} {'Score':>8s}")
        print(f"    {'-'*102}")

        top = df.nlargest(args.top, 'risk_score')
        for i, (_, row) in enumerate(top.iterrows(), 1):
            sc = 'State Name' if 'State Name' in row.index else 'State'
            dc = 'District Name' if 'District Name' in row.index else 'District'
            vc = 'Village Name' if 'Village Name' in row.index else 'Village'
            print(f"    {i:>4d} {str(row[sc])[:20]:<20s} {str(row[dc])[:20]:<20s} "
                  f"{str(row[vc])[:25]:<25s} {str(row['habitation_id']):<25s} {row['risk_score']:>7.3f}")

    # Save
    if args.save:
        df.to_csv(args.save, index=False)
        print(f"\n  💾 Results saved to {args.save}")
        print(f"     predicted_at: {predicted_at}")
        print(f"     model_version: {model_ver}")
        print(f"     rows: {len(df):,}")
        print(f"     columns: {len(df.columns)}")

    print()


if __name__ == '__main__':
    main()
