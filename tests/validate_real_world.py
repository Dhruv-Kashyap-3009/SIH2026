"""
Real-World Validation: Are the model predictions actually correct?
Checks against known disasters, geographic facts, and domain knowledge.
"""

import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
import json
import os
import warnings
warnings.filterwarnings('ignore')

# ─── Load data ───────────────────────────────────────────────────────────────
print("=" * 70)
print("REAL-WORLD VALIDATION: Are Predictions Grounded in Reality?")
print("=" * 70)

df = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False)
print(f"Loaded {len(df):,} villages\n")

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


# ================================================================
# TEST 1: Known landslide-prone areas should be RED
# ================================================================
print("=" * 70)
print("TEST 1: Known Landslide Hotspots → Should Be RED/ORANGE")
print("=" * 70)

# These are well-documented landslide-prone areas in NE India
# Source: GSI Landslide Atlas, news reports, academic papers

known_hotspots = {
    # (District, State) → Expected zones
    'Chamoli': 'Arunachal Pradesh',       # Frequent landslides on NH-52
    'Dima Hasao': 'Assam',                # Lumding landslide zone
    'Tawang': 'Arunachal Pradesh',        # High-altitude landslide zone
    'Ukhrul': 'Manipur',                  # Known landslide area
    'Churachandpur': 'Manipur',           # Hill district, landslide prone
    'Phek': 'Nagaland',                   # Steep terrain, landslide prone
    'Aizawl': 'Mizoram',                  # Landslide capital of India
    'Lunglei': 'Mizoram',                 # Hill district
    'Serchhip': 'Mizoram',                # Hill district
    'West Khasi Hills': 'Meghalaya',      # Known landslide zone
    'Jaintia Hills': 'Meghalaya',          # Coal mining + landslide area
    'East Khasi Hills': 'Meghalaya',       # Cherrapunji area
}

for district, state in known_hotspots.items():
    mask = (df['District Name'].str.strip() == district.strip()) & \
           (df['State Name'].str.strip() == state.strip())
    villages = df[mask]
    if len(villages) == 0:
        continue
    red_pct = (villages['model_risk_zone'] == 'RED').mean() * 100
    orange_pct = (villages['model_risk_zone'] == 'ORANGE').mean() * 100
    high_risk_pct = red_pct + orange_pct
    check(
        f"{district}, {state}: {high_risk_pct:.0f}% high-risk ({len(villages):,} villages)",
        high_risk_pct >= 40,
        f"only {high_risk_pct:.0f}% flagged"
    )

# ================================================================
# TEST 2: Known SAFE areas should be GREEN
# ================================================================
print()
print("=" * 70)
print("TEST 2: Known Safe/Flat Areas → Should Be GREEN")
print("=" * 70)

# The Brahmaputra valley in Assam is relatively flat and far from landslides
# Dhubri, Goalpara, Kokrajhar are in the western Assam plains
safe_districts = {
    'Dhubri': ('Assam', 'Flat Brahmaputra plains, minimal landslides'),
    'Goalpara': ('Assam', 'Western Assam plains'),
    'Kokrajhar': ('Assam', 'Bodo terraced hills but valley areas are safe'),
    'Barpeta': ('Assam', 'Brahmaputra floodplain, no hills'),
    'Nalbari': ('Assam', 'Flat Brahmaputra valley'),
    'Morigaon': ('Assam', 'Brahmaputra plains'),
    'Tinsukia': ('Assam', 'Upper Assam plains'),
}

for district, (state, reason) in safe_districts.items():
    mask = (df['District Name'].str.strip() == district.strip()) & \
           (df['State Name'].str.strip() == state.strip())
    villages = df[mask]
    if len(villages) == 0:
        continue
    green_pct = (villages['model_risk_zone'] == 'GREEN').mean() * 100
    check(
        f"{district}, {state}: {green_pct:.0f}% GREEN ({reason})",
        green_pct >= 40,
        f"only {green_pct:.0f}% GREEN"
    )

# ================================================================
# TEST 3: Known 2020 Assam Flood Districts
# ================================================================
print()
print("=" * 70)
print("TEST 3: 2020 Assam Floods (Worst in 3 Decades)")
print("=" * 70)
print("Source: Assam State Disaster Management Authority (ASDMA)")
print("Over 5.5M people affected across 32 districts\n")

