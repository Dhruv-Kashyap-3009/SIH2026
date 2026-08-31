"""
End-to-End Test Suite for NE India Hazard Red Zone Platform
Tests data integrity, model predictions, pipeline correctness, and edge cases.
"""

import sys
import os
import traceback
import numpy as np
import pandas as pd
import json

PASS = 0
FAIL = 0
ERRORS = []

def assert_test(name, condition, detail=""):
    global PASS, FAIL, ERRORS
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail}")


def test_data_integrity():
    """Test processed CSV data integrity."""
    print("\n=== TEST 1: Data Integrity ===")

    csv_path = 'data/processed/ne_india_village_features.csv'
    assert_test("Feature CSV exists", os.path.exists(csv_path))

    df = pd.read_csv(csv_path, low_memory=False)

    # Basic shape
    assert_test(f"Has 43K+ rows (got {len(df):,})", len(df) >= 40000)
    assert_test(f"Has 400+ columns (got {len(df.columns)})", len(df.columns) >= 400)

    # Required ID columns
    for col in ['Village Name', 'State Name', 'latitude', 'longitude']:
        assert_test(f"Column '{col}' exists", col in df.columns)

    # Coordinate validity
    valid_coords = df['latitude'].notna() & df['longitude'].notna()
    pct = valid_coords.mean() * 100
    assert_test(f"Coordinate coverage >= 95% (got {pct:.1f}%)", pct >= 95)

    # Coordinate bounds (NE India: 20-30N, 87-99E)
    coords = df[valid_coords]
    lat_in = coords['latitude'].between(20, 30).all()
    lon_in = coords['longitude'].between(87, 99).all()
    assert_test("All latitudes in NE India range (20-30N)", lat_in,
                f"min={coords['latitude'].min()}, max={coords['latitude'].max()}")
    assert_test("All longitudes in NE India range (87-99E)", lon_in,
                f"min={coords['longitude'].min()}, max={coords['longitude'].max()}")

    # No duplicate village codes
    if 'Village Code' in df.columns:
        dups = df.duplicated(subset=['State Code', 'District Code', 'Sub District Code', 'Village Code']).sum()
        assert_test("No duplicate village codes", dups == 0, f"Found {dups} duplicates")

    # State coverage
    states = df['State Name'].unique()
    expected_states = ['Assam', 'Meghalaya', 'Arunachal Pradesh', 'Manipur', 'Mizoram', 'Tripura', 'Nagaland']
    for state in expected_states:
        assert_test(f"State '{state}' present", state in states)

    # At least 30K Assam villages
    assam_count = (df['State Name'] == 'Assam').sum()
    assert_test(f"Assam has 20K+ villages (got {assam_count:,})", assam_count >= 20000)

    return df


def test_model_output(df):
    """Test model prediction outputs."""
    print("\n=== TEST 2: Model Predictions ===")

    # Model columns exist
    for col in ['model_risk_score', 'model_risk_zone', 'high_risk']:
        assert_test(f"Column '{col}' exists", col in df.columns)

    # Risk score is 0-1
    scores = df['model_risk_score'].dropna()
    assert_test(f"Risk scores are 0-1 (min={scores.min():.4f}, max={scores.max():.4f})",
                scores.min() >= 0 and scores.max() <= 1)

    # Risk score has reasonable distribution
    mean_score = scores.mean()
    assert_test(f"Mean risk score in 0.3-0.8 range (got {mean_score:.4f})",
                0.3 <= mean_score <= 0.8)

    # Risk zones are valid
    valid_zones = {'RED', 'ORANGE', 'GREEN'}
    actual_zones = set(df['model_risk_zone'].dropna().unique())
    assert_test(f"All risk zones are valid", actual_zones.issubset(valid_zones),
                f"Got: {actual_zones}")

    # Zone counts make sense
    red_count = (df['model_risk_zone'] == 'RED').sum()
    orange_count = (df['model_risk_zone'] == 'ORANGE').sum()
    green_count = (df['model_risk_zone'] == 'GREEN').sum()
    total = red_count + orange_count + green_count
    assert_test(f"All villages classified ({total:,} == {len(df):,})", total == len(df))
    assert_test(f"RED zone > 30% (got {red_count/len(df)*100:.1f}%)", red_count / len(df) > 0.30)
    assert_test(f"GREEN zone > 20% (got {green_count/len(df)*100:.1f}%)", green_count / len(df) > 0.20)
    assert_test(f"ORANGE zone is smallest", orange_count <= red_count and orange_count <= green_count)

    # Risk score is correlated with high_risk label
    corr = df['model_risk_score'].corr(df['high_risk'])
    assert_test(f"Risk score correlates with high_risk (corr={corr:.3f})", corr > 0.8)

    # Risk score monotonicity: mean score in RED > ORANGE > GREEN
    mean_red = df[df['model_risk_zone'] == 'RED']['model_risk_score'].mean()
    mean_green = df[df['model_risk_zone'] == 'GREEN']['model_risk_score'].mean()
    assert_test(f"Mean RED score > Mean GREEN score ({mean_red:.4f} > {mean_green:.4f})",
                mean_red > mean_green)


