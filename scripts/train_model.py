"""
Phase 3: Red Zone Prediction Model
Trains an XGBoost classifier to predict high_risk villages using
Census + spatial features. Includes SHAP explainability.
"""

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import (
    classification_report, confusion_matrix, roc_auc_score, 
    roc_curve, precision_recall_curve, f1_score, recall_score,
    precision_score, accuracy_score
)
from sklearn.preprocessing import LabelEncoder
import shap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import os
import json
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = 'data/processed'
MODEL_DIR = 'models'
os.makedirs(MODEL_DIR, exist_ok=True)


def load_and_select_features():
    """Load feature matrix and select the best features for modeling."""
    print("Loading feature matrix...")
    df = pd.read_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude', 'high_risk'])
    print(f"Total villages: {len(df):,}")

    # ================================================
    # FEATURE SELECTION
    # ================================================
    # Priority 1: Spatial/hazard features (most predictive for risk)
    spatial_features = [
        'elevation_m', 'slope_degrees', 'terrain_roughness',
        'max_daily_rainfall_mm', 'mean_daily_rainfall_mm',
        'rainfall_90th_percentile_mm', 'rainfall_95th_percentile_mm',
        'rain_days_per_year',
        'dist_to_nearest_road_km', 'dist_to_nearest_river_km',
        'dist_to_nearest_hospital_km', 'dist_to_nearest_school_km',
        'road_density_5km',
        'dist_to_nearest_landslide_km', 'landslide_density_50km',
        'landslide_density_100km',
        # Flood features (added to capture flood risk)
        'dist_to_nearest_flood_km', 'flood_density_50km', 'flood_density_100km',
        'flood_proxy_score', 'is_lowland', 'near_major_river',
    ]

    # Priority 2: Census vulnerability features
    census_features = []
    # Population
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in [
            'total population', 'population density', 'total households',
            'total area', 'geographical area'
        ]):
            census_features.append(col)

    # SC/ST percentage
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in ['sc_percentage', 'st_percentage']):
            census_features.append(col)

    # Literacy
    for col in df.columns:
        col_lower = str(col).lower()
        if 'literacy rate' in col_lower or 'literates' in col_lower:
            census_features.append(col)

    # Infrastructure (roads, electricity, water)
    infra_keywords = [
        'pucca road', 'all weather road', 'black topped',
        'electricity', 'power', 'tap water', 'hand pump',
        'well', 'spring'
    ]
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in infra_keywords):
            census_features.append(col)

    # Water availability
    for col in df.columns:
        col_lower = str(col).lower()
        if 'water' in col_lower and 'status' not in col_lower and col not in census_features:
            census_features.append(col)

    # Forest and land use
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in ['forest', 'barren', 'cultivated', 'fallow']):
            census_features.append(col)

    # Deduplicate and filter to available columns
    all_features = list(dict.fromkeys(spatial_features + census_features))
    available = [f for f in all_features if f in df.columns]

    # Filter to features with >50% non-null values
    good_features = []
    for f in available:
        valid_ratio = df[f].notna().mean()
        if valid_ratio > 0.5:
            good_features.append(f)

    print(f"Selected {len(good_features)} features")

    # Create feature matrix
    X = df[good_features].copy()
    y = df['high_risk'].copy()

    # Fill remaining NaN with median
    for col in X.columns:
        if X[col].isna().sum() > 0:
            X[col] = X[col].fillna(X[col].median())

    # Convert all to float
    X = X.astype(float)

    return df, X, y, good_features