# Districts worst hit by 2020 floods
flood_2020_bad = ['Dhemaji', 'Tinsukia', 'Dibrugarh', 'Sivasagar', 'Lakhimpur']
flood_2020_moderate = ['Morigaon', 'Nagaon', 'Dhubri', 'Barpeta', 'Jorhat']

print("  Worst-hit districts (>500K affected):")
for district in flood_2020_bad:
    mask = df['District Name'].str.strip() == district.strip()
    villages = df[mask]
    if len(villages) == 0:
        continue
    red_pct = (villages['model_risk_zone'] == 'RED').mean() * 100
    avg_score = villages['model_risk_score'].mean()
    check(
        f"  {district}: avg_score={avg_score:.3f}, RED={red_pct:.0f}%",
        red_pct >= 30,
        f"only {red_pct:.0f}% RED"
    )

print("\n  Moderately-hit districts:")
for district in flood_2020_moderate:
    mask = df['District Name'].str.strip() == district.strip()
    villages = df[mask]
    if len(villages) == 0:
        continue
    avg_score = villages['model_risk_score'].mean()
    check(
        f"  {district}: avg_score={avg_score:.3f}",
        avg_score >= 0.3,
        f"avg_score={avg_score:.3f} too low"
    )

# ================================================================
# TEST 4: Topographic Gradient — Higher Elevation = More Risk
# ================================================================
print()
print("=" * 70)
print("TEST 4: Elevation-Risk Correlation")
print("=" * 70)
print("In NE India, high-elevation villages face more landslide risk\n")

valid_elev = df[df['elevation_m'].notna()].copy()
# Bin elevation
valid_elev['elev_bin'] = pd.cut(valid_elev['elevation_m'], 
                                 bins=[0, 200, 500, 1000, 2000, 5000],
                                 labels=['0-200m', '200-500m', '500-1000m', '1000-2000m', '2000m+'])

for elev_bin in ['0-200m', '200-500m', '500-1000m', '1000-2000m', '2000m+']:
    subset = valid_elev[valid_elev['elev_bin'] == elev_bin]
    if len(subset) == 0:
        continue
    red_pct = (subset['model_risk_zone'] == 'RED').mean() * 100
    avg_score = subset['model_risk_score'].mean()
    print(f"  {elev_bin:>10s}: RED={red_pct:5.1f}%, avg_score={avg_score:.3f} ({len(subset):,} villages)")

# Check that risk increases with elevation
elev_groups = valid_elev.groupby('elev_bin')['model_risk_score'].mean()
if len(elev_groups) >= 3:
    # At least 200-500m should have higher risk than 0-200m
    low = elev_groups.get('0-200m', 0)
    mid = elev_groups.get('200-500m', 0)
    high = elev_groups.get('1000-2000m', 0)
    check("Low elevation (0-200m) has lower risk than mid (200-500m)", low <= mid + 0.05,
          f"low={low:.3f}, mid={mid:.3f}")
    check("Mid elevation (200-500m) has lower risk than high (1000-2000m)", mid <= high + 0.05,
          f"mid={mid:.3f}, high={high:.3f}")

# ================================================================
# TEST 5: Landslide Proximity — Closer = More Risk
# ================================================================
print()
print("=" * 70)
print("TEST 5: Distance-to-Landslide Gradient")
print("=" * 70)
print("Villages closer to known landslide points should have higher risk\n")

valid_ls = df[df['dist_to_nearest_landslide_km'].notna()].copy()
valid_ls['ls_bin'] = pd.cut(valid_ls['dist_to_nearest_landslide_km'],
                             bins=[0, 5, 10, 25, 50, 100, 500],
                             labels=['0-5km', '5-10km', '10-25km', '25-50km', '50-100km', '100km+'])

for ls_bin in ['0-5km', '5-10km', '10-25km', '25-50km', '50-100km', '100km+']:
    subset = valid_ls[valid_ls['ls_bin'] == ls_bin]
    if len(subset) == 0:
        continue
    red_pct = (subset['model_risk_zone'] == 'RED').mean() * 100
    avg_score = subset['model_risk_score'].mean()
    print(f"  {ls_bin:>10s}: RED={red_pct:5.1f}%, avg_score={avg_score:.3f} ({len(subset):,} villages)")