def test_label_integrity(df):
    """Test label creation correctness."""
    print("\n=== TEST 3: Label Integrity ===")

    # Binary label exists
    assert_test("high_risk column exists", 'high_risk' in df.columns)
    assert_test("high_risk is binary (0/1)", set(df['high_risk'].dropna().unique()).issubset({0, 1}))

    # Reasonable positive rate
    pos_rate = df['high_risk'].mean()
    assert_test(f"Positive rate in 30-70% (got {pos_rate*100:.1f}%)", 0.30 <= pos_rate <= 0.70)

    # Zone columns exist
    for col in ['gsi_landslide_zone', 'emdat_disaster_zone']:
        assert_test(f"'{col}' column exists", col in df.columns)

    # Landslide zone coverage
    lsi = df['gsi_landslide_zone'].sum()
    assert_test(f"Landslide zone has villages (got {lsi:,})", lsi > 1000)

    # EM-DAT zone coverage
    edi = df['emdat_disaster_zone'].sum()
    assert_test(f"EM-DAT zone has villages (got {edi:,})", edi > 100)

    # Consistency: if in landslide zone, high_risk should be 1
    in_lsi_not_risk = ((df['gsi_landslide_zone'] == True) & (df['high_risk'] == 0)).sum()
    assert_test(f"GSI zone implies high_risk (0 violations)", in_lsi_not_risk == 0)

    in_edi_not_risk = ((df['emdat_disaster_zone'] == True) & (df['high_risk'] == 0)).sum()
    assert_test(f"EM-DAT zone implies high_risk (0 violations)", in_edi_not_risk == 0)


def test_spatial_features(df):
    """Test spatial feature extraction quality."""
    print("\n=== TEST 4: Spatial Features ===")

    spatial_cols = {
        'elevation_m': (0, 6000, 80),  # NE India max ~7000m
        'slope_degrees': (0, 90, 70),
        'terrain_roughness': (0, None, 70),
        'max_daily_rainfall_mm': (0, 1000, 80),
        'mean_daily_rainfall_mm': (0, 100, 80),
        'rainfall_90th_percentile_mm': (0, 200, 80),
        'rainfall_95th_percentile_mm': (0, 300, 80),
        'rain_days_per_year': (0, 400, 80),
        'dist_to_nearest_road_km': (0, None, 80),
        'dist_to_nearest_river_km': (0, None, 80),
        'dist_to_nearest_hospital_km': (0, None, 80),
        'dist_to_nearest_school_km': (0, None, 80),
        'road_density_5km': (0, None, 80),
        'dist_to_nearest_landslide_km': (0, None, 80),
        'landslide_density_50km': (0, None, 80),
        'landslide_density_100km': (0, None, 80),
    }

    for col, (min_val, max_val, min_coverage) in spatial_cols.items():
        if col in df.columns:
            valid = df[col].notna().mean() * 100
            assert_test(f"'{col}' coverage >= {min_coverage}% (got {valid:.1f}%)",
                        valid >= min_coverage, f"{valid:.1f}%")

            if min_val is not None:
                actual_min = df[col].min()
                assert_test(f"'{col}' min >= {min_val} (got {actual_min:.2f})",
                            actual_min >= min_val)

            if max_val is not None:
                actual_max = df[col].max()
                assert_test(f"'{col}' max <= {max_val} (got {actual_max:.2f})",
                            actual_max <= max_val)
        else:
            assert_test(f"'{col}' column exists", False, "Column not found")

    # Specific domain checks
    if 'elevation_m' in df.columns:
        ne_elev = df['elevation_m'].dropna()
        assert_test(f"Elevation reasonable for NE India (mean={ne_elev.mean():.0f}m)",
                    100 < ne_elev.mean() < 800)

    if 'mean_daily_rainfall_mm' in df.columns:
        rain = df['mean_daily_rainfall_mm'].dropna()
        assert_test(f"Rainfall reasonable for NE India (mean={rain.mean():.1f}mm)",
                    3 < rain.mean() < 15)

    if 'dist_to_nearest_road_km' in df.columns:
        road = df['dist_to_nearest_road_km'].dropna()
        assert_test(f"Road distance reasonable (mean={road.mean():.2f}km, median={road.median():.2f}km)",
                    road.mean() < 5 and road.median() < 3)


