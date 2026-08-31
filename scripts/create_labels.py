"""
Phase 2: Label Creation
Creates binary high_risk labels for the prediction model using:
1. GSI Landslide Inventory - villages within 10km of a landslide point
2. EM-DAT Disaster History - villages within 15km of a historical disaster
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
from shapely.ops import unary_union
from scipy.spatial import cKDTree
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '.'

def main():
    print('=' * 60)
    print('Phase 2: Label Creation')
    print('=' * 60)

    # Load feature matrix
    df = pd.read_csv('data/processed/ne_india_village_features.csv', low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude'])
    n = len(df)
    print(f'Villages: {n:,}')

    # Convert to GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in zip(df['longitude'], df['latitude'])]
    villages_gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')

    # ============================================================
    # 1. GSI LANDSLIDE LABELS (10km buffer)
    # ============================================================
    print()
    print('--- 1. GSI Landslide Labels (10km buffer) ---')

    shp_path = 'data/raw/gsi_landslide/GSI_Landslide_Inventory.shp'
    landslide_gdf = gpd.read_file(shp_path)
    print(f'Loaded {len(landslide_gdf):,} landslide points')

    # Filter for NE India landslides
    ne_landslides = landslide_gdf[
        landslide_gdf.geometry.x.between(87, 99) &
        landslide_gdf.geometry.y.between(21, 30)
    ]
    print(f'NE India landslides: {len(ne_landslides):,}')

    # Project to UTM 46N for accurate distance calculations
    print('Projecting to UTM 46N...')
    villages_utm = villages_gdf.to_crs(epsg=32646)
    ne_landslides_utm = ne_landslides.to_crs(epsg=32646)

    # Buffer each landslide point by 10km
    print('Creating 10km buffers around landslides...')
    landslide_buffers = ne_landslides_utm.geometry.buffer(10000)
    landslide_union = unary_union(landslide_buffers)

    # Check which villages fall within any buffer
    print('Computing village-landslide intersection...')
    in_landslide_zone = villages_utm.geometry.within(landslide_union)
    print(f'Villages in landslide zone: {in_landslide_zone.sum():,} / {n:,} ({in_landslide_zone.sum()/n*100:.1f}%)')

    # Distance to nearest landslide (UTM for accuracy)
    landslide_coords = np.array(list(zip(
        ne_landslides_utm.geometry.x,
        ne_landslides_utm.geometry.y
    )))
    village_coords = np.array(list(zip(
        villages_utm.geometry.x,
        villages_utm.geometry.y
    )))

    tree = cKDTree(landslide_coords)
    dists, _ = tree.query(village_coords, k=1)
    dists_km = dists / 1000

    # By state
    print()
    for state in df['State Name'].unique():
        mask = df['State Name'] == state
        count = in_landslide_zone[mask].sum()
        total = mask.sum()
        if count > 0:
            print(f'  {state}: {count:,} / {total:,} in landslide zone ({count/total*100:.1f}%)')

    # ============================================================
    # 2. EM-DAT LABELS (15km buffer)
    # ============================================================
    print()
    print('--- 2. EM-DAT Disaster Labels (15km buffer) ---')

    emdat = pd.read_excel('data/raw/emdat/public_emdat_custom_request_2026-08-29_503d005a-ed3a-40fc-bdef-dda52964b0ca.xlsx', header=0)
    ne_states = ['Assam', 'Meghalaya', 'Arunachal', 'Manipur', 'Mizoram', 'Tripura', 'Nagaland', 'Sikkim']
    ne_mask = emdat['Location'].fillna('').str.contains('|'.join(ne_states), case=False)
    ne_emdat = emdat[ne_mask].copy()
    print(f'NE India EM-DAT records: {len(ne_emdat)}')

    # Filter for relevant disaster types
    relevant_types = ['Flood', 'Storm', 'Mass movement (wet)', 'Extreme temperature']
    ne_emdat = ne_emdat[ne_emdat['Disaster Type'].isin(relevant_types)]
    print(f'After filtering relevant types: {len(ne_emdat)}')

    # District centroids for geocoding
    district_centroids = df.groupby(['State Name', 'District Name']).agg({
        'latitude': 'mean',
        'longitude': 'mean'
    }).reset_index()

    # Geocode all EM-DAT events
    emdat_events = []
    for _, row in ne_emdat.iterrows():
        loc = str(row['Location'])

        # If has direct coordinates
        if pd.notna(row.get('Latitude')) and pd.notna(row.get('Longitude')):
            emdat_events.append({
                'DisNo': row['DisNo.'],
                'Disaster Type': row['Disaster Type'],
                'latitude': row['Latitude'],
                'longitude': row['Longitude'],
                'Location': loc,
                'source': 'direct'
            })
            continue

        # Try district match
        matched = False
        for state in ne_states:
            if state.lower() in loc.lower():
                state_districts = district_centroids[
                    district_centroids['State Name'].str.contains(state, case=False, na=False)
                ]
                for _, dist_row in state_districts.iterrows():
                    if dist_row['District Name'].lower() in loc.lower():
                        emdat_events.append({
                            'DisNo': row['DisNo.'],
                            'Disaster Type': row['Disaster Type'],
                            'latitude': dist_row['latitude'],
                            'longitude': dist_row['longitude'],
                            'Location': loc,
                            'source': 'district_match'
                        })
                        matched = True
                        break
                if matched:
                    break

        # Fallback: state centroid
        if not matched:
            for state in ne_states:
                if state.lower() in loc.lower():
                    state_data = df[df['State Name'].str.contains(state, case=False, na=False)]
                    if len(state_data) > 0:
                        emdat_events.append({
                            'DisNo': row['DisNo.'],
                            'Disaster Type': row['Disaster Type'],
                            'latitude': state_data['latitude'].mean(),
                            'longitude': state_data['longitude'].mean(),
                            'Location': loc,
                            'source': 'state_centroid'
                        })
                    break

    emdat_df = pd.DataFrame(emdat_events)
    print(f'Geocoded EM-DAT events: {len(emdat_df)}')
    if len(emdat_df) > 0:
        print(f'  Sources: {emdat_df["source"].value_counts().to_dict()}')

    # Create EM-DAT disaster zone
    in_emdat_zone = pd.Series([False] * n)
    if len(emdat_df) > 0:
        emdat_geometry = [Point(lon, lat) for lon, lat in zip(emdat_df['longitude'], emdat_df['latitude'])]
        emdat_gdf = gpd.GeoDataFrame(emdat_df, geometry=emdat_geometry, crs='EPSG:4326')
        emdat_utm = emdat_gdf.to_crs(epsg=32646)

        emdat_buffers = emdat_utm.geometry.buffer(15000)  # 15km
        emdat_union = unary_union(emdat_buffers)

        in_emdat_zone = villages_utm.geometry.within(emdat_union)
        print(f'Villages in EM-DAT zone: {in_emdat_zone.sum():,} / {n:,} ({in_emdat_zone.sum()/n*100:.1f}%)')

    # ============================================================
    # 3. COMBINED LABELS
    # ============================================================
    print()
    print('--- 3. Combined Risk Labels ---')

    df['gsi_landslide_zone'] = in_landslide_zone.values
    df['emdat_disaster_zone'] = in_emdat_zone.values

    # Combined label: high_risk = 1 if in landslide zone OR EM-DAT zone
    df['high_risk'] = ((df['gsi_landslide_zone'] == True) | (df['emdat_disaster_zone'] == True)).astype(int)

    n_positive = df['high_risk'].sum()
    print(f'High-risk villages: {n_positive:,} / {n:,} ({n_positive/n*100:.1f}%)')
    print(f'Low-risk villages: {(n - n_positive):,} / {n:,} ({(1 - n_positive/n)*100:.1f}%)')

    # Breakdown
    print()
    print('Label source breakdown:')
    gsi_only = ((df['gsi_landslide_zone'] == True) & (df['emdat_disaster_zone'] == False)).sum()
    emdat_only = ((df['gsi_landslide_zone'] == False) & (df['emdat_disaster_zone'] == True)).sum()
    both = ((df['gsi_landslide_zone'] == True) & (df['emdat_disaster_zone'] == True)).sum()
    print(f'  GSI landslide zone only: {gsi_only:,}')
    print(f'  EM-DAT zone only: {emdat_only:,}')
    print(f'  Both zones: {both:,}')

    # By state
    print()
    print('High-risk by state:')
    for state in sorted(df['State Name'].unique()):
        state_df = df[df['State Name'] == state]
        hr = state_df['high_risk'].sum()
        print(f'  {state}: {hr:,} / {len(state_df):,} ({hr/len(state_df)*100:.1f}%)')

    # ============================================================
    # 4. MULTICLASS LABELS (for richer analysis)
    # ============================================================
    print()
    print('--- 4. Multiclass Risk Zones ---')

    # Risk zones based on combined scoring
    # RED: in landslide zone AND >50 landslides within 100km, OR EM-DAT + high landslide density
    # ORANGE: in landslide zone OR high landslide density (>20 within 50km)
    # GREEN: everything else

    landslide_50km = df['landslide_density_50km'].fillna(0)
    landslide_100km = df['landslide_density_100km'].fillna(0)
    dist_landslide = df['dist_to_nearest_landslide_km'].fillna(999)

    conditions_red = (
        (df['gsi_landslide_zone'] == True) & (landslide_100km > 50)
    ) | (
        (df['emdat_disaster_zone'] == True) & (landslide_50km > 10)
    ) | (
        (dist_landslide < 5) & (landslide_50km > 20)
    )

    conditions_orange = (
        (df['gsi_landslide_zone'] == True) |
        (landslide_50km > 20) |
        (df['emdat_disaster_zone'] == True)
    ) & (~conditions_red)

    df['risk_zone'] = 'GREEN'
    df.loc[conditions_orange, 'risk_zone'] = 'ORANGE'
    df.loc[conditions_red, 'risk_zone'] = 'RED'

    print(df['risk_zone'].value_counts().to_string())
    print()

    for zone in ['RED', 'ORANGE', 'GREEN']:
        mask = df['risk_zone'] == zone
        print(f'{zone} zone by state:')
        state_counts = df[mask]['State Name'].value_counts()
        for state, count in state_counts.head(8).items():
            total_state = (df['State Name'] == state).sum()
            print(f'  {state}: {count:,} / {total_state:,}')
        print()

    # Save
    df.to_csv('data/processed/ne_india_village_features.csv', index=False)
    print(f'Saved: data/processed/ne_india_village_features.csv')

    # Also save a clean labels-only file for quick reference
    labels_df = df[['Village Name', 'State Name', 'District Name', 'latitude', 'longitude',
                     'high_risk', 'risk_zone', 'gsi_landslide_zone', 'emdat_disaster_zone',
                     'dist_to_nearest_landslide_km', 'landslide_density_50km',
                     'landslide_density_100km']].copy()
    labels_df.to_csv('data/processed/village_risk_labels.csv', index=False)
    print(f'Saved: data/processed/village_risk_labels.csv')


if __name__ == '__main__':
    main()
