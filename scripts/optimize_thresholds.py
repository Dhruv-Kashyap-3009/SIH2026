"""
Task 5: Threshold Optimization & Quantile-Based Zoning

Instead of fixed round-number thresholds (RED≥0.7, ORANGE≥0.4, GREEN<0.4),
this script:

1. Computes a cost curve across thresholds with asymmetric costs
   (false negative = missed high-risk village = more expensive)
2. Finds the optimal threshold that minimizes expected cost
3. Implements quantile-based zoning (top X% = RED, next Y% = ORANGE)
4. Outputs both methods to prediction_output.csv for comparison

Usage:
    python scripts/optimize_thresholds.py
"""

import numpy as np
import pandas as pd
import os
import json
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'

# Cost weights: missing a high-risk village is 5x worse than a false alarm
FN_COST = 5.0   # False negative: village is actually high-risk, we say low
FP_COST = 1.0   # False positive: village is actually safe, we say high-risk
TP_VALUE = 0.0  # Correctly identified risk
TN_VALUE = 0.0  # Correctly identified safe


def compute_cost(y_true, y_pred, fn_cost=FN_COST, fp_cost=FP_COST):
    """Compute asymmetric classification cost."""
    fn = ((y_true == 1) & (y_pred == 0)).sum()
    fp = ((y_true == 0) & (y_pred == 1)).sum()
    tp = ((y_true == 1) & (y_pred == 1)).sum()
    tn = ((y_true == 0) & (y_pred == 0)).sum()
    return fn * fn_cost + fp * fp_cost


def find_optimal_threshold(y_true, y_prob, fn_cost=FN_COST, fp_cost=FP_COST):
    """Find the threshold that minimizes asymmetric cost."""
    thresholds = np.arange(0.1, 0.9, 0.01)
    costs = []

    for t in thresholds:
        y_pred = (y_prob >= t).astype(int)
        cost = compute_cost(y_true, y_pred, fn_cost, fp_cost)
        costs.append(cost)

    costs = np.array(costs)
    best_idx = np.argmin(costs)
    best_threshold = thresholds[best_idx]
    best_cost = costs[best_idx]

    return best_threshold, best_cost, thresholds, costs


def quantile_zoning(y_prob, red_pct=0.65, orange_pct=0.10):
    """
    Quantile-based zoning: assign zones by score rank rather than fixed thresholds.

    Args:
        y_prob: predicted probabilities
        red_pct: fraction of villages to assign as RED (top scores)
        orange_pct: fraction to assign as ORANGE

    Returns:
        Series of zone labels
    """
    n = len(y_prob)
    n_red = int(n * red_pct)
    n_orange = int(n * orange_pct)

    # Sort by probability (descending)
    sorted_indices = np.argsort(-y_prob)
    zones = pd.Series(['GREEN'] * n, index=range(n))

    zones.iloc[sorted_indices[:n_red]] = 'RED'
    if n_orange > 0:
        zones.iloc[sorted_indices[n_red:n_red + n_orange]] = 'ORANGE'

    return zones


def precision_recall_at_thresholds(y_true, y_prob):
    """Compute precision and recall at various thresholds."""
    from sklearn.metrics import precision_recall_curve
    precisions, recalls, thresholds_pr = precision_recall_curve(y_true, y_prob)

    # Find threshold where recall >= 0.95 (safety-first)
    high_recall_mask = recalls >= 0.95
    if high_recall_mask.any():
        # Among high-recall thresholds, pick the one with best precision
        valid_prec = precisions[high_recall_mask]
        best_idx = np.argmax(valid_prec)
        # Map back to threshold index
        valid_thresholds = thresholds_pr[high_recall_mask[:-1]] if len(thresholds_pr) == len(precisions) - 1 else thresholds_pr[high_recall_mask]
        safe_threshold = valid_thresholds[best_idx] if len(valid_thresholds) > 0 else 0.5
    else:
        safe_threshold = 0.3

    return safe_threshold


def get_out_of_fold_predictions():
    """Generate out-of-fold predictions using 5-fold stratified CV.

    This avoids the in-sample bias of using the model's own predictions
    on the data it was trained on. Each village's prediction comes from
    a fold where it was in the VALIDATION set (never trained on).

    Returns: (y_true, y_prob_oof, df_aligned)
    """
    import xgboost as xgb
    from sklearn.model_selection import StratifiedKFold
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from train_susceptibility_model import load_data, _default_params

    print("  Generating out-of-fold predictions (5-fold stratified CV)...")
    df, X, _, y, features, _ = load_data()

    y_prob_oof = np.zeros(len(y))
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    params = _default_params()
    params.pop('early_stopping_rounds', None)

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        y_prob_oof[val_idx] = model.predict_proba(X_val)[:, 1]
        print(f"    Fold {fold+1}: {len(val_idx)} villages, "
              f"mean_oof={y_prob_oof[val_idx].mean():.3f}")

    return y.values, y_prob_oof, df


