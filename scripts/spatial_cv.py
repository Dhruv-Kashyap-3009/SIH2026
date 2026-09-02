"""
Spatial Cross-Validation for Hazard Susceptibility Models

Provides three CV strategies to honestly evaluate model generalization:
1. Random Stratified 5-Fold CV (baseline — may overestimate due to spatial autocorrelation)
2. Leave-One-State-Out (LOSO) — 7 folds, one per NE India state
3. Leave-One-District-Out (LODO) — ~60 folds, one per district

The gap between random CV and spatial CV reveals how much the model
relies on spatial autocorrelation vs genuine predictive signals.

Usage:
    from scripts.spatial_cv import run_all_cv_strategies
    results = run_all_cv_strategies(X, y, states, districts, feature_names)
"""

import numpy as np
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, recall_score, precision_score, f1_score, accuracy_score
import warnings
warnings.filterwarnings('ignore')


def _train_and_evaluate(X_train, y_train, X_val, y_val, model_params):
    """Train a single XGBoost model and return metrics."""
    model = xgb.XGBClassifier(**model_params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False
    )
    y_prob = model.predict_proba(X_val)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    return {
        'auc': roc_auc_score(y_val, y_prob),
        'recall': recall_score(y_val, y_pred),
        'precision': precision_score(y_val, y_pred, zero_division=0),
        'f1': f1_score(y_val, y_pred),
        'accuracy': accuracy_score(y_val, y_pred),
        'n_val': len(y_val),
        'n_positive_val': int(y_val.sum()),
    }


def _aggregate_folds(fold_results):
    """Compute mean and std across folds, weighted by fold size."""
    n = np.array([f['n_val'] for f in fold_results])
    weights = n / n.sum()

    metrics = {}
    for metric in ['auc', 'recall', 'precision', 'f1', 'accuracy']:
        vals = np.array([f[metric] for f in fold_results])
        metrics[f'mean_{metric}'] = float(np.average(vals, weights=weights))
        metrics[f'std_{metric}'] = float(np.sqrt(np.average((vals - metrics[f'mean_{metric}'])**2, weights=weights)))

    metrics['n_folds'] = len(fold_results)
    metrics['fold_results'] = fold_results
    return metrics


def random_stratified_cv(X, y, n_folds=5, model_params=None, random_state=42):
    """Standard stratified k-fold CV (baseline comparison).

    Args:
        X: Feature DataFrame (n_samples x n_features)
        y: Binary label Series
        n_folds: Number of CV folds
        model_params: XGBoost parameters dict
        random_state: Random seed for reproducibility

    Returns:
        Dict with mean/std metrics and per-fold results
    """
    if model_params is None:
        model_params = _default_params()

    print(f"\n--- Random Stratified {n_folds}-Fold CV ---")

    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=random_state)
    fold_results = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        result = _train_and_evaluate(X_train, y_train, X_val, y_val, model_params)
        result['fold'] = fold + 1
        fold_results.append(result)

        print(f"  Fold {fold+1}: AUC={result['auc']:.4f}, "
              f"Recall={result['recall']:.4f}, Prec={result['precision']:.4f}, "
              f"F1={result['f1']:.4f} (n={result['n_val']})")

    metrics = _aggregate_folds(fold_results)
    print(f"  MEAN: AUC={metrics['mean_auc']:.4f} (+/-{metrics['std_auc']:.4f}), "
          f"Recall={metrics['mean_recall']:.4f}, F1={metrics['mean_f1']:.4f}")
    return metrics


def leave_one_state_out_cv(X, y, states, model_params=None):
    """Leave-One-State-Out CV: 7 folds, one per NE India state.

    Each fold trains on 6 states and tests on the held-out state.
    This is the most realistic evaluation — the model has never seen
    villages from the test state.

    Args:
        X: Feature DataFrame
        y: Binary label Series
        states: Series of state names (same index as X/y)
        model_params: XGBoost parameters dict

    Returns:
        Dict with mean/std metrics and per-fold results
    """
    if model_params is None:
        model_params = _default_params()

    unique_states = sorted(states.unique())
    print(f"\n--- Leave-One-State-Out CV ({len(unique_states)} states) ---")

    fold_results = []
    for state in unique_states:
        test_mask = states == state
        train_mask = ~test_mask

        X_train, X_val = X[train_mask], X[test_mask]
        y_train, y_val = y[train_mask], y[test_mask]

        # Skip states with too few samples
        if len(y_val) < 30 or y_val.sum() < 5:
            print(f"  {state}: SKIPPED (n={len(y_val)}, pos={int(y_val.sum())})")
            continue

        result = _train_and_evaluate(X_train, y_train, X_val, y_val, model_params)
        result['fold'] = state
        result['state'] = state
        fold_results.append(result)

        print(f"  {state}: AUC={result['auc']:.4f}, "
              f"Recall={result['recall']:.4f}, Prec={result['precision']:.4f}, "
              f"F1={result['f1']:.4f} (n={result['n_val']}, pos={result['n_positive_val']})")

    metrics = _aggregate_folds(fold_results)
    print(f"  MEAN: AUC={metrics['mean_auc']:.4f} (+/-{metrics['std_auc']:.4f}), "
          f"Recall={metrics['mean_recall']:.4f}, F1={metrics['mean_f1']:.4f}")
    return metrics


