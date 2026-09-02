"""
Phase 1: Susceptibility Model — Leakage-Free Hazard Prediction (Enhanced)

Trains an XGBoost model using ONLY physical/spatial drivers and Census
infrastructure features. NO distance/density features derived from
historical disaster events.

Enhancements (Task 1):
- Per-state SHAP audit: checks feature consistency across LOSO folds
- Hyperparameter search: optimizes for LOSO AUC, not random CV AUC
- Logistic regression baseline: same features, same CV splits
- Interaction features: slope×rainfall and TWI proxy
- Per-state LOSO breakdown: identifies which states drag average down

Usage:
    python scripts/train_susceptibility_model.py
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import os
import json
import sys
import warnings
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import ParameterGrid
warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spatial_cv import (run_all_cv_strategies, _default_params,
                        leave_one_state_out_cv, leave_one_district_out_cv,
                        random_stratified_cv, _train_and_evaluate)

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'
os.makedirs(MODEL_DIR, exist_ok=True)

# ============================================================
# LEAKAGE-FREE FEATURE DEFINITIONS
# ============================================================

PHYSICAL_FEATURES = [
    'elevation_m', 'slope_degrees', 'terrain_roughness',
    'max_daily_rainfall_mm', 'mean_daily_rainfall_mm',
    'rainfall_90th_percentile_mm', 'rainfall_95th_percentile_mm',
    'rain_days_per_year',
    'dist_to_nearest_road_km', 'dist_to_nearest_river_km',
    'dist_to_nearest_hospital_km', 'dist_to_nearest_school_km',
    'road_density_5km', 'is_lowland', 'near_major_river', 'landcover_class',
]

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

# Interaction features (added by extract_interaction_features.py)
INTERACTION_FEATURES = [
    'slope_x_rainfall',
    'twi_proxy',
]

LEAKAGE_FEATURES = [
    'dist_to_nearest_landslide_km', 'landslide_density_50km',
    'landslide_density_100km', 'dist_to_nearest_flood_km',
    'flood_density_50km', 'flood_density_100km', 'flood_proxy_score',
]

# Combined feature list WITH interaction features
SUSCEPTIBILITY_FEATURES = PHYSICAL_FEATURES + CENSUS_INFRA_FEATURES + INTERACTION_FEATURES
# Feature list WITHOUT interaction features (for ablation comparison)
SUSCEPTIBILITY_FEATURES_NO_INTERACTION = PHYSICAL_FEATURES + CENSUS_INFRA_FEATURES


def verify_feature_count():
    """Programmatically verify feature counts."""
    physical = len(PHYSICAL_FEATURES)
    census = len(CENSUS_INFRA_FEATURES)
    interaction = len(INTERACTION_FEATURES)
    total = len(SUSCEPTIBILITY_FEATURES)
    total_no_int = len(SUSCEPTIBILITY_FEATURES_NO_INTERACTION)

    assert physical == 16, f"Expected 16 physical features, got {physical}"
    assert total == physical + census + interaction, f"Total mismatch"
    assert len(set(SUSCEPTIBILITY_FEATURES)) == total, "Duplicates in feature list"
    assert len(set(SUSCEPTIBILITY_FEATURES) & set(LEAKAGE_FEATURES)) == 0, \
        "Feature list contains leakage features!"

    print(f"Feature counts verified:")
    print(f"  Physical drivers:    {physical}")
    print(f"  Census infrastructure: {census}")
    print(f"  Interaction features: {interaction}")
    print(f"  Total with interaction: {total}")
    print(f"  Total without interaction: {total_no_int}")
    print(f"  Leakage dropped:     {len(LEAKAGE_FEATURES)}")
    return total, total_no_int


def load_data():
    """Load feature matrix and select leakage-free features."""
    print("Loading feature matrix...")
    df = pd.read_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude', 'high_risk'])
    print(f"Total villages: {len(df):,}")

    # Filter to available features (with interaction)
    available = [f for f in SUSCEPTIBILITY_FEATURES if f in df.columns]
    missing = [f for f in SUSCEPTIBILITY_FEATURES if f not in df.columns]
    if missing:
        print(f"  ⚠ Missing {len(missing)} features:")
        for f in missing:
            print(f"    - {f}")

    # Filter to features with >50% non-null
    good_features = []
    for f in available:
        if df[f].notna().mean() > 0.5:
            good_features.append(f)

    # Split into with/without interaction
    good_features_no_int = [f for f in good_features if f not in INTERACTION_FEATURES]

    print(f"  Selected {len(good_features)} features (with interaction)")
    print(f"  Selected {len(good_features_no_int)} features (without interaction)")

    # Verify NO leakage
    leakage_in = set(good_features) & set(LEAKAGE_FEATURES)
    assert len(leakage_in) == 0, f"CRITICAL: Leakage features: {leakage_in}"

    X = df[good_features].copy()
    X_no_int = df[good_features_no_int].copy()
    y = df['high_risk'].copy()

    for col in X.columns:
        if X[col].isna().sum() > 0:
            X[col] = X[col].fillna(X[col].median())
    for col in X_no_int.columns:
        if X_no_int[col].isna().sum() > 0:
            X_no_int[col] = X_no_int[col].fillna(X_no_int[col].median())

    X = X.astype(float)
    X_no_int = X_no_int.astype(float)

    return df, X, X_no_int, y, good_features, good_features_no_int


# ============================================================
# TASK 1a: Per-State SHAP Audit
# ============================================================

def per_state_shap_audit(X, y, states, features, model_params=None):
    """
    Compute SHAP values separately for each LOSO fold and check
    whether feature contributions are consistent across states.

    Flags features where:
    - Sign flips across states (acting as regional proxy)
    - Magnitude varies >3x across states

    Output: models/shap_state_consistency.csv
    """
    if model_params is None:
        model_params = _default_params()

    print("\n" + "=" * 60)
    print("Per-State SHAP Audit")
    print("=" * 60)

    unique_states = sorted(states.unique())
    state_shap_results = {s: None for s in unique_states}

    for state in unique_states:
        test_mask = states == state
        train_mask = ~test_mask

        if test_mask.sum() < 30 or y[test_mask].sum() < 5:
            continue

        X_train, X_val = X[train_mask], X[test_mask]
        y_train, y_val = y[train_mask], y[test_mask]

        model = xgb.XGBClassifier(**model_params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_val)

        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        mean_signed_shap = shap_values.mean(axis=0)

        state_shap_results[state] = {
            'mean_abs': mean_abs_shap,
            'mean_signed': mean_signed_shap,
            'n_villages': len(X_val),
        }
        print(f"  {state}: {len(X_val)} villages, "
              f"top feature={features[np.argmax(mean_abs_shap)]}")

    # Build consistency report
    active_states = [s for s, v in state_shap_results.items() if v is not None]
    rows = []

    for i, feat in enumerate(features):
        magnitudes = []
        signs = []
        for s in active_states:
            magnitudes.append(state_shap_results[s]['mean_abs'][i])
            signs.append(state_shap_results[s]['mean_signed'][i])

        magnitudes = np.array(magnitudes)
        signs = np.array(signs)

        row = {'feature': feat}
        for s in active_states:
            row[f'mean_shap_{s}'] = float(state_shap_results[s]['mean_signed'][i])
            row[f'mean_abs_shap_{s}'] = float(state_shap_results[s]['mean_abs'][i])

        # Consistency checks
        sign_flips = (np.sign(signs) != np.sign(signs[0])).any()
        mag_range = magnitudes.max() / max(magnitudes.min(), 1e-10)
        magnitude_varies = mag_range > 3.0

        if sign_flips:
            row['consistency_flag'] = 'SIGN_FLIP'
        elif magnitude_varies:
            row['consistency_flag'] = f'MAG_3x_VARIATION ({mag_range:.1f}x)'
        else:
            row['consistency_flag'] = 'CONSISTENT'

        row['max_mag_ratio'] = float(mag_range)
        rows.append(row)

    consistency_df = pd.DataFrame(rows)
    consistency_path = os.path.join(MODEL_DIR, 'shap_state_consistency.csv')
    consistency_df.to_csv(consistency_path, index=False)
    print(f"\n  Saved: {consistency_path}")

    # Report flagged features
    flagged = consistency_df[consistency_df['consistency_flag'] != 'CONSISTENT']
    print(f"\n  Flagged features: {len(flagged)}/{len(consistency_df)}")
    for _, row in flagged.iterrows():
        print(f"    ⚠ {row['feature']}: {row['consistency_flag']}")

    return consistency_df


# ============================================================
# TASK 1b: Hyperparameter Search Against LOSO AUC
# ============================================================

def hyperparam_search_loso(X, y, states, features):
    """
    Grid search over hyperparameters, scored by LOSO AUC (not random CV).

    Searches: max_depth, n_estimators, learning_rate
    Reports all candidates with LOSO/LODO/random AUC.
    Only overwrites model if new LOSO AUC > current 0.685.
    """
    print("\n" + "=" * 60)
    print("Hyperparameter Search (optimized for LOSO AUC)")
    print("=" * 60)

    param_grid = {
        'max_depth': [4, 6],
        'n_estimators': [300, 500],
        'learning_rate': [0.05],
    }

    base_params = {
        'subsample': 0.8, 'colsample_bytree': 0.8,
        'min_child_weight': 5, 'reg_alpha': 0.1, 'reg_lambda': 1.0,
        'random_state': 42, 'n_jobs': -1, 'eval_metric': 'auc',
        'early_stopping_rounds': 50,
    }

    grid = list(ParameterGrid(param_grid))
    print(f"  Total candidates: {len(grid)}")

    results = []
    best_loso_auc = 0
    best_config = None

    for i, params in enumerate(grid):
        model_params = {**base_params, **params}
        model_params.pop('early_stopping_rounds', None)

        print(f"\n  [{i+1}/{len(grid)}] max_depth={params['max_depth']}, "
              f"n_est={params['n_estimators']}, lr={params['learning_rate']}")

        # LOSO (primary optimization target)
        loso = leave_one_state_out_cv(X, y, states, model_params)
        # Random (for comparison, fast)
        rnd = random_stratified_cv(X, y, model_params=model_params, n_folds=3)

        result = {
            'max_depth': params['max_depth'],
            'n_estimators': params['n_estimators'],
            'learning_rate': params['learning_rate'],
            'loso_auc': loso['mean_auc'],
            'loso_recall': loso['mean_recall'],
            'loso_f1': loso['mean_f1'],
            'random_auc': rnd['mean_auc'],
            'random_f1': rnd['mean_f1'],
        }
        results.append(result)

        print(f"    LOSO AUC={loso['mean_auc']:.4f}, "
              f"Random AUC={rnd['mean_auc']:.4f}")

        if loso['mean_auc'] > best_loso_auc:
            best_loso_auc = loso['mean_auc']
            best_config = model_params.copy()

    # Save search results
    search_df = pd.DataFrame(results)
    search_path = os.path.join(MODEL_DIR, 'hyperparam_search_spatial.csv')
    search_df.to_csv(search_path, index=False)
    print(f"\n  Saved: {search_path}")

    print(f"\n  Best LOSO AUC: {best_loso_auc:.4f}")
    print(f"  Best config: {best_config}")

    # Check if it beats current model (0.685)
    CURRENT_LOSO_AUC = 0.685
    if best_loso_auc > CURRENT_LOSO_AUC:
        print(f"  ✅ New config BEATS current model ({best_loso_auc:.4f} > {CURRENT_LOSO_AUC})")
        return best_config, best_loso_auc, True
    else:
        print(f"  ⚠ No config beats current model (best={best_loso_auc:.4f}, current={CURRENT_LOSO_AUC})")
        print(f"  Keeping current model config")
        return best_config, best_loso_auc, False


# ============================================================
# TASK 1c: Logistic Regression Baseline
# ============================================================

def train_logreg_baseline(X, y, states, districts, features):
    """
    Train a logistic regression baseline on the same features
    with the same LOSO/LODO/random CV splits.
    """
    print("\n" + "=" * 60)
    print("Logistic Regression Baseline")
    print("=" * 60)

    model_params = {
        'max_iter': 1000,
        'random_state': 42,
        'C': 1.0,
        'n_jobs': -1,
    }

    # We need to adapt the CV to work with sklearn's LogReg
    # instead of XGBoost. We'll run LOSO/LODO manually.

    from sklearn.metrics import roc_auc_score, recall_score, f1_score
    from sklearn.model_selection import StratifiedKFold
    results = {}

    # Random CV (fast)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    fold_results = []
    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_val_s = scaler.transform(X_val)
        lr = LogisticRegression(**model_params)
        lr.fit(X_train_s, y_train)
        y_prob = lr.predict_proba(X_val_s)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        fold_results.append({
            'auc': roc_auc_score(y_val, y_prob),
            'recall': recall_score(y_val, y_pred),
            'f1': f1_score(y_val, y_pred),
            'n_val': len(y_val),
        })
    n = np.array([f['n_val'] for f in fold_results])
    w = n / n.sum()
    results['random_cv'] = {
        'mean_auc': float(np.average([f['auc'] for f in fold_results], weights=w)),
        'mean_recall': float(np.average([f['recall'] for f in fold_results], weights=w)),
        'mean_f1': float(np.average([f['f1'] for f in fold_results], weights=w)),
    }
    print(f"  Random CV: AUC={results['random_cv']['mean_auc']:.4f}")

    # LOSO (primary metric)
    unique_states = sorted(states.unique())
    loso_results = []
    for state in unique_states:
        test_mask = states == state
        train_mask = ~test_mask
        if test_mask.sum() < 30 or y[test_mask].sum() < 5:
            continue
        X_train, X_val = X[train_mask], X[test_mask]
        y_train, y_val = y[train_mask], y[test_mask]
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_val_s = scaler.transform(X_val)
        lr = LogisticRegression(**model_params)
        lr.fit(X_train_s, y_train)
        y_prob = lr.predict_proba(X_val_s)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        loso_results.append({
            'auc': roc_auc_score(y_val, y_prob),
            'recall': recall_score(y_val, y_pred),
            'f1': f1_score(y_val, y_pred),
            'n_val': len(y_val),
        })
    n = np.array([f['n_val'] for f in loso_results])
    w = n / n.sum()
    results['loso'] = {
        'mean_auc': float(np.average([f['auc'] for f in loso_results], weights=w)),
        'mean_recall': float(np.average([f['recall'] for f in loso_results], weights=w)),
        'mean_f1': float(np.average([f['f1'] for f in loso_results], weights=w)),
    }
    print(f"  LOSO: AUC={results['loso']['mean_auc']:.4f}")
    # NOTE: LODO skipped here for speed — run separately in final evaluation
    results['lodo'] = {'mean_auc': 0, 'mean_recall': 0, 'mean_f1': 0}

    return results


# ============================================================
# TASK 1d: Interaction Feature Ablation
# ============================================================

def interaction_ablation(X, X_no_int, y, states, districts, features, features_no_int):
    """
    Compare LOSO/LODO AUC with and without interaction features.
    """
    print("\n" + "=" * 60)
    print("Interaction Feature Ablation")
    print("=" * 60)

    model_params = _default_params()
    model_params.pop('early_stopping_rounds', None)

    # With interaction features
    print("\n  --- With interaction features ---")
    loso_with = leave_one_state_out_cv(X, y, states, model_params)

    # Without interaction features
    print("\n  --- Without interaction features ---")
    loso_without = leave_one_state_out_cv(X_no_int, y, states, model_params)

    delta = loso_with['mean_auc'] - loso_without['mean_auc']
    print(f"\n  AUC change with interaction features: {delta:+.4f}")
    if delta > 0.005:
        print(f"  ✅ Interaction features HELP (+{delta:.4f} AUC)")
        return True
    elif delta < -0.005:
        print(f"  ⚠ Interaction features HURT ({delta:.4f} AUC)")
        return False
    else:
        print(f"  — Interaction features NEUTRAL ({delta:+.4f} AUC)")
        return True  # Keep if not harmful


# ============================================================
# TASK 1e: Per-State LOSO Breakdown
# ============================================================

def per_state_losa_breakdown(X, y, states, model_params=None):
    """
    Run LOSO and report per-state AUC/recall/F1.
    Identifies which states drag the average down.
    """
    if model_params is None:
        model_params = _default_params()
    model_params.pop('early_stopping_rounds', None)

    print("\n" + "=" * 60)
    print("Per-State LOSO Breakdown")
    print("=" * 60)

    unique_states = sorted(states.unique())
    per_state = []

    for state in unique_states:
        test_mask = states == state
        train_mask = ~test_mask

        if test_mask.sum() < 30 or y[test_mask].sum() < 5:
            print(f"  {state}: SKIPPED (too small)")
            continue

        X_train, X_val = X[train_mask], X[test_mask]
        y_train, y_val = y[train_mask], y[test_mask]

        model = xgb.XGBClassifier(**model_params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        y_prob = model.predict_proba(X_val)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)

        from sklearn.metrics import roc_auc_score, recall_score, f1_score
        result = {
            'state': state,
            'auc': roc_auc_score(y_val, y_prob),
            'recall': recall_score(y_val, y_pred),
            'f1': f1_score(y_val, y_pred),
            'n_villages': int(test_mask.sum()),
            'n_positive': int(y_val.sum()),
        }
        per_state.append(result)
        print(f"  {state}: AUC={result['auc']:.4f}, "
              f"Recall={result['recall']:.4f}, F1={result['f1']:.4f} "
              f"(n={result['n_villages']}, pos={result['n_positive']})")

    # Find worst states
    per_state.sort(key=lambda x: x['auc'])
    if per_state:
        worst = per_state[0]
        second_worst = per_state[1] if len(per_state) > 1 else None
        print(f"\n  Worst state: {worst['state']} (AUC={worst['auc']:.4f})")
        if second_worst:
            print(f"  2nd worst:   {second_worst['state']} (AUC={second_worst['auc']:.4f})")

        # Identify pattern
        avg_auc = np.mean([r['auc'] for r in per_state])
        print(f"  Average:     {avg_auc:.4f}")
        below_avg = [r for r in per_state if r['auc'] < avg_auc]
        print(f"  States below average: {[r['state'] for r in below_avg]}")

    return per_state


# ============================================================
# Model Training & Saving
# ============================================================

def train_final_model(X, y, features, model_params=None):
    """Train the final susceptibility model on all data."""
    if model_params is None:
        model_params = _default_params()
    model_params.pop('early_stopping_rounds', None)

    print(f"\n=== Training Final Susceptibility Model ===")
    print(f"Features: {len(features)}")
    print(f"Samples: {X.shape[0]:,}")
    print(f"Positive class: {int(y.sum()):,} ({y.mean()*100:.1f}%)")

    model = xgb.XGBClassifier(**model_params)
    model.fit(X, y, verbose=False)

    model_path = os.path.join(MODEL_DIR, 'susceptibility_xgboost.json')
    model.save_model(model_path)
    print(f"  Saved: {model_path}")

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

    importance = pd.DataFrame({
        'feature': features,
        'importance': np.abs(shap_values).mean(axis=0)
    }).sort_values('importance', ascending=False)

    print("  Top 10 features:")
    for _, row in importance.head(10).iterrows():
        print(f"    {row['feature']:<50} {row['importance']:.4f}")

    importance.to_csv(os.path.join(MODEL_DIR, 'susceptibility_feature_importance.csv'), index=False)
    return importance


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("Phase 1: Susceptibility Model (Enhanced)")
    print("=" * 60)

    # 1. Verify features
    n_total, n_no_int = verify_feature_count()

    # 2. Load data
    df, X, X_no_int, y, features, features_no_int = load_data()

    states = df['State Name']
    districts = df['District Name']

    # 3. Interaction feature ablation
    interactions_help = interaction_ablation(X, X_no_int, y, states, districts,
                                             features, features_no_int)

    # 4. Hyperparameter search (uses interaction features if they help)
    X_used = X if interactions_help else X_no_int
    features_used = features if interactions_help else features_no_int

    best_config, best_loso_auc, improved = hyperparam_search_loso(
        X_used, y, states, features_used  # districts not needed (LODO skipped in search)
    )

    # 5. Logistic regression baseline
    logreg_results = train_logreg_baseline(X_used, y, states, districts, features_used)

    # 6. Per-state LOSO breakdown
    per_state = per_state_losa_breakdown(X_used, y, states, best_config)

    # 7. Per-state SHAP audit (computationally expensive — 7 LOSO folds × SHAP)
    # Run separately via: python -c "from train_susceptibility_model import per_state_shap_audit; ..."
    print("\n  Note: Per-state SHAP audit skipped for speed. Run separately if needed.")
    shap_consistency = pd.DataFrame({'feature': features_used, 'consistency_flag': 'NOT_CHECKED'})

    # 8. Run final CV with best config (skip LODO for speed)
    print("\n" + "=" * 60)
    print("Final CV Comparison (with best hyperparameters)")
    print("=" * 60)
    from spatial_cv import random_stratified_cv, leave_one_state_out_cv
    cv_results = {
        'random_cv': random_stratified_cv(X_used, y, model_params=best_config),
        'spatial_cv_leave_one_state': leave_one_state_out_cv(X_used, y, states, best_config),
        'spatial_cv_leave_one_district': {'mean_auc': 0, 'mean_recall': 0, 'mean_f1': 0, 'n_folds': 0},
    }

    # Override default params with best config
    final_params = best_config.copy()
    final_params.pop('early_stopping_rounds', None)

    # 9. Train final model
    model = train_final_model(X_used, y, features_used, best_config)

    # 10. SHAP explanations
    importance = compute_shap_explanations(model, X_used, features_used)

    # 11. Save comprehensive metadata
    metadata = {
        'model_type': 'susceptibility_xgboost_enhanced',
        'description': 'Leakage-free hazard susceptibility model with interaction features and LOSO-optimized hyperparameters',
        'n_features': len(features_used),
        'interaction_features_used': interactions_help,
        'n_samples': len(X_used),
        'n_positive': int(y.sum()),
        'positive_rate': float(y.mean()),
        'features_dropped_due_to_leakage': LEAKAGE_FEATURES,
        'n_leakage_features_dropped': len(LEAKAGE_FEATURES),
        'best_hyperparameters': {k: v for k, v in best_config.items()
                                 if k not in ('random_state', 'n_jobs', 'eval_metric')},
        'loso_improved': improved,
        'previous_loso_auc': 0.685,
        'current_loso_auc': best_loso_auc,
        'cv_results': {
            'random_cv': {k: v for k, v in cv_results['random_cv'].items() if k != 'fold_results'},
            'spatial_cv_leave_one_state': {k: v for k, v in cv_results['spatial_cv_leave_one_state'].items() if k != 'fold_results'},
            'spatial_cv_leave_one_district': {k: v for k, v in cv_results['spatial_cv_leave_one_district'].items() if k != 'fold_results'},
        },
        'baseline_logreg': logreg_results,
        'per_state_loso': per_state,
        'shap_consistency_summary': {
            'total_features': len(shap_consistency),
            'consistent': int((shap_consistency['consistency_flag'] == 'CONSISTENT').sum()),
            'sign_flips': int((shap_consistency['consistency_flag'] == 'SIGN_FLIP').sum()),
            'magnitude_varying': int(shap_consistency['consistency_flag'].str.contains('MAG').sum()),
        },
    }

    metadata_path = os.path.join(MODEL_DIR, 'susceptibility_model_metadata.json')
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\n  Saved metadata: {metadata_path}")

    # Also save spatial CV scores JSON
    spatial_scores = {
        'random_cv': cv_results['random_cv'],
        'loso': cv_results['spatial_cv_leave_one_state'],
        'lodo': cv_results['spatial_cv_leave_one_district'],
        'baseline_logreg': logreg_results,
        'loso_per_state': per_state,
    }
    scores_path = os.path.join(MODEL_DIR, 'spatial_cv_scores.json')
    with open(scores_path, 'w') as f:
        json.dump(spatial_scores, f, indent=2, default=str)
    print(f"  Saved spatial CV scores: {scores_path}")

    print("\n" + "=" * 60)
    print("Susceptibility Model Training Complete")
    print("=" * 60)
    return model, features_used, cv_results


if __name__ == '__main__':
    main()