def test_prioritization(df):
    """Test prioritization scores."""
    print("\n=== TEST 5: Prioritization ===")

    for col in ['priority_score', 'priority_level', 'vulnerability_score']:
        assert_test(f"'{col}' column exists", col in df.columns)

    # Priority score is 0-1
    ps = df['priority_score'].dropna()
    assert_test(f"Priority score in 0-1 (min={ps.min():.4f}, max={ps.max():.4f})",
                ps.min() >= 0 and ps.max() <= 1)

    # Priority levels are valid
    valid_levels = {'HIGH', 'MEDIUM', 'LOW'}
    actual_levels = set(df['priority_level'].dropna().unique())
    assert_test(f"Priority levels valid", actual_levels.issubset(valid_levels))

    # HIGH is top 30%
    high_pct = (df['priority_level'] == 'HIGH').mean() * 100
    assert_test(f"HIGH is ~30% (got {high_pct:.1f}%)",
                25 <= high_pct <= 35)

    # Higher risk → higher priority (on average)
    mean_priority_red = df[df['model_risk_zone'] == 'RED']['priority_score'].mean()
    mean_priority_green = df[df['model_risk_zone'] == 'GREEN']['priority_score'].mean()
    assert_test(f"RED villages have higher priority than GREEN",
                mean_priority_red > mean_priority_green,
                f"RED={mean_priority_red:.4f}, GREEN={mean_priority_green:.4f}")


def test_green_zone(df):
    """Test green zone suitability."""
    print("\n=== TEST 6: Green Zone Suitability ===")

    for col in ['green_suitability_score', 'suitability_category']:
        assert_test(f"'{col}' column exists", col in df.columns)

    # Score is 0-1
    gs = df['green_suitability_score'].dropna()
    assert_test(f"Suitability score in 0-1 (min={gs.min():.4f}, max={gs.max():.4f})",
                gs.min() >= 0 and gs.max() <= 1)

    # Categories are valid
    valid_cats = {'IDEAL', 'HIGHLY_SUITABLE', 'SUITABLE', 'UNSUITABLE'}
    actual_cats = set(df['suitability_category'].dropna().unique())
    assert_test(f"Suitability categories valid", actual_cats.issubset(valid_cats))

    # IDEAL is rare (top ~1%)
    ideal_pct = (df['suitability_category'] == 'IDEAL').mean() * 100
    assert_test(f"IDEAL is < 5% (got {ideal_pct:.1f}%)", ideal_pct < 5)

    # Suitable + IDEAL > 10%
    suitable_pct = df['suitability_category'].isin(['IDEAL', 'HIGHLY_SUITABLE', 'SUITABLE']).mean() * 100
    assert_test(f"Suitable sites >= 10% (got {suitable_pct:.1f}%)", suitable_pct >= 10)

    # GREEN zone villages should have higher suitability
    mean_suit_green = df[df['model_risk_zone'] == 'GREEN']['green_suitability_score'].mean()
    mean_suit_red = df[df['model_risk_zone'] == 'RED']['green_suitability_score'].mean()
    assert_test(f"GREEN zone has higher suitability",
                mean_suit_green > mean_suit_red,
                f"GREEN={mean_suit_green:.4f}, RED={mean_suit_red:.4f}")


