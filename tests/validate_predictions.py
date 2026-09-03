"""
Ground Truth Validation: Are the model predictions correct?
Tests against EM-DAT, GSI landslides, domain knowledge, and geography.
"""

import pandas as pd
import numpy as np
import geopandas as gpd

df = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False)

print("=" * 70)
print("GROUND TRUTH VALIDATION: Are Predictions Correct?")
print("=" * 70)

# ============================================================
# 1. EM-DAT HISTORICAL DISASTER VALIDATION
# ============================================================
print()
print("=" * 70)
print("TEST 1: EM-DAT Historical Disaster Validation")
print("=" * 70)
print("Checking: Villages in known EM-DAT disaster zones should be RED/ORANGE")

emdat = pd.read_excel('data/raw/emdat/public_emdat_custom_request_2026-08-29_503d005a-ed3a-40fc-bdef-dda52964b0ca.xlsx', header=0)
ne_states = ['Assam', 'Meghalaya', 'Arunachal', 'Manipur', 'Mizoram', 'Tripura', 'Nagaland', 'Sikkim']
ne_emdat = emdat[emdat['Location'].fillna('').str.contains('|'.join(ne_states), case=False)]

# Check specific known disasters
print()
print("Known NE India disasters from EM-DAT:")
for _, row in ne_emdat[ne_emdat['Disaster Type'] == 'Flood'].head(10).iterrows():
    loc = str(row['Location'])[:60]
    year = row.get('Start Year', '?')
    deaths = row.get('Total Deaths', '?')
    affected = row.get('Total Affected', '?')
    print(f"  {int(year)} Flood: {loc}... (Deaths: {deaths}, Affected: {affected})")

# Check if villages in EM-DAT zones are correctly flagged
emdat_zone = df[df['emdat_disaster_zone'] == True]
print(f"\nVillages in EM-DAT zones: {len(emdat_zone):,}")
red_pct = (emdat_zone['model_risk_zone'] == 'RED').mean() * 100
orange_pct = (emdat_zone['model_risk_zone'] == 'ORANGE').mean() * 100
green_pct = (emdat_zone['model_risk_zone'] == 'GREEN').mean() * 100
print(f"  Correctly flagged RED: {(emdat_zone['model_risk_zone']=='RED').sum():,} ({red_pct:.1f}%)")
print(f"  Correctly flagged ORANGE: {(emdat_zone['model_risk_zone']=='ORANGE').sum():,} ({orange_pct:.1f}%)")
print(f"  Missed (GREEN): {(emdat_zone['model_risk_zone']=='GREEN').sum():,} ({green_pct:.1f}%)")

# ============================================================
# 2. GSI LANDSLIDE CLUSTER VALIDATION
# ============================================================
print()
print("=" * 70)
print("TEST 2: GSI Landslide Cluster Validation")
print("=" * 70)
print("Checking: Villages near dense landslide clusters should be RED")

landslide_gdf = gpd.read_file('data/raw/gsi_landslide/GSI_Landslide_Inventory.shp')
ne_landslides = landslide_gdf[
    landslide_gdf.geometry.x.between(87, 99) &
    landslide_gdf.geometry.y.between(21, 30)
]
print(f"NE India landslides: {len(ne_landslides):,}")

# Group landslides by state
ls_by_state = ne_landslides.groupby('STATE').size().sort_values(ascending=False)
print(f"\nLandslides by state:")
for state, count in ls_by_state.head(8).items():
    state_df = df[df['State Name'] == state]
    if len(state_df) > 0:
        state_red_pct = (state_df['model_risk_zone'] == 'RED').mean() * 100
        print(f"  {state}: {count:,} landslides, RED zone: {state_red_pct:.1f}%")

# ============================================================
# 3. DOMAIN KNOWLEDGE VALIDATION
# ============================================================
print()
print("=" * 70)
print("TEST 3: Domain Knowledge Validation")
print("=" * 70)

red = df[df['model_risk_zone'] == 'RED']
green = df[df['model_risk_zone'] == 'GREEN']

checks = [
    ("Closer to landslides", 'dist_to_nearest_landslide_km', '<'),
    ("Higher rainfall", 'mean_daily_rainfall_mm', '>'),
    ("More landslide density", 'landslide_density_50km', '>'),
    ("Further from hospitals", 'dist_to_nearest_hospital_km', '>'),
    ("More rain days", 'rain_days_per_year', '>'),
]

all_correct = True
for desc, col, direction in checks:
    if col in red.columns and col in green.columns:
        red_mean = red[col].mean()
        green_mean = green[col].mean()
        if direction == '<':
            correct = red_mean < green_mean
        else:
            correct = red_mean > green_mean

        status = 'CORRECT' if correct else 'WRONG'
        if not correct:
            all_correct = False
        print(f"  {desc}: RED={red_mean:.2f} vs GREEN={green_mean:.2f} [{status}]")

# Close to landslides
close_to_ls = df[df['dist_to_nearest_landslide_km'] < 5]
print(f"\nVillages within 5km of landslide: {len(close_to_ls):,}")
print(f"  RED: {(close_to_ls['model_risk_zone']=='RED').mean()*100:.1f}%")
print(f"  ORANGE: {(close_to_ls['model_risk_zone']=='ORANGE').mean()*100:.1f}%")
print(f"  GREEN: {(close_to_ls['model_risk_zone']=='GREEN').mean()*100:.1f}%")

