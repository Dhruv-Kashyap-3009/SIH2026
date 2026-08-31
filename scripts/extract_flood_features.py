"""
Flood Feature Extraction
Adds flood-risk features to the village feature matrix using:
1. DFO Global Flood Records (historical flood event polygons)
2. Derived flood-proxy features (low elevation + flat + near river = flood-prone)
"""

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, box
from scipy.spatial import cKDTree
import os
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_villages():
    """Load village data with coordinates."""
    csv_path = os.path.join(BASE_DIR, 'data', 'processed', 'ne_india_village_features.csv')
    df = pd.read_csv(csv_path, low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude'])
    print(f"Loaded {len(df):,} villages")
    return df


def extract_dfo_flood_features(df):
    """
    Extract features from DFO Global Flood Records.
    - dist_to_nearest_flood_km: distance to nearest historical flood polygon
    - flood_density_50km: number of flood events within 50km
    - flood_density_100km: number of flood events within 100km
    - in_historical_flood_zone: whether village is inside a DFO flood polygon
    """
    print("\n--- DFO Flood Record Features ---")

    gpkg_path = os.path.join(BASE_DIR, 'data', 'raw', 'floods', 'Global_Flood_Records.gpkg')
    if not os.path.exists(gpkg_path):
        print("  WARNING: DFO GeoPackage not found, skipping flood features")
        for col in ['dist_to_nearest_flood_km', 'flood_density_50km', 'flood_density_100km', 'in_historical_flood_zone']:
            df[col] = np.nan
        return df

    gdf = gpd.read_file(gpkg_path)
    print(f"  Loaded {len(gdf):,} global flood records")

    # Filter NE India
    ne_bbox = box(87, 21, 99, 30)
    ne_floods = gdf[gdf.geometry.intersects(ne_bbox)].copy()
    print(f"  NE India flood events: {len(ne_floods)}")

    if len(ne_floods) == 0:
        for col in ['dist_to_nearest_flood_km', 'flood_density_50km', 'flood_density_100km', 'in_historical_flood_zone']:
            df[col] = np.nan
        return df

    # Convert villages to GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in zip(df['longitude'], df['latitude'])]
    villages_gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')

    # Project to UTM 46N for accurate distance computation
    villages_utm = villages_gdf.to_crs(epsg=32646)
    floods_utm = ne_floods.to_crs(epsg=32646)

    # 1. Check which villages are inside any DFO flood polygon
    print("  Computing village-in-flood-zone intersections...")
    flood_union = gpd.GeoSeries(floods_utm.geometry).unary_union
    in_flood_zone = villages_utm.geometry.within(flood_union)
    n_in_zone = in_flood_zone.sum()
    print(f"  Villages inside DFO flood polygons: {n_in_zone:,} / {len(df):,} ({n_in_zone/len(df)*100:.1f}%)")

    # 2. Distance to nearest flood polygon centroid
    print("  Computing distance to nearest flood event...")
    flood_centroids = floods_utm.geometry.centroid
    flood_coords = np.array(list(zip(flood_centroids.x, flood_centroids.y)))
    village_coords = np.array(list(zip(villages_utm.geometry.x, villages_utm.geometry.y)))

    tree = cKDTree(flood_coords)
    distances, _ = tree.query(village_coords, k=1)
    dist_km = distances / 1000  # UTM is in meters

    # 3. Flood density (events within radius)
    print("  Computing flood density...")
    density_50km = tree.query_ball_point(village_coords, r=50000)
    density_100km = tree.query_ball_point(village_coords, r=100000)

    df = df.copy()
    df['dist_to_nearest_flood_km'] = dist_km
    df['flood_density_50km'] = [len(pts) for pts in density_50km]
    df['flood_density_100km'] = [len(pts) for pts in density_100km]
    df['in_historical_flood_zone'] = in_flood_zone.values

    # Summary
    print(f"  dist_to_nearest_flood_km: mean={dist_km.mean():.1f}km, min={dist_km.min():.1f}km")
    print(f"  flood_density_50km: mean={df['flood_density_50km'].mean():.1f}")
    print(f"  flood_density_100km: mean={df['flood_density_100km'].mean():.1f}")

    return df


def derive_flood_proxy_features(df):
    """
    Derive flood-proxy features from existing data.
    Flood risk = low elevation + flat terrain + near major river + high rainfall

    Features:
    - is_lowland: elevation < 100m (Brahmaputra floodplain)
    - is_flat: slope < 5 degrees (water accumulates)
    - dist_to_major_river_km: distance to major rivers (already have dist_to_nearest_river_km)
    - flood_proxy_score: combined score (0-1) of flood susceptibility
    """
    print("\n--- Derived Flood Proxy Features ---")

    df = df.copy()

    # 1. Lowland flag (< 100m = Brahmaputra/Barak floodplain)
    if 'elevation_m' in df.columns:
        df['is_lowland'] = (df['elevation_m'] < 100).astype(int)
        n_lowland = df['is_lowland'].sum()
        print(f"  Lowland villages (<100m): {n_lowland:,} ({n_lowland/len(df)*100:.1f}%)")

    # 2. Flat terrain flag (slope < 5°)
    if 'slope_degrees' in df.columns:
        df['is_flat'] = (df['slope_degrees'] < 5).astype(int)
        n_flat = df['is_flat'].sum()
        print(f"  Flat villages (slope<5°): {n_flat:,} ({n_flat/len(df)*100:.1f}%)")

    # 3. Near major river (< 2km)
    if 'dist_to_nearest_river_km' in df.columns:
        df['near_major_river'] = (df['dist_to_nearest_river_km'] < 2).astype(int)
        n_near = df['near_major_river'].sum()
        print(f"  Near river (<2km): {n_near:,} ({n_near/len(df)*100:.1f}%)")

    # 4. High rainfall zone (mean > 8mm/day)
    if 'mean_daily_rainfall_mm' in df.columns:
        df['high_rainfall_zone'] = (df['mean_daily_rainfall_mm'] > 8).astype(int)
        n_rain = df['high_rainfall_zone'].sum()
        print(f"  High rainfall zone (>8mm/day): {n_rain:,} ({n_rain/len(df)*100:.1f}%)")

    # 5. Combined flood proxy score (0-1)
    # Weighted combination of flood-prone factors
    components = []
    weights = []

    if 'elevation_m' in df.columns:
        # Lower elevation = higher flood risk (invert and normalize)
        elev = df['elevation_m'].fillna(df['elevation_m'].median())
        elev_score = 1 - (elev / elev.max()).clip(0, 1)
        components.append(elev_score)
        weights.append(0.25)

    if 'slope_degrees' in df.columns:
        # Flatter = higher flood risk
        slope = df['slope_degrees'].fillna(df['slope_degrees'].median())
        slope_score = 1 - (slope / 90).clip(0, 1)
        components.append(slope_score)
        weights.append(0.20)

    if 'dist_to_nearest_river_km' in df.columns:
        # Closer to river = higher flood risk
        river = df['dist_to_nearest_river_km'].fillna(df['dist_to_nearest_river_km'].median())
        river_score = 1 - (river / river.max()).clip(0, 1)
        components.append(river_score)
        weights.append(0.25)

    if 'mean_daily_rainfall_mm' in df.columns:
        # Higher rainfall = higher flood risk
        rain = df['mean_daily_rainfall_mm'].fillna(df['mean_daily_rainfall_mm'].median())
        rain_score = (rain / rain.max()).clip(0, 1)
        components.append(rain_score)
        weights.append(0.15)

    if 'max_daily_rainfall_mm' in df.columns:
        # Extreme rainfall events
        max_rain = df['max_daily_rainfall_mm'].fillna(df['max_daily_rainfall_mm'].median())
        max_rain_score = (max_rain / max_rain.max()).clip(0, 1)
        components.append(max_rain_score)
        weights.append(0.15)

    if components:
        total_weight = sum(weights)
        flood_proxy = sum(c * w for c, w in zip(components, weights)) / total_weight
        df['flood_proxy_score'] = flood_proxy.clip(0, 1)
        print(f"  flood_proxy_score: mean={flood_proxy.mean():.3f}, range=[{flood_proxy.min():.3f}, {flood_proxy.max():.3f}]")

    return df


def main():
    print("=" * 60)
    print("Flood Feature Extraction")
    print("=" * 60)

    # Load villages
    df = load_villages()

    # Extract DFO flood features
    df = extract_dfo_flood_features(df)

    # Derive flood proxy features
    df = derive_flood_proxy_features(df)

    # Save
    output_path = os.path.join(BASE_DIR, 'data', 'processed', 'ne_india_village_features.csv')
    df.to_csv(output_path, index=False)
    print(f"\nSaved: {output_path}")
    print(f"Shape: {df.shape}")

    # Summary
    print("\n--- Flood Feature Summary ---")
    flood_cols = ['dist_to_nearest_flood_km', 'flood_density_50km', 'flood_density_100km',
                  'in_historical_flood_zone', 'is_lowland', 'is_flat', 'near_major_river',
                  'high_rainfall_zone', 'flood_proxy_score']
    for col in flood_cols:
        if col in df.columns:
            valid = df[col].notna().sum()
            print(f"  {col}: {valid:,} / {len(df):,} valid ({valid/len(df)*100:.1f}%)")


if __name__ == '__main__':
    main()