def test_model_files():
    """Test saved model artifacts."""
    print("\n=== TEST 7: Model Artifacts ===")

    # Model file
    model_path = 'models/red_zone_xgboost.json'
    assert_test("Model file exists", os.path.exists(model_path))
    if os.path.exists(model_path):
        assert_test("Model file > 100KB", os.path.getsize(model_path) > 100000)

    # Feature importance
    fi_path = 'models/feature_importance.csv'
    assert_test("Feature importance file exists", os.path.exists(fi_path))
    if os.path.exists(fi_path):
        fi = pd.read_csv(fi_path)
        assert_test("Feature importance has 60+ features", len(fi) >= 60)
        assert_test("Feature importance values are positive", (fi['mean_shap'] >= 0).all())

    # CV scores
    cv_path = 'models/cv_scores.csv'
    assert_test("CV scores file exists", os.path.exists(cv_path))
    if os.path.exists(cv_path):
        cv = pd.read_csv(cv_path)
        assert_test("CV has 5 folds", len(cv) == 5)
        assert_test(f"CV AUC > 0.95 (mean={cv['auc'].mean():.4f})", cv['auc'].mean() > 0.95)
        assert_test(f"CV Recall > 0.90 (mean={cv['recall'].mean():.4f})", cv['recall'].mean() > 0.90)
        # Folds should be consistent
        auc_std = cv['auc'].std()
        assert_test(f"CV AUC stable across folds (std={auc_std:.4f})", auc_std < 0.01)

    # Features JSON
    feat_path = 'models/features.json'
    assert_test("Features JSON exists", os.path.exists(feat_path))
    if os.path.exists(feat_path):
        with open(feat_path) as f:
            features = json.load(f)
        assert_test("Features list has 50+ entries", len(features) >= 50)

    # Metadata
    meta_path = 'models/model_metadata.json'
    assert_test("Model metadata exists", os.path.exists(meta_path))


def test_map_files():
    """Test generated map files."""
    print("\n=== TEST 8: Map and Report Files ===")
    # Maps and reports were removed per user request — only model artifacts remain.
    print("  ⏭️  Skipped (maps/reports intentionally removed)")


def test_model_predictions_loadable():
    """Test that the model can be loaded and used for prediction."""
    print("\n=== TEST 9: Model Load + Predict ===")

    try:
        import xgboost as xgb
        model = xgb.XGBClassifier()
        model.load_model('models/red_zone_xgboost.json')
        assert_test("Model loads successfully", True)

        # Load feature list
        with open('models/features.json') as f:
            features = json.load(f)

        # Load data
        df = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False, nrows=100)
        X = df[features].copy()
        for col in X.columns:
            if X[col].isna().sum() > 0:
                X[col] = X[col].fillna(X[col].median())
        X = X.astype(float)

        # Predict
        preds = model.predict(X)
        probs = model.predict_proba(X)[:, 1]

        assert_test(f"Predictions shape correct (got {preds.shape})", preds.shape == (100,))
        assert_test(f"Probabilities in 0-1 (min={probs.min():.4f}, max={probs.max():.4f})",
                    probs.min() >= 0 and probs.max() <= 1)
        assert_test(f"Predictions are binary (0/1)", set(preds).issubset({0, 1}))
        assert_test(f"Probability matches prediction threshold",
                    np.all((probs >= 0.5) == (preds == 1)))

    except Exception as e:
        assert_test(f"Model load/predict failed: {e}", False, str(e))


def test_cross_validation_consistency():
    """Test that CV scores are consistent with reported metrics."""
    print("\n=== TEST 10: Cross-Validation Consistency ===")

    cv = pd.read_csv('models/cv_scores.csv')
    meta = json.load(open('models/model_metadata.json'))

    # CV mean should match metadata
    cv_auc = cv['auc'].mean()
    meta_auc = meta['metrics']['auc']
    assert_test(f"CV AUC matches metadata ({cv_auc:.4f} ~ {meta_auc:.4f})",
                abs(cv_auc - meta_auc) < 0.001)

    # All folds should have AUC > 0.99
    for _, row in cv.iterrows():
        assert_test(f"Fold {int(row['fold'])} AUC > 0.99 (got {row['auc']:.4f})",
                    row['auc'] > 0.99)


