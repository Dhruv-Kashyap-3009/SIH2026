#!/usr/bin/env python3
"""
Re-run the trained models over all 43,996 villages and refresh the model-owned
prediction columns of data/processed/prediction_output.csv IN PLACE, stamping a
brand-new `predicted_at` (a new model run).

Why in-place instead of a from-scratch `predict.py --save`?
prediction_output.csv is the canonical master file: besides the model outputs
(risk_score, zones, relocation_timeline, top_factors, susceptibility_*) it also
carries downstream-module columns written by social_vulnerability.py,
hazard_decomposition.py, optimize_thresholds.py, uncertainty_quantification.py
and refresh_rainfall.py (vulnerability_score, landslide/flood risk scores,
recommended_action, fixed/quantile zone variants, prediction_uncertainty, …).
Rebuilding the file from the feature matrix alone would DROP all of those and
break every downstream consumer (VYOMA export, seed, the test suite).

What this script does:
  1. loads the CURRENT prediction_output.csv (all ~463 columns preserved),
  2. re-runs BOTH trained models (historical + leakage-free susceptibility)
     with the exact same code paths as predict.py (same model files + same
     feature values -> deterministic, identical probabilities — which is the
     honest meaning of "re-run the model on unchanged data"),
  3. re-derives the model-owned columns: model_risk_score/risk_score,
     predicted_risk_zone, relocation_timeline, per-village SHAP top_factors,
     low_confidence, susceptibility_score/_risk_zone, is_novel_red_zone,
  4. stamps predicted_at = now (UTC) and model_version = model-file hash,
  5. saves back over data/processed/prediction_output.csv and prints a
     machine-readable marker line consumed by the backend refresh job:
         REFRESH_PREDICTED_AT=<iso-timestamp>

The rest of the refresh chain (relocation sites -> VYOMA exports -> static
bundles -> `npm run seed`) is orchestrated by the backend refresh endpoint
(POST /api/admin/refresh), not here.

Usage:
    python scripts/refresh_predictions.py
"""

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import predict  # same-module reuse keeps the exact predict.py code paths

DATA_DIR = os.path.join('data', 'processed')
PRED_PATH = os.path.join(DATA_DIR, 'prediction_output.csv')
MODEL_DIR = 'models'


