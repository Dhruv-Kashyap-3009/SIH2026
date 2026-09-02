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


def main():
    print("=" * 60)
    print("Task 5: Threshold Optimization & Quantile-Based Zoning")
    print("=" * 60)

    # Load prediction output
    pred_path = os.path.join(OUTPUT_DIR, 'prediction_output.csv')
    df = pd.read_csv(pred_path, low_memory=False)
    print(f"Loaded: {pred_path} ({len(df):,} villages)")

    # Load true labels (high_risk) for threshold optimization
    features_path = os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv')
    df_features = pd.read_csv(features_path, usecols=['high_risk'], low_memory=False)

    y_true = df_features['high_risk'].values
    y_prob = df['risk_score'].values

    # ── Method 1: Cost-sensitive optimal threshold ──
    print("\n--- Cost-Sensitive Threshold Optimization ---")
    best_t, best_cost, thresholds, costs = find_optimal_threshold(y_true, y_prob)

    # Also find the "safety-first" threshold (high recall)
    safe_t = precision_recall_at_thresholds(y_true, y_prob)

    print(f"  Cost-optimal threshold: {best_t:.2f} (cost={best_cost:,.0f})")
    print(f"  Safety-first threshold (≥95% recall): {safe_t:.2f}")

    # Current fixed thresholds
    print(f"\n  Current fixed thresholds: RED≥0.7, ORANGE≥0.4, GREEN<0.4")

    # Apply cost-optimal threshold
    df['predicted_risk_zone_fixed'] = df['risk_score'].apply(
        lambda s: 'RED' if s >= best_t else 'GREEN'
    )

    # For 3-class, use cost-optimal for RED and a derived threshold for ORANGE
    orange_threshold = best_t * 0.55  # Or use 0.4 as default
    df['predicted_risk_zone_fixed'] = df['risk_score'].apply(
        lambda s: 'RED' if s >= best_t else ('ORANGE' if s >= orange_threshold else 'GREEN')
    )

    # ── Method 2: Quantile-based zoning ──
    print("\n--- Quantile-Based Zoning ---")

    # Option A: Match current distribution (~67% RED)
    q_zones_a = quantile_zoning(y_prob, red_pct=0.67, orange_pct=0.01)
    df['predicted_risk_zone_quantile'] = q_zones_a

    print(f"  Quantile (67% RED):")
    print(f"    {q_zones_a.value_counts().to_dict()}")

    # ── Comparison ──
    print("\n--- Comparison ---")
    print(f"\n  Fixed threshold (t={best_t:.2f}):")
    print(f"    {df['predicted_risk_zone_fixed'].value_counts().to_dict()}")

    # Cost comparison
    cost_fixed = compute_cost(y_true, (y_prob >= 0.7).astype(int))
    cost_optimal = compute_cost(y_true, (y_prob >= best_t).astype(int))
    print(f"\n  Cost with fixed threshold (0.7): {cost_fixed:,.0f}")
    print(f"  Cost with optimal threshold ({best_t:.2f}): {cost_optimal:,.0f}")
    print(f"  Cost reduction: {(1 - cost_optimal/cost_fixed)*100:.1f}%")

    # Save to CSV
    df.to_csv(pred_path, index=False)
    print(f"\n  Saved: {pred_path}")

    # Save threshold metadata
    metadata = {
        'fixed_threshold': 0.7,
        'cost_optimal_threshold': float(best_t),
        'safety_first_threshold': float(safe_t),
        'orange_threshold': float(orange_threshold),
        'fn_cost_weight': FN_COST,
        'fp_cost_weight': FP_COST,
        'cost_fixed': int(cost_fixed),
        'cost_optimal': int(cost_optimal),
        'cost_reduction_pct': round((1 - cost_optimal/cost_fixed)*100, 1),
        'method': 'cost_sensitive',
    }
    meta_path = os.path.join(MODEL_DIR, 'threshold_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"  Saved: {meta_path}")

    # Save cost curve for visualization
    curve_df = pd.DataFrame({
        'threshold': thresholds,
        'cost': costs,
    })
    curve_path = os.path.join(MODEL_DIR, 'threshold_cost_curve.csv')
    curve_df.to_csv(curve_path, index=False)
    print(f"  Saved: {curve_path}")

    print("\n" + "=" * 60)
    print("Threshold Optimization Complete")
    print("=" * 60)
    return df


if __name__ == '__main__':
    main()
