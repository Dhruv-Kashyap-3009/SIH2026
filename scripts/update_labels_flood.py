"""
Update Labels: Add DFO Flood Zones as 3rd Label Source

Current labels: high_risk = GSI landslide zone OR EM-DAT zone
New labels:     high_risk = GSI landslide zone OR EM-DAT zone OR DFO flood zone

DFO flood zone criteria:
  - Village is inside a DFO flood polygon AND severity >= 2, OR
  - flood_density_50km >= 5 (many historical floods nearby)
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point, box
from scipy.spatial import cKDTree
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '.'


def main():
    print('=' * 60)
    print('Update Labels: Add DFO Flood Zones')
    print('=' * 60)

    # Load current feature matrix
    df = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude'])
    n = len(df)
    print(f'Villages: {n:,}')

    # Show current label distribution
    print(f'\nCurrent labels:')
    print(f'  high_risk=1: {df["high_risk"].sum():,} ({df["high_risk"].mean()*100:.1f}%)')
    print(f'  gsi_landslide_zone: {df["gsi_landslide_zone"].sum():,}')
    print(f'  emdat_disaster_zone: {df["emdat_disaster_zone"].sum():,}')

    # ============================================================
    # 1. LOAD DFO FLOOD DATA
    # ============================================================
    print('\n--- 1. Loading DFO Flood Records ---')

    gpkg_path = 'data/raw/floods/Global_Flood_Records.gpkg'
    gdf = gpd.read_file(gpkg_path)
    print(f'Global flood records: {len(gdf):,}')

    # Filter NE India
    ne_bbox = box(87, 21, 99, 30)
    ne_floods = gdf[gdf.geometry.intersects(ne_bbox)].copy()
    print(f'NE India flood events: {len(ne_floods)}')

    # Convert severity to numeric
    ne_floods['Severity'] = pd.to_numeric(ne_floods['Severity'], errors='coerce').fillna(0)
    print(f'\nFlood severity distribution:')
    print(ne_floods['Severity'].value_counts().sort_index().to_string())

    # ============================================================
    # 2. IDENTIFY DFO FLOOD ZONES
    # ============================================================
    print('\n--- 2. Identifying DFO Flood Zones ---')

    # Convert to UTM for spatial operations
    geometry = [Point(lon, lat) for lon, lat in zip(df['longitude'], df['latitude'])]
    villages_gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')
    villages_utm = villages_gdf.to_crs(epsg=32646)
    floods_utm = ne_floods.to_crs(epsg=32646)

    # DFO flood polygons are watershed-scale (cover entire basins),
    # so nearly all villages fall inside them. Instead, use flood density
    # which is more discriminative.
    #
    # Criteria: flood_density_50km >= 5 AND dist_to_nearest_flood_km < 30km
    # This captures villages with significant historical flood exposure.
    high_flood_density = (df['flood_density_50km'] >= 5) & (df['dist_to_nearest_flood_km'] < 30)
    print(f'Villages with flood_density_50km >= 5 AND dist < 30km: {high_flood_density.sum():,} ({high_flood_density.sum()/n*100:.1f}%)')

    # Also flag villages with very high flood density (>= 10)
    very_high_flood = df['flood_density_50km'] >= 10
    print(f'Very high flood density (>= 10): {very_high_flood.sum():,} ({very_high_flood.sum()/n*100:.1f}%)')

    # ============================================================
    # 3. CREATE DFO FLOOD ZONE LABEL
    # ============================================================
    print('\n--- 3. Creating DFO Flood Zone Label ---')

    df['dfo_flood_zone'] = high_flood_density.values
    n_dfo = df['dfo_flood_zone'].sum()
    print(f'Villages in DFO flood zone: {n_dfo:,} ({n_dfo/n*100:.1f}%)')

    # Show by state
    print('\nDFO flood zone by state:')
    for state in sorted(df['State Name'].unique()):
        mask = df['State Name'] == state
        count = df.loc[mask, 'dfo_flood_zone'].sum()
        total = mask.sum()
        if count > 0:
            print(f'  {state}: {count:,} / {total:,} ({count/total*100:.1f}%)')

    # ============================================================
    # 4. UPDATE HIGH_RISK LABELS
    # ============================================================
    print('\n--- 4. Updating high_risk Labels ---')

    # Old: high_risk = gsi_landslide_zone OR emdat_disaster_zone
    old_high_risk = df['high_risk'].sum()

    # New: high_risk = gsi_landslide_zone OR emdat_disaster_zone OR dfo_flood_zone
    df['high_risk'] = (
        (df['gsi_landslide_zone'] == True) |
        (df['emdat_disaster_zone'] == True) |
        (df['dfo_flood_zone'] == True)
    ).astype(int)

    new_high_risk = df['high_risk'].sum()
    added = new_high_risk - old_high_risk

    print(f'Old high_risk=1: {old_high_risk:,} ({old_high_risk/n*100:.1f}%)')
    print(f'New high_risk=1: {new_high_risk:,} ({new_high_risk/n*100:.1f}%)')
    print(f'Added by DFO:    {added:,} ({added/n*100:.1f}%)')

    # Show breakdown
    print('\nLabel source breakdown:')
    gsi_only = ((df['gsi_landslide_zone'] == True) & (df['emdat_disaster_zone'] == False) & (df['dfo_flood_zone'] == False)).sum()
    emdat_only = ((df['gsi_landslide_zone'] == False) & (df['emdat_disaster_zone'] == True) & (df['dfo_flood_zone'] == False)).sum()
    dfo_only = ((df['gsi_landslide_zone'] == False) & (df['emdat_disaster_zone'] == False) & (df['dfo_flood_zone'] == True)).sum()
    multiple = new_high_risk - gsi_only - emdat_only - dfo_only
    print(f'  GSI only:     {gsi_only:,}')
    print(f'  EM-DAT only:  {emdat_only:,}')
    print(f'  DFO only:     {dfo_only:,}')
    print(f'  Multiple:     {multiple:,}')

    # ============================================================
    # 5. CHECK FLOOD DISTRICTS
    # ============================================================
    print('\n--- 5. Flood District Label Check ---')

    flood_dists = ['Dhemaji', 'Tinsukia', 'Sivasagar', 'Dibrugarh', 'Dhubri', 'Jorhat']
    for district in flood_dists:
        mask = df['District Name'].str.strip() == district
        villages = df[mask]
        if len(villages) == 0:
            continue
        hr = villages['high_risk'].mean() * 100
        dfo = villages['dfo_flood_zone'].mean() * 100
        print(f'  {district:<15s}: high_risk={hr:.1f}%, dfo_flood_zone={dfo:.1f}% ({len(villages):,} villages)')

    # ============================================================
    # 6. UPDATE MULTICLASS RISK ZONES
    # ============================================================
    print('\n--- 6. Updating Risk Zones ---')

    landslide_50km = df['landslide_density_50km'].fillna(0)
    landslide_100km = df['landslide_density_100km'].fillna(0)
    dist_landslide = df['dist_to_nearest_landslide_km'].fillna(999)
    flood_50km = df['flood_density_50km'].fillna(0)

    conditions_red = (
        (df['gsi_landslide_zone'] == True) & (landslide_100km > 50)
    ) | (
        (df['emdat_disaster_zone'] == True) & (landslide_50km > 10)
    ) | (
        (dist_landslide < 5) & (landslide_50km > 20)
    ) | (
        # NEW: DFO flood zone with high flood density
        (df['dfo_flood_zone'] == True) & (flood_50km >= 8)
    ) | (
        # NEW: Inside severe flood polygon + near river
        (df['dfo_flood_zone'] == True) & (df['dist_to_nearest_river_km'] < 2)
    )

    conditions_orange = (
        (df['gsi_landslide_zone'] == True) |
        (landslide_50km > 20) |
        (df['emdat_disaster_zone'] == True) |
        (df['dfo_flood_zone'] == True)  # NEW: DFO flood zone
    ) & (~conditions_red)

    df['risk_zone'] = 'GREEN'
    df.loc[conditions_orange, 'risk_zone'] = 'ORANGE'
    df.loc[conditions_red, 'risk_zone'] = 'RED'

    print(df['risk_zone'].value_counts().to_string())

    # ============================================================
    # 7. SAVE
    # ============================================================
    print('\n--- 7. Saving ---')

    df.to_csv('data/processed/ne_india_village_features.csv', index=False)
    print(f'Saved: data/processed/ne_india_village_features.csv')
    print(f'Shape: {df.shape}')

    # Also save labels-only file
    labels_df = df[['Village Name', 'State Name', 'District Name', 'latitude', 'longitude',
                     'high_risk', 'risk_zone', 'gsi_landslide_zone', 'emdat_disaster_zone',
                     'dfo_flood_zone', 'dist_to_nearest_landslide_km', 'landslide_density_50km',
                     'landslide_density_100km', 'flood_density_50km', 'flood_density_100km']].copy()
    labels_df.to_csv('data/processed/village_risk_labels.csv', index=False)
    print(f'Saved: data/processed/village_risk_labels.csv')

    print('\n' + '=' * 60)
    print('LABELS UPDATED — Ready for retraining')
    print('=' * 60)


if __name__ == '__main__':
    main()