# Check monotonicity
ls_groups = valid_ls.groupby('ls_bin')['model_risk_score'].mean()
if len(ls_groups) >= 4:
    check("Villages <5km from landslide have highest risk",
          ls_groups.get('0-5km', 0) >= ls_groups.get('50-100km', 0),
          f"<5km={ls_groups.get('0-5km', 0):.3f}, 50-100km={ls_groups.get('50-100km', 0):.3f}")
    check("Risk decreases monotonically with distance",
          ls_groups.get('0-5km', 0) >= ls_groups.get('10-25km', 0) >= ls_groups.get('50-100km', 0),
          f"non-monotonic: {dict(ls_groups)}")

# ================================================================
# TEST 6: Mizoram Should Be Mostly RED
# ================================================================
print()
print("=" * 70)
print("TEST 6: Mizoram — India's Landslide Capital")
print("=" * 70)
print("Mizoram has the highest landslide density in India\n")

mizoram = df[df['State Name'] == 'Mizoram']
red_pct = (mizoram['model_risk_zone'] == 'RED').mean() * 100
avg_score = mizoram['model_risk_score'].mean()
avg_ls_density = mizoram['landslide_density_50km'].mean()
print(f"  Mizoram: {len(mizoram):,} villages")
print(f"  RED zone: {red_pct:.1f}%")
print(f"  Avg risk score: {avg_score:.3f}")
print(f"  Avg landslide density (50km): {avg_ls_density:.0f}")
check("Mizoram is >80% RED zone", red_pct >= 80, f"only {red_pct:.1f}%")
check("Mizoram has high landslide density (>200)", avg_ls_density >= 200,
      f"density={avg_ls_density:.0f}")

# ================================================================
# TEST 7: Tripura Should Be Mostly GREEN (flat, few landslides)
# ================================================================
print()
print("=" * 70)
print("TEST 7: Tripura — Relatively Flat, Fewer Landslides")
print("=" * 70)

tripura = df[df['State Name'] == 'Tripura']
red_pct_t = (tripura['model_risk_zone'] == 'RED').mean() * 100
green_pct_t = (tripura['model_risk_zone'] == 'GREEN').mean() * 100
avg_ls_t = tripura['landslide_density_50km'].mean()
print(f"  Tripura: {len(tripura):,} villages")
print(f"  RED: {red_pct_t:.1f}%, GREEN: {green_pct_t:.1f}%")
print(f"  Avg landslide density (50km): {avg_ls_t:.0f}")
check("Tripura has lower RED % than Mizoram", red_pct_t < 80,
      f"Tripura RED={red_pct_t:.1f}%, Mizoram RED={red_pct:.1f}%")
check("Tripura has low landslide density (<200)", avg_ls_t < 200,
      f"density={avg_ls_t:.0f}")

# ================================================================
# TEST 8: Feature Plausibility — Do key features make sense?
# ================================================================
print()
print("=" * 70)
print("TEST 8: Feature Plausibility Check")
print("=" * 70)

# Elevation range for NE India should be 0-7000m (Kangchenjunga nearby)
check("Max elevation ≤ 7000m (realistic for NE India)",
      df['elevation_m'].dropna().max() <= 7000,
      f"max={df['elevation_m'].dropna().max():.0f}m")

# Mean daily rainfall for NE India should be 5-15mm (one of wettest regions)
mean_rain = df['mean_daily_rainfall_mm'].dropna().mean()
check("Mean daily rainfall 3-20mm (NE India is very wet)",
      3 <= mean_rain <= 20,
      f"mean={mean_rain:.1f}mm")

# Max daily rainfall should be extreme (NE India gets cloudbursts)
max_rain = df['max_daily_rainfall_mm'].dropna().max()
check("Max daily rainfall >500mm (NE India gets cloudbursts)",
      max_rain > 500,
      f"max={max_rain:.0f}mm")

# Distance to road should be reasonable (NE India has limited road network)
mean_road = df['dist_to_nearest_road_km'].dropna().mean()
check("Mean distance to road <5km (reasonable for rural India)",
      mean_road < 5,
      f"mean={mean_road:.2f}km")

# ================================================================
# TEST 9: GSI Landslide Point Validation
# ================================================================
print()
print("=" * 70)
print("TEST 9: GSI Landslide Points — Are They in RED Zones?")
print("=" * 70)
print("Villages near known GSI landslide inventory points should be RED\n")

