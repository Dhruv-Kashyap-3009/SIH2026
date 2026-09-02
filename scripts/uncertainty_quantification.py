"""
Task 6: Uncertainty Quantification

Train a bootstrap ensemble of the susceptibility model and compute
prediction variance per village as a continuous uncertainty measure.

Replaces the binary low_confidence flag with a continuous
prediction_uncertainty (0-1, higher = less certain).

Usage:
    python scripts/uncertainty_quantification.py
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import os
import json
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'

N_BOOTSTRAP = 7  # Number of bootstrap ensemble members
RANDOM_STATE = 42


def bootstrap_uncertainty(X, y, features, n_bootstrap=N_BOOTSTRAP):
    """
    Train bootstrap ensemble and compute per-village prediction variance.

    Each bootstrap model is trained on a random sample (with replacement)
    of the training data. The variance of predictions across models
    indicates uncertainty.

    Args:
        X: Feature matrix
        y: Labels
        features: Feature names
        n_bootstrap: Number of ensemble members

    Returns:
        mean_pred: Mean prediction across ensemble
        uncertainty: Prediction variance (0-1 scale)
        models: List of trained models
    """
    print(f"\n--- Bootstrap Ensemble ({n_bootstrap} models) ---")

    rng = np.random.RandomState(RANDOM_STATE)
    all_preds = np.zeros((len(X), n_bootstrap))

    for i in range(n_bootstrap):
        # Sample with replacement
        boot_idx = rng.choice(len(X), size=len(X), replace=True)
        X_boot = X.iloc[boot_idx]
        y_boot = y.iloc[boot_idx]

        # Train model
        params = {
            'n_estimators': 500, 'max_depth': 4,
            'learning_rate': 0.05, 'subsample': 0.8,
            'colsample_bytree': 0.8, 'min_child_weight': 5,
            'random_state': RANDOM_STATE + i, 'n_jobs': -1,
            'eval_metric': 'auc',
        }
        model = xgb.XGBClassifier(**params)
        model.fit(X_boot, y_boot, verbose=False)

        # Predict on full dataset
        all_preds[:, i] = model.predict_proba(X)[:, 1]
        print(f"  Model {i+1}/{n_bootstrap}: "
              f"mean_pred={all_preds[:, i].mean():.3f}, "
              f"std={all_preds[:, i].std():.3f}")

    # Compute uncertainty metrics
    mean_pred = all_preds.mean(axis=1)
    prediction_std = all_preds.std(axis=1)

    # Normalize uncertainty to [0, 1]
    # Higher std = less certain
    uncertainty = prediction_std / prediction_std.max() if prediction_std.max() > 0 else prediction_std

    return mean_pred, uncertainty, all_preds


def main():
    print("=" * 60)
    print("Task 6: Uncertainty Quantification")
    print("=" * 60)

    # Load data
    features_path = os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv')
    df = pd.read_csv(features_path, low_memory=False)
    df = df.dropna(subset=['high_risk'])

    with open(os.path.join(MODEL_DIR, 'susceptibility_features.json')) as f:
        features = json.load(f)

    X = df[features].copy()
    y = df['high_risk'].copy()
    for col in X.columns:
        X[col] = X[col].fillna(X[col].median())
    X = X.astype(float)

    print(f"  Data: {len(X):,} villages, {len(features)} features")

    # Run bootstrap uncertainty
    mean_pred, uncertainty, all_preds = bootstrap_uncertainty(X, y, features)

    # Add to features CSV
    df['prediction_uncertainty'] = uncertainty
    df['prediction_mean'] = mean_pred
    df['prediction_std'] = all_preds.std(axis=1)

    # Update low_confidence based on continuous uncertainty
    # Villages with uncertainty > 75th percentile get low_confidence=True
    threshold = np.percentile(uncertainty, 75)
    df['low_confidence'] = uncertainty > threshold

    # Report
    print(f"\n--- Uncertainty Statistics ---")
    print(f"  Mean uncertainty: {uncertainty.mean():.4f}")
    print(f"  Std uncertainty:  {uncertainty.std():.4f}")
    print(f"  Max uncertainty:  {uncertainty.max():.4f}")
    print(f"  Low confidence threshold (75th pctl): {threshold:.4f}")
    print(f"  Low confidence villages: {df['low_confidence'].sum()} "
          f"({df['low_confidence'].mean()*100:.1f}%)")

    # Uncertainty by risk zone
    if 'predicted_risk_zone' in df.columns:
        print(f"\n  Uncertainty by risk zone:")
        for zone in ['GREEN', 'ORANGE', 'RED']:
            mask = df['predicted_risk_zone'] == zone
            if mask.sum() > 0:
                print(f"    {zone}: mean_uncertainty={uncertainty[mask].mean():.4f}, "
                      f"n={mask.sum()}")

    # Save
    df.to_csv(features_path, index=False)
    print(f"\n  Saved: {features_path}")

    # Save metadata
    metadata = {
        'n_bootstrap_models': N_BOOTSTRAP,
        'mean_uncertainty': float(uncertainty.mean()),
        'std_uncertainty': float(uncertainty.std()),
        'low_confidence_threshold': float(threshold),
        'n_low_confidence': int(df['low_confidence'].sum()),
        'low_confidence_pct': round(df['low_confidence'].mean()*100, 1),
    }
    meta_path = os.path.join(MODEL_DIR, 'uncertainty_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"  Saved: {meta_path}")

    print("\n" + "=" * 60)
    print("Uncertainty Quantification Complete")
    print("=" * 60)


if __name__ == '__main__':
    main()