def train_xgboost(X, y):
    """Train XGBoost with stratified k-fold CV."""
    print("\n=== Training XGBoost Classifier ===")
    print(f"Features: {X.shape[1]}")
    print(f"Samples: {X.shape[0]:,}")
    print(f"Positive class: {y.sum():,} ({y.mean()*100:.1f}%)")

    # XGBoost model with tuned hyperparameters
    model = xgb.XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_alpha=0.1,
        reg_lambda=1.0,
        scale_pos_weight=1.0,  # ~1:1 class balance
        random_state=42,
        n_jobs=-1,
        eval_metric='auc',
        early_stopping_rounds=50,
    )

    # Stratified K-Fold cross-validation
    n_folds = 5
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)

    print(f"\n{n_folds}-Fold Stratified Cross-Validation:")

    # Cross-validation predictions
    oof_preds = np.zeros(len(X))
    oof_probs = np.zeros(len(X))
    fold_scores = []
    fold_models = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

        # Train with early stopping
        model_clone = xgb.XGBClassifier(**model.get_params())
        model_clone.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )

        # Predict
        y_pred = model_clone.predict(X_val)
        y_prob = model_clone.predict_proba(X_val)[:, 1]

        oof_preds[val_idx] = y_pred
        oof_probs[val_idx] = y_prob

        # Metrics
        acc = accuracy_score(y_val, y_pred)
        auc = roc_auc_score(y_val, y_prob)
        rec = recall_score(y_val, y_pred)
        prec = precision_score(y_val, y_pred)
        f1 = f1_score(y_val, y_pred)

        fold_scores.append({'fold': fold+1, 'accuracy': acc, 'auc': auc, 'recall': rec, 'precision': prec, 'f1': f1})
        fold_models.append(model_clone)

        print(f"  Fold {fold+1}: Acc={acc:.4f}, AUC={auc:.4f}, Recall={rec:.4f}, Prec={prec:.4f}, F1={f1:.4f}")

    # Overall metrics
    overall_acc = accuracy_score(y, oof_preds)
    overall_auc = roc_auc_score(y, oof_probs)
    overall_rec = recall_score(y, oof_preds)
    overall_prec = precision_score(y, oof_preds)
    overall_f1 = f1_score(y, oof_preds)

    print(f"\n  Overall: Acc={overall_acc:.4f}, AUC={overall_auc:.4f}, Recall={overall_rec:.4f}, Prec={overall_prec:.4f}, F1={overall_f1:.4f}")

    # Train final model on all data (remove early_stopping since no eval set)
    print("\nTraining final model on all data...")
    final_params = model.get_params()
    final_params.pop('early_stopping_rounds', None)
    final_model = xgb.XGBClassifier(**final_params)
    final_model.fit(X, y, verbose=False)

    return final_model, fold_models, fold_scores, oof_preds, oof_probs


def compute_shap_values(model, X, feature_names):
    """Compute SHAP values for model explainability."""
    print("\n=== Computing SHAP Values ===")

    # Use TreeExplainer for XGBoost (fast)
    explainer = shap.TreeExplainer(model)

    # Compute SHAP values on a sample (for speed)
    sample_size = min(5000, len(X))
    X_sample = X.sample(n=sample_size, random_state=42)
    print(f"Computing SHAP on {sample_size:,} samples...")

    shap_values = explainer.shap_values(X_sample)

    # Mean absolute SHAP values for feature importance
    mean_shap = np.abs(shap_values).mean(axis=0)
    importance_df = pd.DataFrame({
        'feature': feature_names,
        'mean_shap': mean_shap
    }).sort_values('mean_shap', ascending=False)

    print("\nTop 20 Most Important Features (by SHAP):")
    for i, row in importance_df.head(20).iterrows():
        print(f"  {row['feature']}: {row['mean_shap']:.4f}")

    return shap_values, X_sample, importance_df, explainer


