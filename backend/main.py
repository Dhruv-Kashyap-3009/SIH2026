"""
GIS Decision-Support Dashboard Backend
FastAPI app serving NE India hazard zone data.
"""

import os
import sys
import json
import hashlib
import numpy as np
import pandas as pd
import xgboost as xgb
import shap
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE_DIR, 'models')
DATA_DIR = os.path.join(BASE_DIR, 'data', 'processed')
SCRIPTS_DIR = os.path.join(BASE_DIR, 'scripts')

app = FastAPI(title="NE India Red Zone Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global State ─────────────────────────────────────────────────────────────
_model = None
_features = None
_metadata = None
_explainer = None
_df = None
_model_version = None
_loaded_at = None


def _load_model():
    global _model, _features, _metadata, _explainer, _model_version
    _model = xgb.XGBClassifier()
    _model.load_model(os.path.join(MODEL_DIR, 'red_zone_xgboost.json'))
    with open(os.path.join(MODEL_DIR, 'features.json')) as f:
        _features = json.load(f)
        if isinstance(_features, dict):
            _features = _features['features']
    with open(os.path.join(MODEL_DIR, 'model_metadata.json')) as f:
        _metadata = json.load(f)
    _explainer = shap.TreeExplainer(_model)
    _model_version = hashlib.sha256(
        open(os.path.join(MODEL_DIR, 'red_zone_xgboost.json'), 'rb').read()
    ).hexdigest()[:12]


def _load_data():
    global _df, _loaded_at
    csv_path = os.path.join(DATA_DIR, 'prediction_output.csv')
    _df = pd.read_csv(csv_path, low_memory=False)

    # Ensure key columns exist
    if 'habitation_id' not in _df.columns:
        _df['habitation_id'] = (
            _df['State Code'].astype(str) + '-' +
            _df['District Code'].astype(str) + '-' +
            _df['Sub District Code'].astype(str) + '-' +
            _df['Village Code'].astype(str)
        )

    # Ensure relocation_timeline exists
    if 'relocation_timeline' not in _df.columns:
        _df['relocation_timeline'] = 'MONITOR'
        _df.loc[_df['risk_score'] >= 0.85, 'relocation_timeline'] = 'IMMEDIATE'
        _df.loc[
            (_df['risk_score'] >= 0.7) & (_df['risk_score'] < 0.85),
            'relocation_timeline'
        ] = 'SHORT_TERM'
        _df.loc[
            (_df['risk_score'] >= 0.55) & (_df['risk_score'] < 0.7),
            'relocation_timeline'
        ] = 'MEDIUM_TERM'

    _loaded_at = datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def startup():
    print("Loading model...")
    _load_model()
    print(f"  OK Model loaded ({_metadata['n_features']} features, v{_model_version})")
    print("Loading village data...")
    _load_data()
    print(f"  OK Loaded {len(_df):,} villages")


# ── Helper ───────────────────────────────────────────────────────────────────
def _village_summary(row):
    """Convert a row to a minimal village dict for list views."""
    return {
        "village_id": str(row.get("habitation_id", "")),
        "village_name": str(row.get("Village Name", row.get("village", ""))),
        "district": str(row.get("District Name", row.get("district", ""))),
        "state": str(row.get("State Name", row.get("state", ""))),
        "latitude": float(row["latitude"]) if pd.notna(row.get("latitude")) else None,
        "longitude": float(row["longitude"]) if pd.notna(row.get("longitude")) else None,
        "risk_score": round(float(row["risk_score"]), 4),
        "risk_zone": str(row.get("predicted_risk_zone", "")),
        "relocation_timeline": str(row.get("relocation_timeline", "MONITOR")),
        "priority_level": str(row.get("priority_level", "")),
    }


def _village_detail(row):
    """Full village record including SHAP factors."""
    summary = _village_summary(row)
    # Parse top_factors if JSON string
    tf = row.get("top_factors", "[]")
    if isinstance(tf, str):
        try:
            summary["top_factors"] = json.loads(tf)
        except (json.JSONDecodeError, TypeError):
            summary["top_factors"] = []
    else:
        summary["top_factors"] = tf

    summary["low_confidence"] = bool(row.get("low_confidence", False))
    summary["model_version"] = str(row.get("model_version", f"v1.0-{_model_version}"))
    summary["predicted_at"] = str(row.get("predicted_at", ""))

    # Key physical features
    for col in ["elevation_m", "slope_degrees", "max_daily_rainfall_mm",
                 "dist_to_nearest_landslide_km", "landslide_density_50km",
                 "dist_to_nearest_flood_km", "flood_density_50km",
                 "landcover_class", "dist_to_nearest_road_km",
                 "dist_to_nearest_river_km"]:
        if col in row.index:
            val = row[col]
            summary[col] = round(float(val), 4) if pd.notna(val) else None

    # Carrying capacity if available
    cc_path = os.path.join(DATA_DIR, 'carrying_capacity.csv')
    if os.path.exists(cc_path):
        # Only lookup for GREEN/orange villages
        if row.get("predicted_risk_zone") in ("GREEN", "ORANGE"):
            summary["is_relocation_candidate"] = True
        else:
            summary["is_relocation_candidate"] = False

    return summary


def _live_shap(row_idx):
    """Compute live SHAP values for a single village."""
    row = _df.iloc[row_idx]
    X_row = row[_features].fillna(_df[_features].median()).values.reshape(1, -1).astype(float)
    shap_vals = _explainer.shap_values(X_row)[0]

    abs_shap = np.abs(shap_vals)
    top_idx = np.argsort(abs_shap)[-5:][::-1]

    factors = []
    for rank, fi in enumerate(top_idx):
        feat_name = _features[fi]
        feat_val = X_row[0, fi]
        shap_val = shap_vals[fi]
        impact = "high" if rank < 2 else "medium" if rank < 3 else "low"

        # Human-readable value
        if 'km' in feat_name:
            val_str = f"{feat_val:.1f} km"
        elif 'mm' in feat_name:
            val_str = f"{feat_val:.1f} mm"
        elif 'degrees' in feat_name:
            val_str = f"{feat_val:.1f}°"
        else:
            val_str = f"{feat_val:.2f}"

        factors.append({
            "feature": feat_name,
            "value": val_str,
            "impact": impact,
            "shap_value": round(float(shap_val), 4),
        })

    return factors


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    """Global statistics."""
    zone_counts = _df['predicted_risk_zone'].value_counts().to_dict()
    timeline_counts = _df['relocation_timeline'].value_counts().to_dict()
    state_counts = _df['State Name'].value_counts().to_dict() if 'State Name' in _df.columns else {}
    return {
        "total_villages": len(_df),
        "zone_distribution": {
            "RED": zone_counts.get("RED", 0),
            "ORANGE": zone_counts.get("ORANGE", 0),
            "GREEN": zone_counts.get("GREEN", 0),
        },
        "timeline_distribution": {
            "IMMEDIATE": timeline_counts.get("IMMEDIATE", 0),
            "SHORT_TERM": timeline_counts.get("SHORT_TERM", 0),
            "MEDIUM_TERM": timeline_counts.get("MEDIUM_TERM", 0),
            "MONITOR": timeline_counts.get("MONITOR", 0),
        },
        "states": state_counts,
        "model_version": f"v1.0-{_model_version}",
        "loaded_at": _loaded_at,
    }


@app.get("/api/villages")
def get_villages(
    state: Optional[str] = Query(None, description="Filter by state"),
    zone: Optional[str] = Query(None, description="Filter by risk zone (RED/ORANGE/GREEN)"),
    timeline: Optional[str] = Query(None, description="Filter by relocation timeline"),
    search: Optional[str] = Query(None, description="Search village/district name"),
    limit: int = Query(500, ge=1, le=50000),
    offset: int = Query(0, ge=0),
):
    """List villages with filters. Returns minimal fields for map rendering."""
    df = _df.copy()

    if state:
        df = df[df['State Name'].str.contains(state, case=False, na=False)]
    if zone:
        df = df[df['predicted_risk_zone'] == zone.upper()]
    if timeline:
        df = df[df['relocation_timeline'] == timeline.upper()]
    if search:
        mask = (
            df['Village Name'].str.contains(search, case=False, na=False) |
            df['District Name'].str.contains(search, case=False, na=False)
        )
        df = df[mask]

    total = len(df)
    df = df.iloc[offset:offset + limit]

    villages = [_village_summary(row) for _, row in df.iterrows()]
    return {"total": total, "offset": offset, "limit": limit, "villages": villages}


@app.get("/api/villages/{village_id}")
def get_village_detail(village_id: str):
    """Full detail for one village including live SHAP explanation."""
    mask = _df['habitation_id'].astype(str) == village_id
    matches = _df[mask]
    if len(matches) == 0:
        raise HTTPException(status_code=404, detail=f"Village {village_id} not found")

    row = matches.iloc[0]
    detail = _village_detail(row)

    # Live SHAP
    row_idx = matches.index[0]
    detail["live_shap"] = _live_shap(row_idx)

    return detail


@app.get("/api/matches/{village_id}")
def get_relocation_matches(village_id: str):
    """Get top relocation site matches for a given village."""
    matches_csv = os.path.join(DATA_DIR, 'relocation_matches.csv')
    if not os.path.exists(matches_csv):
        raise HTTPException(status_code=404, detail="Relocation matches not yet computed")

    matches_df = pd.read_csv(matches_csv, low_memory=False)
    village_matches = matches_df[matches_df['source_village_id'].astype(str) == village_id]

    if len(village_matches) == 0:
        return {"source_village_id": village_id, "matches": [], "message": "No safe site found within 50km"}

    results = []
    for _, m in village_matches.iterrows():
        results.append({
            "target_village_id": str(m.get("target_village_id", "")),
            "target_village_name": str(m.get("target_village_name", "")),
            "distance_km": round(float(m.get("distance_km", 0)), 1),
            "carrying_capacity_score": round(float(m.get("target_carrying_capacity_score", 0)), 3),
            "remaining_capacity": int(m.get("target_remaining_capacity", 0)),
        })

    return {"source_village_id": village_id, "matches": results[:5]}


@app.get("/api/state_summary")
def get_state_summary():
    """Summary stats per state."""
    summaries = []
    for state in sorted(_df['State Name'].unique()):
        sdf = _df[_df['State Name'] == state]
        zone_counts = sdf['predicted_risk_zone'].value_counts().to_dict()
        timeline_counts = sdf['relocation_timeline'].value_counts().to_dict()
        summaries.append({
            "state": state,
            "total_villages": len(sdf),
            "red": zone_counts.get("RED", 0),
            "orange": zone_counts.get("ORANGE", 0),
            "green": zone_counts.get("GREEN", 0),
            "immediate": timeline_counts.get("IMMEDIATE", 0),
            "short_term": timeline_counts.get("SHORT_TERM", 0),
            "medium_term": timeline_counts.get("MEDIUM_TERM", 0),
            "avg_risk_score": round(float(sdf['risk_score'].mean()), 4),
        })
    return {"states": summaries}


@app.post("/api/refresh")
def refresh_predictions():
    """
    Demo endpoint: run refresh_rainfall.py and return which villages changed zone.
    This simulates real-time updating for the hackathon demo.
    """
    import subprocess
    script_path = os.path.join(SCRIPTS_DIR, 'refresh_rainfall.py')
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="refresh_rainfall.py not found")

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=60,
            cwd=os.path.dirname(SCRIPTS_DIR),
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr[-500:]}

        # Reload data
        _load_data()

        # Parse output for changed villages
        changes = []
        for line in result.stdout.split('\n'):
            if 'CHANGED' in line or 'changed' in line.lower():
                changes.append(line.strip())

        return {
            "success": True,
            "message": f"Refresh complete. {len(changes)} village zones changed.",
            "changes": changes[:20],
            "total_villages": len(_df),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Refresh script timed out (60s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Serve Frontend ───────────────────────────────────────────────────────────
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')

@app.get("/")
def serve_frontend():
    index = os.path.join(FRONTEND_DIR, 'index.html')
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "API is running. Frontend not found."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