def main():
    print("=" * 60)
    print("Model re-run: refreshing predictions for all villages")
    print("=" * 60)

    if not os.path.exists(PRED_PATH):
        print(f"  ❌ {PRED_PATH} not found — nothing to refresh.")
        sys.exit(1)

    print("  Loading current prediction_output.csv (keeps all columns)...")
    df = pd.read_csv(PRED_PATH, low_memory=False)
    n_rows = len(df)
    print(f"  ✅ Loaded {n_rows:,} villages x {len(df.columns)} columns")
    if 'habitation_id' not in df.columns:
        print("  ❌ habitation_id column missing — refusing to refresh.")
        sys.exit(1)

    # ── Historical model (66 features, incl. documented leaky comparison) ──
    print("\n  Loading historical model...")
    model, features, metadata = predict.load_model()
    # Guard: every feature the model needs must exist on the current CSV.
    missing = [f for f in features if f not in df.columns]
    if missing:
        print(f"  ❌ {len(missing)} historical features missing from "
              f"prediction_output.csv (first: {missing[:5]}) — refusing.")
        sys.exit(1)
    print(f"  ✅ Historical model ({metadata['n_features']} features)")

    print("  Re-running predictions + per-village SHAP...")
    df_new, X = predict.predict_all(model, features, df)
    print("  ✅ Predictions complete")

    # ── Susceptibility model (59 leakage-free features — canonical) ────────
    susc_path = os.path.join(MODEL_DIR, 'susceptibility_xgboost.json')
    susc_feat_path = os.path.join(MODEL_DIR, 'susceptibility_features.json')
    if os.path.exists(susc_path) and os.path.exists(susc_feat_path):
        import xgboost as xgb
        print("\n  Loading susceptibility model...")
        susc_model = xgb.XGBClassifier()
        susc_model.load_model(susc_path)
        with open(susc_feat_path) as f:
            susc_features = json.load(f)
        missing_s = [f for f in susc_features if f not in df_new.columns]
        if missing_s:
            print(f"  ❌ {len(missing_s)} susceptibility features missing from "
                  f"prediction_output.csv (first: {missing_s[:5]}) — refusing.")
            sys.exit(1)
        print(f"  ✅ Susceptibility model ({len(susc_features)} features)")
        print("  Running susceptibility model predictions...")
        X_susc = df_new[susc_features].copy()
        X_susc = X_susc.fillna(X_susc.median())
        susc_probs = susc_model.predict_proba(X_susc)[:, 1]
        df_new['susceptibility_score'] = susc_probs
        # Canonical zone thresholds (must match predict.py / train_model.py):
        # GREEN < 0.4, ORANGE 0.4-0.9, RED >= 0.9 — RED cutoff raised from 0.7
        # on user request so only the most extreme scores are RED.
        df_new['susceptibility_risk_zone'] = 'GREEN'
        df_new.loc[susc_probs >= 0.9, 'susceptibility_risk_zone'] = 'RED'
        df_new.loc[(susc_probs >= 0.4) & (susc_probs < 0.9),
                   'susceptibility_risk_zone'] = 'ORANGE'
        print("  ✅ Susceptibility predictions complete")

        # ── Relocation timeline (zone-aligned, canonical) ──────────────────
        # Recompute from the susceptibility score with the same 0.9/0.4
        # cutoffs as susceptibility_risk_zone (predict.py no longer derives it
        # from the historical risk_score inside predict_all), so the tier shown
        # as relocation_priority can never contradict the zone shown as
        # risk_level: GREEN -> MONITOR, ORANGE -> MEDIUM_TERM, RED ->
        # SHORT_TERM / IMMEDIATE (IMMEDIATE only in disaster/high-density
        # areas).
        df_new = predict.compute_relocation_timeline(df_new, 'susceptibility_score')

    # ── Novel red zone detection (re-derived from refreshed zones) ─────────
    if 'susceptibility_risk_zone' in df_new.columns:
        has_landslide = (df_new.get('gsi_landslide_zone',
                                    pd.Series(0, index=df_new.index)) == 1)
        has_emdat = (df_new.get('emdat_disaster_zone',
                                pd.Series(0, index=df_new.index)) == 1)
        has_flood = (df_new.get('dfo_flood_zone',
                                pd.Series(0, index=df_new.index)) == 1)
        has_event = has_landslide | has_emdat | has_flood
        df_new['is_novel_red_zone'] = (
            (df_new['susceptibility_risk_zone'] == 'RED') & (~has_event)
        )

    # ── Stamp the new run ─────────────────────────────────────────────────
    predicted_at = datetime.now(timezone.utc).isoformat()
    model_ver = predict._model_version()
    df_new['predicted_at'] = predicted_at
    df_new['model_version'] = model_ver

    if len(df_new) != n_rows or df_new['habitation_id'].is_unique is False:
        print("  ❌ Row count or habitation_id uniqueness changed — aborting "
              "without saving.")
        sys.exit(1)

    # Sanity: predictions are deterministic, so zone mix must be unchanged.
    def zone_counts(d):
        return {z: int((d.get('susceptibility_risk_zone') == z).sum())
                for z in ('RED', 'ORANGE', 'GREEN')}
    if 'susceptibility_risk_zone' in df.columns and \
            'susceptibility_risk_zone' in df_new.columns:
        old_c = zone_counts(df)
        new_c = zone_counts(df_new)
        if old_c != new_c:
            print(f"  ⚠ Zone distribution changed: {old_c} -> {new_c}")
        else:
            print(f"  ✅ Zone distribution unchanged (deterministic re-run): "
                  f"{new_c}")

    print(f"\n  💾 Saving refreshed predictions -> {PRED_PATH}")
    df_new.to_csv(PRED_PATH, index=False)
    print(f"  ✅ Saved {len(df_new):,} rows")
    print(f"  🕒 predicted_at: {predicted_at}")
    print(f"  🏷  model_version: {model_ver}")
    print(f"\nREFRESH_PREDICTED_AT={predicted_at}")


if __name__ == '__main__':
    main()