# Safe villages
safe = df[(df['dist_to_nearest_landslide_km'] > 50) & (df['landslide_density_50km'] < 5)]
print(f"\nVillages >50km from landslides, <5 nearby: {len(safe):,}")
print(f"  GREEN: {(safe['model_risk_zone']=='GREEN').mean()*100:.1f}%")
print(f"  RED: {(safe['model_risk_zone']=='RED').mean()*100:.1f}%")

# ============================================================
# 4. STATE CASE STUDIES
# ============================================================
print()
print("=" * 70)
print("TEST 4: State Case Studies (Domain Expertise)")
print("=" * 70)

for state_name, known_for in [
    ('Mizoram', 'landslides, steep terrain'),
    ('Assam', 'floods, flatter Brahmaputra valley'),
    ('Meghalaya', 'extreme rainfall (Cherrapunji)'),
]:
    sdf = df[df['State Name'] == state_name]
    print(f"\n{state_name.upper()} (known for: {known_for}):")
    print(f"  Villages: {len(sdf):,}")
    print(f"  RED zone: {(sdf['model_risk_zone']=='RED').mean()*100:.1f}%")
    print(f"  Avg elevation: {sdf['elevation_m'].mean():.0f}m")
    print(f"  Avg slope: {sdf['slope_degrees'].mean():.1f} deg")
    print(f"  Avg max rainfall: {sdf['max_daily_rainfall_mm'].mean():.0f}mm")
    print(f"  Avg landslide density (50km): {sdf['landslide_density_50km'].mean():.0f}")
    print(f"  In GSI landslide zone: {sdf['gsi_landslide_zone'].sum():,}/{len(sdf):,}")

# ============================================================
# 5. GEOGRAPHIC SANITY CHECK
# ============================================================
print()
print("=" * 70)
print("TEST 5: Geographic Sanity Check")
print("=" * 70)

hill_states = ['Mizoram', 'Nagaland', 'Manipur', 'Meghalaya', 'Arunachal Pradesh']
plains_states = ['Assam', 'Tripura']

hill_red = df[df['State Name'].isin(hill_states)]['model_risk_zone'].apply(lambda x: x == 'RED').mean() * 100
plains_red = df[df['State Name'].isin(plains_states)]['model_risk_zone'].apply(lambda x: x == 'RED').mean() * 100
print(f"Hill states avg RED: {hill_red:.1f}%")
print(f"Plains states avg RED: {plains_red:.1f}%")
print(f"Hill > Plains: {'YES - CORRECT' if hill_red > plains_red else 'NO - ISSUE'}")

# ============================================================
# 6. INDIVIDUAL VILLAGE SPOT-CHECKS
# ============================================================
print()
print("=" * 70)
print("TEST 6: Individual Village Spot-Checks")
print("=" * 70)

# Pick 5 highest risk villages and verify they have bad characteristics
print("\nTop 5 Highest Risk Villages:")
top5 = df.nlargest(5, 'model_risk_score')
for _, v in top5.iterrows():
    print(f"\n  {v['Village Name']} ({v['State Name']}, {v['District Name']})")
    print(f"    Risk Score: {v['model_risk_score']:.4f}")
    print(f"    Elevation: {v.get('elevation_m', 0):.0f}m, Slope: {v.get('slope_degrees', 0):.1f} deg")
    print(f"    Max Rainfall: {v.get('max_daily_rainfall_mm', 0):.0f}mm")
    print(f"    Dist Landslide: {v.get('dist_to_nearest_landslide_km', 0):.1f}km")
    print(f"    Landslide Density (50km): {v.get('landslide_density_50km', 0):.0f}")
    print(f"    In GSI zone: {v.get('gsi_landslide_zone', False)}")
    print(f"    In EM-DAT zone: {v.get('emdat_disaster_zone', False)}")

# Pick 5 lowest risk villages
print("\nTop 5 Lowest Risk Villages:")
bot5 = df.nsmallest(5, 'model_risk_score')
for _, v in bot5.iterrows():
    print(f"\n  {v['Village Name']} ({v['State Name']}, {v['District Name']})")
    print(f"    Risk Score: {v['model_risk_score']:.4f}")
    print(f"    Elevation: {v.get('elevation_m', 0):.0f}m, Slope: {v.get('slope_degrees', 0):.1f} deg")
    print(f"    Dist Landslide: {v.get('dist_to_nearest_landslide_km', 0):.1f}km")
    print(f"    Landslide Density (50km): {v.get('landslide_density_50km', 0):.0f}")

# ============================================================
# 7. OVERALL VERDICT
# ============================================================
print()
print("=" * 70)
print("OVERALL VERDICT")
print("=" * 70)
print(f"  EM-DAT detection rate (RED+ORANGE in EM-DAT zones): {red_pct + orange_pct:.1f}%")
print(f"  Domain knowledge checks: {'ALL PASS' if all_correct else 'SOME ISSUES'}")
print(f"  Hill vs Plains: {'CORRECT' if hill_red > plains_red else 'ISSUE'}")
print(f"  Villages near landslides flagged RED: {(close_to_ls['model_risk_zone']=='RED').mean()*100:.1f}%")
print(f"  Safe villages flagged GREEN: {(safe['model_risk_zone']=='GREEN').mean()*100:.1f}%")