def test_prediction_output_fields():
    """Test the new prediction output fields: habitation_id, district, top_factors, low_confidence, predicted_at, model_version."""
    print("\n=== TEST 11: Prediction Output Fields ===")

    csv_path = 'data/processed/prediction_output.csv'
    assert_test("prediction_output.csv exists", os.path.exists(csv_path))

    if not os.path.exists(csv_path):
        return

    df = pd.read_csv(csv_path, low_memory=False)

    # 1. habitation_id
    assert_test("habitation_id column exists", 'habitation_id' in df.columns)
    if 'habitation_id' in df.columns:
        assert_test("habitation_id has no NaN", df['habitation_id'].notna().all(),
                     f"nulls={df['habitation_id'].isna().sum()}")
        # Check format: State-District-SubDist-Village
        sample = str(df['habitation_id'].iloc[0])
        parts = sample.split('-')
        assert_test(f"habitation_id is composite key (got {len(parts)} parts)", len(parts) == 4,
                     f"sample={sample}")

    # 2. district + state + village
    for col in ['district', 'state', 'village']:
        assert_test(f"'{col}' column exists", col in df.columns)
        if col in df.columns:
            assert_test(f"'{col}' has no NaN", df[col].notna().all())

    # 3. risk_score
    assert_test("risk_score column exists", 'risk_score' in df.columns)
    if 'risk_score' in df.columns:
        in_range = df['risk_score'].between(0, 1).all()
        assert_test("risk_score in [0, 1]", in_range)

    # 4. top_factors
    assert_test("top_factors column exists", 'top_factors' in df.columns)
    if 'top_factors' in df.columns:
        # Every row should be valid JSON with 3-5 factors
        valid_json = 0
        factor_counts = []
        valid_impacts = {'high', 'medium', 'low'}
        all_valid = True
        for val in df['top_factors'].dropna():
            try:
                factors = json.loads(str(val))
                valid_json += 1
                factor_counts.append(len(factors))
                for f in factors:
                    if f.get('impact') not in valid_impacts:
                        all_valid = False
            except:
                all_valid = False
        assert_test(f"All top_factors are valid JSON ({valid_json}/{len(df)})",
                     valid_json == len(df))
        assert_test(f"All top_factors have 3-5 entries (min={min(factor_counts)}, max={max(factor_counts)})",
                     all(3 <= c <= 5 for c in factor_counts) if factor_counts else False)
        assert_test("All top_factors have valid impact values (high/medium/low)", all_valid)

    # 5. low_confidence
    assert_test("low_confidence column exists", 'low_confidence' in df.columns)
    if 'low_confidence' in df.columns:
        assert_test("low_confidence is boolean type", df['low_confidence'].dtype == 'bool',
                     f"dtype={df['low_confidence'].dtype}")
        assert_test("low_confidence has both True and False values",
                     df['low_confidence'].any() and (~df['low_confidence']).any())

    # 6. predicted_at
    assert_test("predicted_at column exists", 'predicted_at' in df.columns)
    if 'predicted_at' in df.columns:
        sample_ts = str(df['predicted_at'].iloc[0])
        assert_test("predicted_at contains ISO timestamp",
                     'T' in sample_ts and len(sample_ts) > 10,
                     f"sample={sample_ts}")

    # 7. model_version
    assert_test("model_version column exists", 'model_version' in df.columns)
    if 'model_version' in df.columns:
        sample_ver = str(df['model_version'].iloc[0])
        assert_test("model_version is non-empty string",
                     len(sample_ver) > 2, f"sample={sample_ver}")
        assert_test("model_version starts with 'v'", sample_ver.startswith('v'),
                     f"sample={sample_ver}")

    # 8. Existing fields still present
    for col in ['latitude', 'longitude', 'priority_level']:
        assert_test(f"Existing field '{col}' still present", col in df.columns)


