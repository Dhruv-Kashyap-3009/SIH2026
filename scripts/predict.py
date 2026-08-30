"""
Prediction Script: Load trained model and predict risk zones for NE India villages.

Usage:
    python scripts/predict.py                        # Predict all villages
    python scripts/predict.py --state Assam           # Predict one state
    python scripts/predict.py --village "Bomi-koto"   # Predict one village
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import json
import os
import sys
import argparse

MODEL_DIR = 'models'
DATA_DIR = 'data/processed'

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


# ─── Predict ─────────────────────────────────────────────────────────────────

def predict_all(model, features, df):
    """Predict risk for all villages."""
    X = df[features].copy()
    
    # Handle NaN
    X = X.fillna(X.median())
    
    # Predict
    risk_probabilities = model.predict_proba(X)[:, 1]
    df = df.copy()
    df['predicted_risk_score'] = risk_probabilities
    
    # Assign risk zone based on score thresholds
    df['predicted_risk_zone'] = pd.cut(
        df['predicted_risk_score'],
        bins=[-0.01, 0.3, 0.7, 1.01],
        labels=['GREEN', 'ORANGE', 'RED']
    )
    
    return df


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
    
    top10 = df.nlargest(10, 'predicted_risk_score')
    for _, row in top10.iterrows():
        print(f"    {str(row[state_c])[:20]:<20s} {str(row[dist_c])[:20]:<20s} "
              f"{str(row[vill_c])[:25]:<25s} {row['predicted_risk_score']:>7.3f}")
    
    # Top 10 safest villages
    print(f"\n  🟢 Top 10 Safest Villages:")
    print(f"    {'State':<20s} {'District':<20s} {'Village':<25s} {'Score':>8s}")
    print(f"    {'-'*73}")
    
    bottom10 = df.nsmallest(10, 'predicted_risk_score')
    for _, row in bottom10.iterrows():
        print(f"    {str(row[state_c])[:20]:<20s} {str(row[dist_c])[:20]:<20s} "
              f"{str(row[vill_c])[:25]:<25s} {row['predicted_risk_score']:>7.3f}")
    
    print("\n" + "="*70)


def predict_village(model, features, df, village_name):
    """Predict risk for a specific village."""
    village_col = 'Village Name' if 'Village Name' in df.columns else 'Village'
    matches = df[df[village_col].str.contains(village_name, case=False, na=False)]
    
    if len(matches) == 0:
        print(f"\n  ❌ No village found matching '{village_name}'")
        return
    
    print(f"\n  🔍 Found {len(matches)} village(s) matching '{village_name}':")
    
    for _, row in matches.iterrows():
        print(f"\n  {'─'*50}")
        vn = row.get('Village Name', row.get('Village', 'N/A'))
        dn = row.get('District Name', row.get('District', 'N/A'))
        sn = row.get('State Name', row.get('State', 'N/A'))
        print(f"  Village: {vn}")
        print(f"  District: {dn}")
        print(f"  State: {sn}")
        print(f"  Coordinates: {row['latitude']:.4f}°N, {row['longitude']:.4f}°E")
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
        
        # Prediction
        X = row[features].values.reshape(1, -1)
        X = np.nan_to_num(X, nan=0.0)
        
        prob = model.predict_proba(X)[0][1]
        label = 'RED' if prob >= 0.5 else 'GREEN'
        
        print(f"\n  🎯 PREDICTION:")
        emoji = '🔴' if prob >= 0.7 else '🟠' if prob >= 0.3 else '🟢'
        print(f"    Risk Score: {prob:.3f} {emoji}")
        print(f"    Risk Zone:  {label}")
        
        if prob >= 0.7:
            print(f"    ⚠️  HIGH RISK — Immediate relocation recommended")
        elif prob >= 0.3:
            print(f"    ⚠️  MEDIUM RISK — Monitor and plan")
        else:
            print(f"    ✅ LOW RISK — Safe for habitation")


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
    print(f"  ✅ Model loaded ({metadata['n_features']} features, {metadata['model_type']})")
    
    print("  Loading village data...")
    df = load_data()
    print(f"  ✅ Loaded {len(df):,} villages")
    
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
    
    # Predict all
    print("  Running predictions...")
    df = predict_all(model, features, df)
    print("  ✅ Predictions complete")
    
    # Summary
    print_summary(df)
    
    # Top N
    if args.top > 0:
        print(f"\n  🔴 Top {args.top} Highest Risk Villages:")
        print(f"    {'#':>4s} {'State':<20s} {'District':<20s} {'Village':<25s} {'Score':>8s}")
        print(f"    {'-'*77}")
        
        top = df.nlargest(args.top, 'predicted_risk_score')
        for i, (_, row) in enumerate(top.iterrows(), 1):
            sc = 'State Name' if 'State Name' in row.index else 'State'
            dc = 'District Name' if 'District Name' in row.index else 'District'
            vc = 'Village Name' if 'Village Name' in row.index else 'Village'
            print(f"    {i:>4d} {str(row[sc])[:20]:<20s} {str(row[dc])[:20]:<20s} "
                  f"{str(row[vc])[:25]:<25s} {row['predicted_risk_score']:>7.3f}")
    
    # Save
    if args.save:
        df.to_csv(args.save, index=False)
        print(f"\n  💾 Results saved to {args.save}")
    
    print()


if __name__ == '__main__':
    main()