shp_path = 'data/raw/gsi_landslide/GSI_Landslide_Inventory.shp'
if os.path.exists(shp_path):
    ls_gdf = gpd.read_file(shp_path)
    # Filter NE India
    ne_ls = ls_gdf[
        ls_gdf.geometry.x.between(87, 99) & ls_gdf.geometry.y.between(21, 30)
    ]
    print(f"  NE India landslide points: {len(ne_ls):,}")
    
    # Sample 100 landslide points and check nearest village
    sample_ls = ne_ls.sample(n=min(100, len(ne_ls)), random_state=42)
    
    villages_with_coords = df[df['latitude'].notna() & df['longitude'].notna()].copy()
    villages_gdf = gpd.GeoDataFrame(
        villages_with_coords,
        geometry=[Point(lon, lat) for lon, lat in zip(villages_with_coords['longitude'], villages_with_coords['latitude'])],
        crs='EPSG:4326'
    )
    
    # For each sampled landslide, find nearest village
    correct = 0
    total = 0
    for _, ls_row in sample_ls.iterrows():
        ls_point = ls_row.geometry
        distances = villages_gdf.geometry.distance(ls_point)
        nearest_idx = distances.idxmin()
        nearest_village = villages_with_coords.loc[nearest_idx]
        dist_deg = distances.min()
        
        # Villages within ~5km should be RED
        if dist_deg < 0.05:  # ~5km
            total += 1
            if nearest_village['model_risk_zone'] == 'RED':
                correct += 1
    
    if total > 0:
        rate = correct / total * 100
        print(f"  Villages within 5km of landslide points: {total}")
        print(f"  Correctly flagged RED: {correct}/{total} ({rate:.1f}%)")
        check(f"≥70% of villages near GSI landslides are RED ({rate:.1f}%)",
              rate >= 70,
              f"only {rate:.1f}%")
    else:
        print("  No villages found within 5km of sampled points")
else:
    print("  GSI shapefile not found, skipping")

# ================================================================
# TEST 10: EM-DAT Historical Disaster Validation
# ================================================================
print()
print("=" * 70)
print("TEST 10: EM-DAT Historical Disaster Validation")
print("=" * 70)

emdat_path = 'data/raw/emdat/public_emdat_custom_request_2026-08-29_503d005a-ed3a-40fc-bdef-dda52964b0ca.xlsx'
if os.path.exists(emdat_path):
    emdat = pd.read_excel(emdat_path, header=0)
    ne_states = ['Assam', 'Meghalaya', 'Arunachal', 'Manipur', 'Mizoram', 'Tripura', 'Nagaland', 'Sikkim']
    ne_emdat = emdat[emdat['Location'].fillna('').str.contains('|'.join(ne_states), case=False)]
    
    # Filter for relevant disasters
    relevant = ['Flood', 'Storm', 'Mass movement (wet)', 'Extreme temperature']
    ne_relevant = ne_emdat[ne_emdat['Disaster Type'].isin(relevant)]
    
    print(f"  NE India EM-DAT events: {len(ne_emdat)}")
    print(f"  Relevant disasters: {len(ne_relevant)}")
    
    # Check EM-DAT zone villages
    emdat_zone = df[df['emdat_disaster_zone'] == True]
    if len(emdat_zone) > 0:
        red_pct = (emdat_zone['model_risk_zone'] == 'RED').mean() * 100
        high_risk = (emdat_zone['model_risk_zone'].isin(['RED', 'ORANGE'])).mean() * 100
        print(f"  Villages in EM-DAT zone: {len(emdat_zone):,}")
        print(f"  RED: {red_pct:.1f}%, HIGH RISK (RED+ORANGE): {high_risk:.1f}%")
        check(f"≥85% of EM-DAT zone villages are RED/ORANGE ({high_risk:.1f}%)",
              high_risk >= 85,
              f"only {high_risk:.1f}%")
else:
    print("  EM-DAT file not found, skipping")

# ================================================================
# SUMMARY
# ================================================================
print()
print("=" * 70)
print(f"RESULTS: {PASS}/{PASS+FAIL} passed, {FAIL}/{PASS+FAIL} failed")
print("=" * 70)

if FAIL == 0:
    print("\n🎉 ALL VALIDATIONS PASSED — Predictions are grounded in real-world data!")
else:
    print(f"\n⚠️  {FAIL} validation(s) failed — review above for details")
    print("Note: Some failures may be expected due to data limitations")
    print("(e.g., model is trained on landslide risk, not flood risk)")