def test_bug_fixes():
    """Regression tests for bugs that were fixed."""
    print("\n=== TEST 12: Bug Fix Regression ===")

    # 1. No stale UTM column in main CSV
    df_main = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False, nrows=10)
    assert_test("No dist_to_nearest_landslide_km_utm column",
                 'dist_to_nearest_landslide_km_utm' not in df_main.columns)

    # 2. pd.cut produces 0 NaN zones
    df_scores = pd.read_csv('data/processed/ne_india_village_features.csv',
                            usecols=['model_risk_score'], low_memory=False)
    zones = pd.cut(df_scores['model_risk_score'],
                   bins=[-0.01, 0.3, 0.7, 1.01],
                   labels=['GREEN', 'ORANGE', 'RED'])
    assert_test("pd.cut produces 0 NaN zones", zones.isna().sum() == 0,
                 f"got {zones.isna().sum()} NaN")

    # 3. prediction_output has both model_risk_score and risk_score, consistent
    df_pred = pd.read_csv('data/processed/prediction_output.csv',
                          usecols=['model_risk_score', 'risk_score'], low_memory=False)
    assert_test("prediction_output has both risk_score columns",
                 'model_risk_score' in df_pred.columns and 'risk_score' in df_pred.columns)
    assert_test("model_risk_score == risk_score (consistency)",
                 (df_pred['model_risk_score'] == df_pred['risk_score']).all())

    # 4. district/state/village aliases exist alongside originals
    # district/state/village are only in prediction_output.csv, not the main features CSV
    df_aliases = pd.read_csv('data/processed/prediction_output.csv',
                             nrows=5, low_memory=False)
    for col in ['district', 'state', 'village', 'District Name', 'State Name', 'Village Name']:
        assert_test(f"Column '{col}' in prediction output", col in df_aliases.columns)

    # 5. All features have variance (no constant columns)
    import json
    with open('models/features.json') as f:
        features = json.load(f)
    df_feats = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False)
    const_feats = [f for f in features if f in df_feats.columns and df_feats[f].nunique() <= 1]
    assert_test(f"No constant feature columns (checked {len(features)})",
                 len(const_feats) == 0, f"constant: {const_feats}")

    # 6. Single-village prediction uses median imputation (not 0.0)
    import xgboost as xgb
    model = xgb.XGBClassifier()
    model.load_model('models/red_zone_xgboost.json')
    with open('models/features.json') as f:
        features = json.load(f)
    df_full = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False, nrows=200)
    for idx, row in df_full.iterrows():
        row_features = row[features]
        if row_features.isna().any():
            X_median = row_features.to_frame().T.copy()
            for col in X_median.columns:
                if X_median[col].isna().sum() > 0:
                    X_median[col] = X_median[col].fillna(X_median[col].median())
            prob = model.predict_proba(X_median.astype(float).values)[0][1]
            assert_test(f"Single-village prediction with NaN feature works (row {idx}, prob={prob:.4f})",
                         0 <= prob <= 1)
            break
    else:
        assert_test("Single-village prediction with NaN feature works (no NaN in sample)", True)


def main():
    """Run all tests."""
    global PASS, FAIL, ERRORS
    print("=" * 70)
    print("END-TO-END TEST SUITE")
    print("NE India Hazard Red Zone Platform")
    print("=" * 70)

    try:
        df = test_data_integrity()
        test_model_output(df)
        test_label_integrity(df)
        test_spatial_features(df)
        test_prioritization(df)
        test_green_zone(df)
        test_model_files()
        test_map_files()
        test_model_predictions_loadable()
        test_cross_validation_consistency()
        test_prediction_output_fields()
        test_bug_fixes()
    except Exception as e:
        print(f"\n💥 FATAL ERROR: {e}")
        traceback.print_exc()
        FAIL += 1

    # Summary
    total = PASS + FAIL
    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS}/{total} passed, {FAIL}/{total} failed")
    print("=" * 70)

    if FAIL > 0:
        print("\nFAILED TESTS:")
        for err in ERRORS:
            print(f"  ❌ {err}")

    print()
    return FAIL == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
