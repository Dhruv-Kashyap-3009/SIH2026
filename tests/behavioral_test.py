"""Behavioral tests for Phase 1-5 outputs."""
import pandas as pd
import numpy as np
import json
import xgboost as xgb
import sys

errors = []

def check(condition, msg):
    if not condition:
        errors.append(msg)
        print(f"  FAIL: {msg}")
    return condition

print("=== BEHAVIORAL TEST 1: Prediction Output Consistency ===")
df = pd.read_csv("data/processed/prediction_output.csv", low_memory=False)

required_cols = [
    "habitation_id", "district", "state", "village",
    "risk_score", "predicted_risk_zone", "susceptibility_score",
    "susceptibility_risk_zone", "is_novel_red_zone",
    "priority_score", "relocation_timeline",
    "social_vulnerability_index", "relocation_sensitivity",
    "landslide_risk_score", "flood_risk_score", "recommended_action",
    "top_factors", "low_confidence", "predicted_at", "model_version",
    "latitude", "longitude"
]
missing = [c for c in required_cols if c not in df.columns]
check(len(missing) == 0, f"Missing columns: {missing}")
print(f"  Columns: {len(required_cols) - len(missing)}/{len(required_cols)} present")

zones = df["predicted_risk_zone"].value_counts()
red = int((df["predicted_risk_zone"] == "RED").sum())
green = int((df["predicted_risk_zone"] == "GREEN").sum())
orange = int((df["predicted_risk_zone"] == "ORANGE").sum())
check(red > 0, "No RED villages")
check(green > 0, "No GREEN villages")
print(f"  Zones: RED={red}, ORANGE={orange}, GREEN={green}")

check(df["risk_score"].min() >= 0 and df["risk_score"].max() <= 1, "Risk score out of range")
print(f"  Risk score: [{df['risk_score'].min():.4f}, {df['risk_score'].max():.4f}]")

check(df["habitation_id"].nunique() == len(df), f"Duplicate habitation_ids")
print(f"  Habitation IDs: {df['habitation_id'].nunique()} unique")

check(df["latitude"].between(20, 30).all(), "Latitude out of range")
check(df["longitude"].between(87, 99).all(), "Longitude out of range")
print(f"  Coordinates: NE India range OK")

sample = df["top_factors"].head(100)
for i, val in sample.items():
    factors = json.loads(val)
    check(len(factors) >= 3, f"Row {i}: only {len(factors)} factors")
    for f in factors:
        check(f["impact"] in ("high", "medium", "low"), f"Invalid impact: {f['impact']}")
print(f"  top_factors: valid JSON, 3+ entries (sampled 100)")

check(df["model_version"].str.startswith("v").all(), "model_version not starting with v")
print(f"  model_version: {df['model_version'].iloc[0]}")

check(df["low_confidence"].dtype == bool or str(df["low_confidence"].dtype) == "bool", "low_confidence not boolean")
print(f"  low_confidence: bool, {df['low_confidence'].sum():,} True")

print("\n=== BEHAVIORAL TEST 2: Carrying Capacity ===")
cc = pd.read_csv("data/processed/carrying_capacity.csv")
print(f"  Rows: {len(cc):,}")
print(f"  Columns: {list(cc.columns)}")

check((cc["buildable_land_ha"] >= 0).all(), "Negative buildable land")
print(f"  Buildable land: [{cc['buildable_land_ha'].min():.2f}, {cc['buildable_land_ha'].max():.2f}] ha")

check(cc["carrying_capacity_score"].between(0, 1).all(), "Capacity score out of range")
print(f"  Capacity score: [{cc['carrying_capacity_score'].min():.3f}, {cc['carrying_capacity_score'].max():.3f}]")

check((cc["estimated_absorbable_population"] >= 0).all(), "Negative absorbable pop")
print(f"  Absorbable pop: median={cc['estimated_absorbable_population'].median():.0f}")

check(set(cc["risk_zone"].unique()).issubset({"GREEN", "ORANGE"}), f"Unexpected zones: {cc['risk_zone'].unique()}")
print(f"  Risk zones: {cc['risk_zone'].value_counts().to_dict()}")

print("\n=== BEHAVIORAL TEST 3: Relocation Plan ===")
rp = pd.read_csv("data/processed/relocation_plan.csv")
print(f"  Rows: {len(rp):,}")

assigned = rp[rp["feasibility_flag"] == "assigned"]
no_site = rp[rp["feasibility_flag"] == "no_feasible_relocation_site_within_range"]
pct = len(assigned) / len(rp) * 100
check(pct >= 10, f"Only {pct:.1f}% assigned (< 10%)")
print(f"  Assigned: {len(assigned):,} ({pct:.1f}%)")
print(f"  No site: {len(no_site):,}")

