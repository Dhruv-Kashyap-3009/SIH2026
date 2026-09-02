"""
Task 4: Model Calibration

Produces reliability diagrams and applies Platt scaling or isotonic
regression to calibrate the susceptibility model's probability outputs.

A well-calibrated model's predicted probability should match the observed
frequency (e.g., among villages predicted at 70% risk, ~70% should actually
be positive).

Usage:
    python scripts/calibrate_model.py
"""

import numpy as np
import pandas as pd
import xgboost as xgb
import os
import json
import warnings
from sklearn.calibration import calibration_curve, CalibratedClassifierCV
from sklearn.model_selection import StratifiedKFold
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
warnings.filterwarnings('ignore')

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'


def compute_reliability(y_true, y_prob, n_bins=10):
    """Compute reliability data: fraction of positives per probability bucket."""
    fraction_positive, mean_predicted = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy='uniform')
    return fraction_positive, mean_predicted


def plot_reliability_diagram(y_true, y_prob_uncal, y_prob_cal, model_name, save_path):
    """Plot reliability diagram comparing uncalibrated vs calibrated."""
    fig, ax = plt.subplots(1, 1, figsize=(8, 6))

    # Uncalibrated
    frac_uncal, mean_uncal = compute_reliability(y_true, y_prob_uncal)
    ax.plot(mean_uncal, frac_uncal, 's-', color='#e74c3c', label=f'Uncalibrated (ECE={compute_ece(y_true, y_prob_uncal):.3f})')

    # Calibrated
    frac_cal, mean_cal = compute_reliability(y_true, y_prob_cal)
    ax.plot(mean_cal, frac_cal, 'o-', color='#27ae60', label=f'Calibrated (ECE={compute_ece(y_true, y_prob_cal):.3f})')

    # Perfect calibration
    ax.plot([0, 1], [0, 1], 'k--', alpha=0.5, label='Perfect calibration')

    ax.set_xlabel('Mean Predicted Probability', fontsize=12)
    ax.set_ylabel('Fraction of Positives', fontsize=12)
    ax.set_title(f'Reliability Diagram — {model_name}', fontsize=14)
    ax.legend(fontsize=10)
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1])
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def compute_ece(y_true, y_prob, n_bins=10):
    """Expected Calibration Error — lower is better."""
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0

    for i in range(n_bins):
        mask = (y_prob >= bin_edges[i]) & (y_prob < bin_edges[i + 1])
        if mask.sum() == 0:
            continue
        bin_acc = y_true[mask].mean()
        bin_conf = y_prob[mask].mean()
        ece += mask.sum() * abs(bin_acc - bin_conf)

    return ece / len(y_true)


def calibrate_with_plattscaling(model, X, y, cv=5):
    """Apply Platt scaling (sigmoid) via cross-validation."""
    print("\n  Applying Platt scaling (sigmoid calibration)...")
    calibrated = CalibratedClassifierCV(model, method='sigmoid', cv=cv)
    calibrated.fit(X, y)
    return calibrated


def calibrate_with_isotonic(model, X, y, cv=5):
    """Apply isotonic regression calibration."""
    print("  Applying isotonic regression calibration...")
    calibrated = CalibratedClassifierCV(model, method='isotonic', cv=cv)
    calibrated.fit(X, y)
    return calibrated


