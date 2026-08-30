"""
Phase 1b: Vector Feature Extraction
Extracts distances to roads, rivers, hospitals, schools, and landslide proximity
for all NE India villages from OSM PBF and GSI Landslide shapefile.
"""

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import nearest_points
from scipy.spatial import cKDTree
import os
import warnings
warnings.filterwarnings('ignore')

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSM_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'openstreetmap')
GSI_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'gsi_landslide')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')


def load_osm_features():
    """
    Extract OSM features from PBF file using osmium.
    Extracts: highways, waterways, amenities (hospitals, schools)
    """
    print("\n--- Loading OSM Features ---")
    
    pbf_file = os.path.join(OSM_DIR, 'north-eastern-zone.osm.pbf')
    if not os.path.exists(pbf_file):
        print(f"  ERROR: {pbf_file} not found!")
        return None
    
    try:
        import osmium
        import json
        
        # Custom handler to extract features
        class OSMHandler(osmium.SimpleHandler):
            def __init__(self):
                super().__init__()
                self.highways = []
                self.waterways = []
                self.hospitals = []
                self.schools = []
            
            def node(self, n):
                tags = dict(n.tags)
                loc = (n.location.lon, n.location.lat)
                
                if 'amenity' in tags:
                    if tags['amenity'] in ['hospital', 'clinic', 'health_center']:
                        self.hospitals.append({'lon': loc[0], 'lat': loc[1], 'name': tags.get('name', '')})
                    elif tags['amenity'] in ['school', 'college', 'university']:
                        self.schools.append({'lon': loc[0], 'lat': loc[1], 'name': tags.get('name', '')})
            
            def way(self, w):
                tags = dict(w.tags)
                
                if 'highway' in tags:
                    # Get way coordinates
                    coords = []
                    for n in w.nodes:
                        if n.location.valid():
                            coords.append((n.location.lon, n.location.lat))
                    if len(coords) >= 2:
                        self.highways.append({
                            'type': tags['highway'],
                            'coords': coords,
                            'name': tags.get('name', '')
                        })
                
                if 'waterway' in tags:
                    coords = []
                    for n in w.nodes:
                        if n.location.valid():
                            coords.append((n.location.lon, n.location.lat))
                    if len(coords) >= 2:
                        self.waterways.append({
                            'type': tags['waterway'],
                            'coords': coords,
                            'name': tags.get('name', '')
                        })
        
        print("  Parsing OSM PBF file (this may take a few minutes)...")
        handler = OSMHandler()
        handler.apply_file(pbf_file)
        
        print(f"  Found: {len(handler.highways)} highways, {len(handler.waterways)} waterways")
        print(f"         {len(handler.hospitals)} hospitals, {len(handler.schools)} schools")
        
        return {
            'highways': handler.highways,
            'waterways': handler.waterways,
            'hospitals': handler.hospitals,
            'schools': handler.schools
        }
        
    except ImportError:
        print("  osmium not available, trying alternative extraction...")
        # Fallback: try to use subprocess to run osmium tool
        import subprocess
        
        # Extract highways as GeoJSON
        print("  Using osmium extract command...")
        
        features = {
            'highways': [],
            'waterways': [],
            'hospitals': [],
            'schools': []
        }
        
        # Try osmium tags-filter
        try:
            # Extract highways
            result = subprocess.run(
                ['osmium', 'tags-filter', pbf_file, 'w/highway'],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                print("  Highway extraction successful")
        except:
            print("  osmium command not available")
        
        return features


def compute_distance_to_features(villages_gdf, features_gdf, feature_type="feature"):
    """
    Compute minimum distance from each village to the nearest feature.
    Uses cKDTree for efficient nearest-neighbor computation.
    """
    if len(features_gdf) == 0:
        print(f"  WARNING: No {feature_type} found!")
        return np.full(len(villages_gdf), np.nan)
    
    # Create coordinate arrays
    village_coords = np.array(list(zip(villages_gdf.geometry.x, villages_gdf.geometry.y)))
    
    # For line features (roads, rivers), sample points along lines
    if features_gdf.geometry.type.isin(['LineString', 'MultiLineString']).any():
        # Sample points along lines at ~100m intervals
        feature_points = []
        for geom in features_gdf.geometry:
            if geom is None:
                continue
            if geom.geom_type == 'MultiLineString':
                for line in geom.geoms:
                    # Sample at ~100m intervals
                    length = line.length
                    n_points = max(int(length / 0.001), 2)  # ~100m in degrees
                    for t in np.linspace(0, 1, n_points):
                        pt = line.interpolate(t, normalized=True)
                        feature_points.append((pt.x, pt.y))
            elif geom.geom_type == 'LineString':
                length = geom.length
                n_points = max(int(length / 0.001), 2)
                for t in np.linspace(0, 1, n_points):
                    pt = geom.interpolate(t, normalized=True)
                    feature_points.append((pt.x, pt.y))
        
        if not feature_points:
            return np.full(len(villages_gdf), np.nan)
        
        feature_coords = np.array(feature_points)
    else:
        # Point features (hospitals, schools)
        feature_coords = np.array(list(zip(features_gdf.geometry.x, features_gdf.geometry.y)))
    
    # Build KDTree and query
    tree = cKDTree(feature_coords)
    distances, _ = tree.query(village_coords, k=1)
    
    # Convert degrees to approximate kilometers (1 degree ~ 111 km at equator)
    # For NE India (~25N), 1 degree latitude ~ 111 km, 1 degree longitude ~ 100 km
    distances_km = distances * 111  # Rough approximation
    
    return distances_km


def extract_vector_features(villages_df):
    """Extract all vector features for villages."""
    print("\n--- Vector Feature Extraction ---")
    
    # Convert villages to GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in zip(villages_df['longitude'], villages_df['latitude'])]
    villages_gdf = gpd.GeoDataFrame(villages_df, geometry=geometry, crs='EPSG:4326')
    
    n = len(villages_gdf)
    
    # Initialize output columns
    villages_df = villages_df.copy()
    villages_df['dist_to_nearest_road_km'] = np.nan
    villages_df['dist_to_nearest_river_km'] = np.nan
    villages_df['dist_to_nearest_hospital_km'] = np.nan
    villages_df['dist_to_nearest_school_km'] = np.nan
    villages_df['road_density_5km'] = np.nan  # Number of road segments within 5km
    
    # 1. Load OSM features
    print("\n  Loading OSM features...")
    osm_features = load_osm_features()
    
    if osm_features and osm_features.get('highways'):
        print("  Computing distance to roads...")
        highways_data = osm_features['highways']
        
        # Create GeoDataFrame for highways
        from shapely.geometry import LineString
        highway_lines = []
        for hw in highways_data:
            if len(hw['coords']) >= 2:
                line = LineString(hw['coords'])
                highway_lines.append({'geometry': line, 'type': hw['type']})
        
        if highway_lines:
            highways_gdf = gpd.GeoDataFrame(highway_lines, crs='EPSG:4326')
            villages_df['dist_to_nearest_road_km'] = compute_distance_to_features(
                villages_gdf, highways_gdf, "roads"
            )
            
            # Compute road density (roads within 5km radius)
            print("  Computing road density...")
            road_coords = []
            for hw in highways_data:
                road_coords.extend(hw['coords'])
            
            if road_coords:
                road_tree = cKDTree(np.array(road_coords))
                village_coords = np.array(list(zip(villages_gdf.geometry.x, villages_gdf.geometry.y)))
                # Count road points within ~5km (0.045 degrees)
                road_density = road_tree.query_ball_point(village_coords, r=0.045)
                villages_df['road_density_5km'] = [len(pts) for pts in road_density]
    
    if osm_features and osm_features.get('waterways'):
        print("  Computing distance to rivers...")
        waterway_data = osm_features['waterways']
        
        from shapely.geometry import LineString
        waterway_lines = []
        for ww in waterway_data:
            if len(ww['coords']) >= 2:
                line = LineString(ww['coords'])
                waterway_lines.append({'geometry': line, 'type': ww['type']})
        
        if waterway_lines:
            waterways_gdf = gpd.GeoDataFrame(waterway_lines, crs='EPSG:4326')
            villages_df['dist_to_nearest_river_km'] = compute_distance_to_features(
                villages_gdf, waterways_gdf, "waterways"
            )
    
    if osm_features and osm_features.get('hospitals'):
        print("  Computing distance to hospitals...")
        hospital_data = osm_features['hospitals']
        
        if hospital_data:
            from shapely.geometry import Point as ShapelyPoint
            hospital_points = [{'geometry': ShapelyPoint(h['lon'], h['lat'])} for h in hospital_data]
            hospitals_gdf = gpd.GeoDataFrame(hospital_points, crs='EPSG:4326')
            villages_df['dist_to_nearest_hospital_km'] = compute_distance_to_features(
                villages_gdf, hospitals_gdf, "hospitals"
            )
    
    if osm_features and osm_features.get('schools'):
        print("  Computing distance to schools...")
        school_data = osm_features['schools']
        
        if school_data:
            from shapely.geometry import Point as ShapelyPoint
            school_points = [{'geometry': ShapelyPoint(s['lon'], s['lat'])} for s in school_data]
            schools_gdf = gpd.GeoDataFrame(school_points, crs='EPSG:4326')
            villages_df['dist_to_nearest_school_km'] = compute_distance_to_features(
                villages_gdf, schools_gdf, "schools"
            )
    
    return villages_df


def extract_landslide_features(villages_df):
    """Extract landslide proximity features from GSI Landslide Inventory."""
    print("\n--- Landslide Feature Extraction ---")
    
    shp_file = os.path.join(GSI_DIR, 'GSI_Landslide_Inventory.shp')
    if not os.path.exists(shp_file):
        print(f"  ERROR: {shp_file} not found!")
        villages_df = villages_df.copy()
        villages_df['dist_to_nearest_landslide_km'] = np.nan
        villages_df['landslide_density_50km'] = np.nan
        villages_df['landslide_density_100km'] = np.nan
        return villages_df
    
    # Load landslide points
    print("  Loading GSI Landslide Inventory...")
    landslide_gdf = gpd.read_file(shp_file)
    print(f"  Loaded {len(landslide_gdf):,} landslide points")
    
    # Convert villages to GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in zip(villages_df['longitude'], villages_df['latitude'])]
    villages_gdf = gpd.GeoDataFrame(villages_df, geometry=geometry, crs='EPSG:4326')
    
    # Extract landslide coordinates
    landslide_coords = np.array(list(zip(
        landslide_gdf.geometry.x if hasattr(landslide_gdf.geometry, 'x') else [g.x for g in landslide_gdf.geometry],
        landslide_gdf.geometry.y if hasattr(landslide_gdf.geometry, 'y') else [g.y for g in landslide_gdf.geometry]
    )))
    
    # Handle different geometry types
    if 'POINT' in str(landslide_gdf.geometry.type.values[0]).upper():
        landslide_coords = np.array(list(zip(
            [g.x for g in landslide_gdf.geometry],
            [g.y for g in landslide_gdf.geometry]
        )))
    else:
        # Extract centroids
        landslide_gdf_proj = landslide_gdf.to_crs(epsg=32646)
        centroids = landslide_gdf_proj.geometry.centroid.to_crs(epsg=4326)
        landslide_coords = np.array(list(zip(
            [c.x for c in centroids],
            [c.y for c in centroids]
        )))
    
    village_coords = np.array(list(zip(villages_gdf.geometry.x, villages_gdf.geometry.y)))
    
    # Build KDTree
    print("  Building spatial index...")
    tree = cKDTree(landslide_coords)
    
    # Find nearest landslide for each village
    print("  Computing distance to nearest landslide...")
    distances, indices = tree.query(village_coords, k=1)
    distances_km = distances * 111  # Convert degrees to km (rough)
    
    # Compute density (landslides within radius)
    print("  Computing landslide density...")
    radius_50km = 50 / 111  # Convert km to degrees (~0.45)
    radius_100km = 100 / 111  # ~0.90
    
    density_50km = tree.query_ball_point(village_coords, r=radius_50km)
    density_100km = tree.query_ball_point(village_coords, r=radius_100km)
    
    villages_df = villages_df.copy()
    villages_df['dist_to_nearest_landslide_km'] = distances_km
    villages_df['landslide_density_50km'] = [len(pts) for pts in density_50km]
    villages_df['landslide_density_100km'] = [len(pts) for pts in density_100km]
    
    # Add landslide state/district info
    if 'STATE' in landslide_gdf.columns:
        print("\n  Landslide distribution by state:")
        state_counts = landslide_gdf['STATE'].value_counts()
        for state, count in state_counts.head(10).items():
            print(f"    {state}: {count:,}")
    
    print(f"  Landslide feature extraction complete")
    
    return villages_df


def main():
    """Main execution."""
    print("=" * 60)
    print("Phase 1b: Vector Feature Extraction")
    print("=" * 60)
    
    # Load village coordinates
    csv_path = os.path.join(OUTPUT_DIR, 'ne_india_census_with_coords.csv')
    villages_df = pd.read_csv(csv_path, usecols=['Village Name', 'State Name', 'District Name', 'latitude', 'longitude'])
    villages_df = villages_df.dropna(subset=['latitude', 'longitude'])
    print(f"Loaded {len(villages_df):,} villages with coordinates")
    
    # Extract features
    villages_df = extract_vector_features(villages_df)
    villages_df = extract_landslide_features(villages_df)
    
    # Save output
    output_path = os.path.join(OUTPUT_DIR, 'village_vector_features.csv')
    villages_df.to_csv(output_path, index=False)
    print(f"\nSaved: {output_path}")
    print(f"Shape: {villages_df.shape}")
    
    # Summary statistics
    print("\n--- Feature Summary ---")
    for col in villages_df.columns:
        if col not in ['Village Name', 'State Name', 'District Name', 'latitude', 'longitude']:
            valid = villages_df[col].notna().sum()
            if valid > 0:
                mean_val = villages_df[col].mean()
                print(f"  {col}: {valid:,} valid, mean={mean_val:.2f}")

if __name__ == '__main__':
    main()