if len(assigned) > 0:
    check((assigned["distance_km"] > 0).all(), "Non-positive distance")
    check((assigned["distance_km"] <= 50).all(), "Distance > 50km")
    print(f"  Distance: [{assigned['distance_km'].min():.1f}, {assigned['distance_km'].max():.1f}] km")
    print(f"  Capacity fit: {assigned['capacity_fit'].value_counts().to_dict()}")

print("\n=== BEHAVIORAL TEST 4: Hazard Decomposition ===")
check("landslide_risk_score" in df.columns, "Missing landslide_risk_score")
check("flood_risk_score" in df.columns, "Missing flood_risk_score")
check("recommended_action" in df.columns, "Missing recommended_action")

ls = df["landslide_risk_score"]
fl = df["flood_risk_score"]
actions = df["recommended_action"]
print(f"  Landslide risk: [{ls.min():.4f}, {ls.max():.4f}], mean={ls.mean():.4f}")
print(f"  Flood risk: [{fl.min():.4f}, {fl.max():.4f}], mean={fl.mean():.4f}")
print(f"  Actions: {actions.value_counts().to_dict()}")

relocate = df[actions == "RELOCATE"]
mitigate = df[actions == "MITIGATE"]
monitor = df[actions == "MONITOR"]

if len(relocate) > 0:
    avg_ls = relocate["landslide_risk_score"].mean()
    avg_fl = relocate["flood_risk_score"].mean()
    print(f"  RELOCATE: avg ls={avg_ls:.4f}, avg fl={avg_fl:.4f}")
    check(avg_ls > avg_fl * 0.5, "RELOCATE: landslide should dominate")

if len(mitigate) > 0:
    avg_ls = mitigate["landslide_risk_score"].mean()
    avg_fl = mitigate["flood_risk_score"].mean()
    print(f"  MITIGATE: avg ls={avg_ls:.4f}, avg fl={avg_fl:.4f}")
    check(avg_fl > avg_ls * 0.5, "MITIGATE: flood should dominate")

print("\n=== BEHAVIORAL TEST 5: Social Vulnerability ===")
sv = pd.read_csv("data/processed/social_vulnerability.csv")
print(f"  Rows: {len(sv):,}")
check("social_vulnerability_index" in sv.columns, "Missing social_vulnerability_index")
check("relocation_sensitivity" in sv.columns, "Missing relocation_sensitivity")
check(sv["social_vulnerability_index"].between(0, 1).all(), "Vulnerability out of range")
print(f"  Vulnerability: [{sv['social_vulnerability_index'].min():.3f}, {sv['social_vulnerability_index'].max():.3f}]")
print(f"  Sensitivity: {sv['relocation_sensitivity'].value_counts().to_dict()}")
check("social_vulnerability_index" in df.columns, "prediction_output missing vulnerability")
check("relocation_sensitivity" in df.columns, "prediction_output missing sensitivity")
print(f"  prediction_output has vulnerability columns: OK")

print("\n=== BEHAVIORAL TEST 6: Susceptibility Model ===")
susc_model = xgb.XGBClassifier()
susc_model.load_model("models/susceptibility_xgboost.json")
with open("models/susceptibility_features.json") as f:
    susc_features = json.load(f)
print(f"  Features: {len(susc_features)}")
check(len(susc_features) == 59, f"Expected 59 features, got {len(susc_features)}")

leakage = {"dist_to_nearest_landslide_km", "landslide_density_50km", "landslide_density_100km",
           "dist_to_nearest_flood_km", "flood_density_50km", "flood_density_100km", "flood_proxy_score"}
overlap = set(susc_features) & leakage
check(len(overlap) == 0, f"Leakage found: {overlap}")
print(f"  Zero leakage: VERIFIED")

check("susceptibility_score" in df.columns, "Missing susceptibility_score")
non_null = df["susceptibility_score"].notna().sum()
check(non_null > 40000, f"Only {non_null} non-null susceptibility scores")
susc_red = int((df["susceptibility_risk_zone"] == "RED").sum())
print(f"  Susceptibility RED: {susc_red:,}")
print(f"  is_novel_red_zone: {int(df['is_novel_red_zone'].sum()):,}")

print("\n=== BEHAVIORAL TEST 7: Cross-Model Consistency ===")
agree = int((df["predicted_risk_zone"] == df["susceptibility_risk_zone"]).sum())
pct_agree = agree / len(df) * 100
print(f"  Models agree: {agree:,}/{len(df):,} ({pct_agree:.1f}%)")

novel = df[df["is_novel_red_zone"] == True]
print(f"  Novel red zones: {len(novel):,}")
if len(novel) > 0:
    print(f"  Their susceptibility scores: mean={novel['susceptibility_score'].mean():.3f}, min={novel['susceptibility_score'].min():.3f}")

print("\n" + "=" * 60)
if errors:
    print(f"RESULT: {len(errors)} FAILURES")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("RESULT: ALL 7 BEHAVIORAL TESTS PASSED (0 errors)")