def generate_visualizations(model, X, y, oof_probs, oof_preds, importance_df, shap_values, X_sample, full_df=None):
    """Generate all evaluation plots."""
    print("\n=== Generating Visualizations ===")

    # 1. Confusion Matrix
    fig, axes = plt.subplots(2, 3, figsize=(20, 12))

    # Confusion Matrix
    cm = confusion_matrix(y, oof_preds)
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', ax=axes[0, 0],
                xticklabels=['Low Risk', 'High Risk'], yticklabels=['Low Risk', 'High Risk'])
    axes[0, 0].set_title('Confusion Matrix', fontsize=14, fontweight='bold')
    axes[0, 0].set_xlabel('Predicted')
    axes[0, 0].set_ylabel('Actual')

    # 2. ROC Curve
    fpr, tpr, _ = roc_curve(y, oof_probs)
    axes[0, 1].plot(fpr, tpr, 'b-', linewidth=2, label=f'AUC = {roc_auc_score(y, oof_probs):.4f}')
    axes[0, 1].plot([0, 1], [0, 1], 'k--', alpha=0.5)
    axes[0, 1].set_title('ROC Curve', fontsize=14, fontweight='bold')
    axes[0, 1].set_xlabel('False Positive Rate')
    axes[0, 1].set_ylabel('True Positive Rate')
    axes[0, 1].legend(fontsize=12)
    axes[0, 1].grid(True, alpha=0.3)

    # 3. Precision-Recall Curve
    prec_curve, rec_curve, _ = precision_recall_curve(y, oof_probs)
    axes[0, 2].plot(rec_curve, prec_curve, 'r-', linewidth=2)
    axes[0, 2].set_title('Precision-Recall Curve', fontsize=14, fontweight='bold')
    axes[0, 2].set_xlabel('Recall')
    axes[0, 2].set_ylabel('Precision')
    axes[0, 2].grid(True, alpha=0.3)

    # 4. Top 15 Feature Importance (SHAP)
    top15 = importance_df.head(15)
    axes[1, 0].barh(range(len(top15)), top15['mean_shap'].values, color='steelblue')
    axes[1, 0].set_yticks(range(len(top15)))
    axes[1, 0].set_yticklabels(top15['feature'].values, fontsize=9)
    axes[1, 0].set_title('Top 15 Features (Mean |SHAP|)', fontsize=14, fontweight='bold')
    axes[1, 0].set_xlabel('Mean |SHAP value|')
    axes[1, 0].invert_yaxis()

    # 5. Prediction Distribution
    axes[1, 1].hist(oof_probs[y == 0], bins=50, alpha=0.6, label='Low Risk', color='green', density=True)
    axes[1, 1].hist(oof_probs[y == 1], bins=50, alpha=0.6, label='High Risk', color='red', density=True)
    axes[1, 1].set_title('Prediction Probability Distribution', fontsize=14, fontweight='bold')
    axes[1, 1].set_xlabel('Predicted Probability')
    axes[1, 1].set_ylabel('Density')
    axes[1, 1].legend(fontsize=12)
    axes[1, 1].grid(True, alpha=0.3)

    # 6. Risk by State
    if full_df is not None and 'State Name' in full_df.columns:
        state_risk = pd.DataFrame({'high_risk': y, 'State': full_df['State Name'].values})
    else:
        state_risk = pd.DataFrame({'high_risk': y, 'State': pd.read_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), usecols=['State Name'], low_memory=False)['State Name']})
    state_stats = state_risk.groupby('State').agg(
        total=('high_risk', 'count'),
        high_risk=('high_risk', 'sum')
    )
    state_stats['risk_rate'] = state_stats['high_risk'] / state_stats['total'] * 100
    state_stats = state_stats.sort_values('risk_rate', ascending=True)

    axes[1, 2].barh(range(len(state_stats)), state_stats['risk_rate'].values, color='coral')
    axes[1, 2].set_yticks(range(len(state_stats)))
    axes[1, 2].set_yticklabels(state_stats.index.values)
    axes[1, 2].set_title('Risk Rate by State (%)', fontsize=14, fontweight='bold')
    axes[1, 2].set_xlabel('High-Risk Village %')
    axes[1, 2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(MODEL_DIR, 'model_evaluation.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: models/model_evaluation.png")

    # SHAP Summary Plot
    print("  Generating SHAP summary plot...")
    plt.figure(figsize=(12, 8))
    shap.summary_plot(shap_values, X_sample, max_display=20, show=False)
    plt.title('SHAP Feature Importance', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(MODEL_DIR, 'shap_summary.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: models/shap_summary.png")


def predict_all_villages(df, model, features):
    """Apply the model to predict risk for all villages."""
    print("\n=== Predicting Risk for All Villages ===")

    X = df[features].copy()
    for col in X.columns:
        if X[col].isna().sum() > 0:
            X[col] = X[col].fillna(X[col].median())
    X = X.astype(float)

    # Predict
    df['model_risk_score'] = model.predict_proba(X)[:, 1]
    df['model_prediction'] = model.predict(X)

    # Classify into zones based on risk score
    # Canonical thresholds (must match predict.py): GREEN<0.4, ORANGE 0.4-0.9,
    # RED>=0.9 — RED cutoff raised 0.7 -> 0.9 on user request.
    df['model_risk_zone'] = 'GREEN'
    df.loc[df['model_risk_score'] >= 0.9, 'model_risk_zone'] = 'RED'
    df.loc[(df['model_risk_score'] >= 0.4) & (df['model_risk_score'] < 0.9), 'model_risk_zone'] = 'ORANGE'

    print("Model risk zone distribution:")
    print(df['model_risk_zone'].value_counts().to_string())
    print()

    print("Model risk by state:")
    for state in sorted(df['State Name'].unique()):
        state_df = df[df['State Name'] == state]
        red = (state_df['model_risk_zone'] == 'RED').sum()
        orange = (state_df['model_risk_zone'] == 'ORANGE').sum()
        green = (state_df['model_risk_zone'] == 'GREEN').sum()
        print(f"  {state}: RED={red:,}, ORANGE={orange:,}, GREEN={green:,}")

    return df


def save_model_artifacts(model, importance_df, fold_scores, features):
    """Save model and metadata."""
    print("\n=== Saving Model Artifacts ===")

    # Save model
    model_path = os.path.join(MODEL_DIR, 'red_zone_xgboost.json')
    model.save_model(model_path)
    print(f"  Model: {model_path}")

    # Save feature importance
    importance_df.to_csv(os.path.join(MODEL_DIR, 'feature_importance.csv'), index=False)
    print(f"  Feature importance: {MODEL_DIR}/feature_importance.csv")

    # Save fold scores
    scores_df = pd.DataFrame(fold_scores)
    scores_df.to_csv(os.path.join(MODEL_DIR, 'cv_scores.csv'), index=False)
    print(f"  CV scores: {MODEL_DIR}/cv_scores.csv")

    # Save feature list
    with open(os.path.join(MODEL_DIR, 'features.json'), 'w') as f:
        json.dump(features, f)
    print(f"  Features: {MODEL_DIR}/features.json")

    # Save model metadata
    metadata = {
        'model_type': 'XGBClassifier',
        'n_features': len(features),
        'cv_folds': 5,
        'metrics': {
            'accuracy': float(scores_df['accuracy'].mean()),
            'auc': float(scores_df['auc'].mean()),
            'recall': float(scores_df['recall'].mean()),
            'precision': float(scores_df['precision'].mean()),
            'f1': float(scores_df['f1'].mean()),
        },
        'features': features,
        'description': 'Red Zone prediction model for NE India villages'
    }
    with open(os.path.join(MODEL_DIR, 'model_metadata.json'), 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"  Metadata: {MODEL_DIR}/model_metadata.json")


def main():
    """Main execution."""
    print("=" * 60)
    print("Phase 3: Red Zone Prediction Model")
    print("=" * 60)

    # 1. Load and select features
    df, X, y, features = load_and_select_features()

    # 2. Train XGBoost
    model, fold_models, fold_scores, oof_preds, oof_probs = train_xgboost(X, y)

    # 3. SHAP explainability
    shap_values, X_sample, importance_df, explainer = compute_shap_values(model, X, features)

    # 4. Generate visualizations
    generate_visualizations(model, X, y, oof_probs, oof_preds, importance_df, shap_values, X_sample, full_df=df)

    # 5. Save model artifacts
    save_model_artifacts(model, importance_df, fold_scores, features)

    # 6. Predict for all villages
    df = predict_all_villages(df, model, features)

    # 7. Save final predictions
    df.to_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), index=False)
    print(f"\nSaved: {OUTPUT_DIR}/ne_india_village_features.csv")

    # Quick summary
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"Villages: {len(df):,}")
    print(f"Features used: {len(features)}")
    print(f"Model AUC: {fold_scores[-1]['auc']:.4f}")
    print(f"RED zone: {(df['model_risk_zone']=='RED').sum():,} villages")
    print(f"ORANGE zone: {(df['model_risk_zone']=='ORANGE').sum():,} villages")
    print(f"GREEN zone: {(df['model_risk_zone']=='GREEN').sum():,} villages")


if __name__ == '__main__':
    main()