def main():
    print("=" * 60)
    print("Task 4: Model Calibration")
    print("=" * 60)

    # Load data
    features_path = os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv')
    df = pd.read_csv(features_path, low_memory=False)
    df = df.dropna(subset=['high_risk'])

    # Load susceptibility model
    model = xgb.XGBClassifier()
    model.load_model(os.path.join(MODEL_DIR, 'susceptibility_xgboost.json'))

    with open(os.path.join(MODEL_DIR, 'susceptibility_features.json')) as f:
        features = json.load(f)

    X = df[features].copy()
    y = df['high_risk'].copy()
    for col in X.columns:
        X[col] = X[col].fillna(X[col].median())
    X = X.astype(float)

    print(f"  Data: {len(X):,} villages, {len(features)} features")
    print(f"  Positive rate: {y.mean()*100:.1f}%")

    # ── Cross-validated calibration ──
    print("\n--- Cross-Validated Calibration ---")

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_prob_uncal = np.zeros(len(y))
    y_prob_platt = np.zeros(len(y))
    y_prob_isotonic = np.zeros(len(y))

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        # Uncalibrated
        model_clone = xgb.XGBClassifier(**model.get_params())
        model_clone.fit(X_train, y_train, verbose=False)
        y_prob_uncal[val_idx] = model_clone.predict_proba(X_val)[:, 1]

        # Platt scaling
        platt = calibrate_with_plattscaling(model_clone, X_train, y_train, cv=3)
        y_prob_platt[val_idx] = platt.predict_proba(X_val)[:, 1]

        # Isotonic
        isotonic = calibrate_with_isotonic(model_clone, X_train, y_train, cv=3)
        y_prob_isotonic[val_idx] = isotonic.predict_proba(X_val)[:, 1]

        print(f"  Fold {fold+1}: ECE_uncal={compute_ece(y_val, y_prob_uncal[val_idx]):.3f}, "
              f"ECE_platt={compute_ece(y_val, y_prob_platt[val_idx]):.3f}, "
              f"ECE_isotonic={compute_ece(y_val, y_prob_isotonic[val_idx]):.3f}")

    # ── Global metrics ──
    print("\n--- Calibration Metrics ---")
    ece_uncal = compute_ece(y, y_prob_uncal)
    ece_platt = compute_ece(y, y_prob_platt)
    ece_isotonic = compute_ece(y, y_prob_isotonic)
    brier_uncal = np.mean((y - y_prob_uncal) ** 2)
    brier_platt = np.mean((y - y_prob_platt) ** 2)
    brier_isotonic = np.mean((y - y_prob_isotonic) ** 2)

    print(f"  ECE (Expected Calibration Error):")
    print(f"    Uncalibrated: {ece_uncal:.4f}")
    print(f"    Platt scaling: {ece_platt:.4f}")
    print(f"    Isotonic:      {ece_isotonic:.4f}")
    print(f"  Brier Score:")
    print(f"    Uncalibrated: {brier_uncal:.4f}")
    print(f"    Platt scaling: {brier_platt:.4f}")
    print(f"    Isotonic:      {brier_isotonic:.4f}")

    # ── Decision: apply calibration if significant ──
    best_method = 'none'
    best_ece = ece_uncal

    if ece_platt < ece_uncal * 0.95:  # >5% improvement
        best_method = 'sigmoid'
        best_ece = ece_platt
    if ece_isotonic < best_ece * 0.95:
        best_method = 'isotonic'
        best_ece = ece_isotonic

    apply_calibration = best_method != 'none'
    print(f"\n  Calibration {'APPLIED' if apply_calibration else 'NOT APPLIED'}")
    if apply_calibration:
        print(f"  Method: {best_method} (ECE: {ece_uncal:.4f} → {best_ece:.4f})")
    else:
        print(f"  Model is already well-calibrated (ECE={ece_uncal:.4f})")

    # ── Plot reliability diagram ──
    print("\n--- Reliability Diagram ---")
    if apply_calibration:
        best_cal = y_prob_platt if best_method == 'sigmoid' else y_prob_isotonic
        plot_reliability_diagram(y, y_prob_uncal, best_cal,
                                'Susceptibility Model',
                                os.path.join(MODEL_DIR, 'calibration_plot.png'))
    else:
        # Still plot uncalibrated for reference
        plot_reliability_diagram(y, y_prob_uncal, y_prob_uncal,
                                'Susceptibility Model (already calibrated)',
                                os.path.join(MODEL_DIR, 'calibration_plot.png'))

    # ── Fit final calibrated model on all data ──
    if apply_calibration:
        print("\n--- Fitting Final Calibrated Model ---")
        if best_method == 'sigmoid':
            final_calibrated = calibrate_with_plattscaling(model, X, y, cv=5)
        else:
            final_calibrated = calibrate_with_isotonic(model, X, y, cv=5)

        # Save calibrated model
        import pickle
        cal_path = os.path.join(MODEL_DIR, 'susceptibility_xgboost_calibrated.pkl')
        with open(cal_path, 'wb') as f:
            pickle.dump(final_calibrated, f)
        print(f"  Saved: {cal_path}")

    # ── Save calibration metadata ──
    metadata = {
        'calibration_active': apply_calibration,
        'calibration_method': best_method,
        'ece_uncalibrated': round(ece_uncal, 4),
        'ece_calibrated': round(best_ece, 4),
        'brier_uncalibrated': round(brier_uncal, 4),
        'brier_platt': round(brier_platt, 4),
        'brier_isotonic': round(brier_isotonic, 4),
    }
    meta_path = os.path.join(MODEL_DIR, 'calibration_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"  Saved: {meta_path}")

    print("\n" + "=" * 60)
    print("Calibration Complete")
    print("=" * 60)


if __name__ == '__main__':
    main()