def leave_one_district_out_cv(X, y, districts, model_params=None, min_villages=50):
    """Leave-One-District-Out CV: ~60 folds, one per district.

    Stricter than LOSO — tests whether the model generalizes to
    unseen districts, not just unseen states.

    Skips districts with fewer than min_villages (default 50) as
    they're too small for meaningful evaluation.

    Args:
        X: Feature DataFrame
        y: Binary label Series
        districts: Series of district names (same index as X/y)
        model_params: XGBoost parameters dict
        min_villages: Minimum villages in a district to be used as a test fold

    Returns:
        Dict with mean/std metrics and per-fold results
    """
    if model_params is None:
        model_params = _default_params()

    district_counts = districts.value_counts()
    eligible = district_counts[district_counts >= min_villages].index.tolist()
    print(f"\n--- Leave-One-District-Out CV ({len(eligible)} eligible districts "
          f"out of {len(district_counts)} total, min_villages={min_villages}) ---")

    fold_results = []
    for district in eligible:
        test_mask = districts == district
        train_mask = ~test_mask

        X_train, X_val = X[train_mask], X[test_mask]
        y_train, y_val = y[train_mask], y[test_mask]

        # Skip districts with insufficient class diversity in test set
        if y_val.sum() < 3 or (y_val == 0).sum() < 3:
            continue

        result = _train_and_evaluate(X_train, y_train, X_val, y_val, model_params)
        result['fold'] = district
        result['district'] = district
        fold_results.append(result)

        if len(fold_results) % 10 == 0:
            print(f"  ... {len(fold_results)} districts processed, "
                  f"running AUC={np.mean([f['auc'] for f in fold_results]):.4f}")

    metrics = _aggregate_folds(fold_results)
    print(f"  MEAN: AUC={metrics['mean_auc']:.4f} (+/-{metrics['std_auc']:.4f}), "
          f"Recall={metrics['mean_recall']:.4f}, F1={metrics['mean_f1']:.4f}")
    print(f"  Districts evaluated: {len(fold_results)}")
    return metrics


def run_all_cv_strategies(X, y, states, districts, feature_names=None):
    """Run all three CV strategies and return comparison results.

    Args:
        X: Feature DataFrame
        y: Binary label Series
        states: Series of state names
        districts: Series of district names
        feature_names: Optional list of feature names for metadata

    Returns:
        Dict with keys: 'random_cv', 'spatial_cv_leave_one_state',
        'spatial_cv_leave_one_district'
    """
    print("=" * 60)
    print("Spatial Cross-Validation Comparison")
    print("=" * 60)
    print(f"Samples: {len(X):,}, Features: {X.shape[1]}, "
          f"Positive rate: {y.mean()*100:.1f}%")
    print(f"States: {len(states.unique())}, Districts: {len(districts.unique())}")

    results = {}

    # 1. Random stratified CV (baseline)
    results['random_cv'] = random_stratified_cv(X, y)

    # 2. Leave-one-state-out
    results['spatial_cv_leave_one_state'] = leave_one_state_out_cv(X, y, states)

    # 3. Leave-one-district-out
    results['spatial_cv_leave_one_district'] = leave_one_district_out_cv(X, y, districts)

    # Print comparison
    print("\n" + "=" * 60)
    print("CV Strategy Comparison")
    print("=" * 60)
    print(f"{'Strategy':<35} {'AUC':>8} {'Recall':>8} {'Precision':>10} {'F1':>8}")
    print("-" * 60)
    for strategy, label in [
        ('random_cv', 'Random 5-Fold CV'),
        ('spatial_cv_leave_one_state', 'Leave-One-State-Out'),
        ('spatial_cv_leave_one_district', 'Leave-One-District-Out'),
    ]:
        r = results[strategy]
        print(f"{label:<35} {r['mean_auc']:>8.4f} {r['mean_recall']:>8.4f} "
              f"{r['mean_precision']:>10.4f} {r['mean_f1']:>8.4f}")

    print("-" * 60)
    gap = results['random_cv']['mean_auc'] - results['spatial_cv_leave_one_state']['mean_auc']
    print(f"Random vs Spatial AUC gap: {gap:.4f}")
    if gap > 0.15:
        print("  ⚠ Large gap — model relies heavily on spatial autocorrelation")
    elif gap > 0.05:
        print("  ⚠ Moderate gap — some spatial autocorrelation effect")
    else:
        print("  ✓ Small gap — model generalizes well across regions")

    return results


def _default_params():
    """Default XGBoost parameters for susceptibility model."""
    return {
        'n_estimators': 500,
        'max_depth': 6,
        'learning_rate': 0.05,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'min_child_weight': 5,
        'reg_alpha': 0.1,
        'reg_lambda': 1.0,
        'scale_pos_weight': 1.0,
        'random_state': 42,
        'n_jobs': -1,
        'eval_metric': 'auc',
        'early_stopping_rounds': 50,
    }


if __name__ == '__main__':
    print("spatial_cv.py — Run via train_susceptibility_model.py")
    print("Or: from scripts.spatial_cv import run_all_cv_strategies")