def main():
    print("=" * 60)
    print("Task 5: Threshold Optimization & Quantile-Based Zoning")
    print("=" * 60)

    # Load prediction output for column updates
    pred_path = os.path.join(OUTPUT_DIR, 'prediction_output.csv')
    df_pred = pd.read_csv(pred_path, low_memory=False)
    print(f"Loaded: {pred_path} ({len(df_pred):,} villages)")

    # ── Get OUT-OF-FOLD predictions (not in-sample!) ──
    print("\n--- Generating Out-of-Fold Predictions ---")
    y_true, y_prob_oof, df_aligned = get_out_of_fold_predictions()
    print(f"  OOF predictions: {len(y_prob_oof):,}, "
          f"mean={y_prob_oof.mean():.3f}, std={y_prob_oof.std():.3f}")

    # ── Method 1: Cost-sensitive optimal threshold (on OOF predictions) ──
    print("\n--- Cost-Sensitive Threshold Optimization (Out-of-Fold) ---")
    best_t, best_cost, thresholds, costs = find_optimal_threshold(y_true, y_prob_oof)

    safe_t = precision_recall_at_thresholds(y_true, y_prob_oof)

    print(f"  Cost-optimal threshold: {best_t:.2f} (cost={best_cost:,.0f})")
    print(f"  Safety-first threshold (≥95% recall): {safe_t:.2f}")

    # Apply to full dataset using in-sample risk_score for zone assignment
    # (thresholds are validated on OOF, applied to in-sample for final output)
    risk_scores = df_pred['risk_score'].values
    orange_threshold = best_t * 0.55
    df_pred['predicted_risk_zone_fixed'] = pd.Series(risk_scores).apply(
        lambda s: 'RED' if s >= best_t else ('ORANGE' if s >= orange_threshold else 'GREEN')
    )

    # ── Method 2: Quantile-based zoning ──
    print("\n--- Quantile-Based Zoning ---")
    q_zones = quantile_zoning(risk_scores, red_pct=0.67, orange_pct=0.01)
    df_pred['predicted_risk_zone_quantile'] = q_zones
    print(f"  Quantile (67% RED): {q_zones.value_counts().to_dict()}")

    # ── Cost comparison (on OOF predictions) ──
    print("\n--- Cost Comparison (Out-of-Fold) ---")
    cost_fixed = compute_cost(y_true, (y_prob_oof >= 0.7).astype(int))
    cost_optimal = compute_cost(y_true, (y_prob_oof >= best_t).astype(int))
    print(f"  Cost with fixed threshold (0.7): {cost_fixed:,.0f}")
    print(f"  Cost with optimal threshold ({best_t:.2f}): {cost_optimal:,.0f}")
    cost_reduction = round((1 - cost_optimal/cost_fixed)*100, 1) if cost_fixed > 0 else 0
    print(f"  Cost reduction: {cost_reduction}%")

    # Save to CSV
    df_pred.to_csv(pred_path, index=False)
    print(f"\n  Saved: {pred_path}")

    # Save threshold metadata
    metadata = {
        'fixed_threshold': 0.7,
        'cost_optimal_threshold': float(best_t),
        'safety_first_threshold': float(safe_t),
        'orange_threshold': float(orange_threshold),
        'fn_cost_weight': FN_COST,
        'fp_cost_weight': FP_COST,
        'cost_fixed_oof': int(cost_fixed),
        'cost_optimal_oof': int(cost_optimal),
        'cost_reduction_pct_oof': cost_reduction,
        'method': 'out_of_fold_5fold_stratified',
        'validation': 'thresholds optimized on out-of-fold cross-validated predictions, not in-sample scores',
    }
    meta_path = os.path.join(MODEL_DIR, 'threshold_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"  Saved: {meta_path}")

    # Save cost curve
    curve_df = pd.DataFrame({'threshold': thresholds, 'cost': costs})
    curve_path = os.path.join(MODEL_DIR, 'threshold_cost_curve.csv')
    curve_df.to_csv(curve_path, index=False)
    print(f"  Saved: {curve_path}")

    print("\n" + "=" * 60)
    print("Threshold Optimization Complete (Out-of-Fold Validated)")
    print("=" * 60)
    return df_pred


if __name__ == '__main__':
    main()
