"""
Phase 1a: Raster Feature Extraction
Extracts elevation, slope, terrain roughness, rainfall, and land cover
for all NE India villages from downloaded raster datasets.
"""

import numpy as np
import pandas as pd
import rasterio
from rasterio.sample import sample_gen
import xarray as xr
import os
import warnings
from scipy import ndimage
warnings.filterwarnings('ignore')

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRTM_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'srtm')
IMD_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'imd_rainfall')
WORLDCOVER_DIR = os.path.join(BASE_DIR, 'data', 'raw', 'worldcover')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')

def load_village_coords():
    """Load village coordinates from processed CSV."""
    csv_path = os.path.join(OUTPUT_DIR, 'ne_india_census_with_coords.csv')
    df = pd.read_csv(csv_path, usecols=['Village Name', 'State Name', 'District Name', 'latitude', 'longitude'])
    df = df.dropna(subset=['latitude', 'longitude'])
    print(f"Loaded {len(df):,} villages with coordinates")
    return df

def extract_srtm_features(villages_df):
    """
    Extract elevation, slope, and terrain roughness from SRTM DEM tiles.
    For each village, samples the nearest pixel value from the SRTM tile.
    """
    print("\n--- SRTM Feature Extraction ---")
    
    # Get all SRTM tile files
    srtm_files = [f for f in os.listdir(SRTM_DIR) if f.endswith('.tif')]
    print(f"Found {len(srtm_files)} SRTM tiles")
    
    # Create a mapping of (lat, lon) -> tile file for fast lookup
    import re
    tile_map = {}
    for f in srtm_files:
        match = re.search(r'n(\d+)_e(\d+)', f)
        if match:
            lat = int(match.group(1))
            lon = int(match.group(2))
            tile_map[(lat, lon)] = os.path.join(SRTM_DIR, f)
    
    # Initialize output columns
    n = len(villages_df)
    elevation = np.full(n, np.nan)
    slope = np.full(n, np.nan)
    terrain_roughness = np.full(n, np.nan)
    
    # Process each village
    processed = 0
    errors = 0
    
    for idx, (_, row) in enumerate(villages_df.iterrows()):
        lat = row['latitude']
        lon = row['longitude']
        
        # Find which tile this village falls in
        tile_lat = int(lat)
        tile_lon = int(lon)
        
        tile_path = tile_map.get((tile_lat, tile_lon))
        if not tile_path:
            # Try adjacent tiles (village might be on tile boundary)
            for dlat in [-1, 0, 1]:
                for dlon in [-1, 0, 1]:
                    tile_path = tile_map.get((tile_lat + dlat, tile_lon + dlon))
                    if tile_path:
                        break
                if tile_path:
                    break
        
        if not tile_path:
            errors += 1
            continue
        
        try:
            with rasterio.open(tile_path) as src:
                # Sample elevation at village point
                row_col = list(src.sample([(lon, lat)]))[0]
                
                if row_col[0] != src.nodata and not np.isnan(row_col[0]):
                    elevation[idx] = float(row_col[0])
                    
                    # Compute slope from DEM using numpy gradient
                    # Read a small window around the point (3x3 pixels = ~90m)
                    px, py = src.index(lon, lat)
                    window_size = 3
                    half_w = window_size // 2
                    
                    # Ensure window is within bounds
                    row_start = max(0, px - half_w)
                    row_end = min(src.height, px + half_w + 1)
                    col_start = max(0, py - half_w)
                    col_end = min(src.width, py + half_w + 1)
                    
                    if (row_end - row_start) >= 3 and (col_end - col_start) >= 3:
                        window = src.read(1, window=((row_start, row_end), (col_start, col_end)))
                        window = window.astype(float)
                        window[window == src.nodata] = np.nan
                        
                        if not np.all(np.isnan(window)):
                            # Compute slope using gradient
                            dy, dx = np.gradient(window, src.res[0])
                            slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
                            slope[idx] = np.nanmean(np.degrees(slope_rad))
                            
                            # Terrain Roughness Index (standard deviation of elevation)
                            terrain_roughness[idx] = np.nanstd(window)
                    
                    processed += 1
                    
        except Exception as e:
            errors += 1
            continue
        
        if (idx + 1) % 5000 == 0:
            print(f"  Processed {idx + 1:,} / {n:,} villages...")
    
    print(f"  SRTM extraction complete: {processed:,} elevation, {errors:,} errors")
    
    villages_df = villages_df.copy()
    villages_df['elevation_m'] = elevation
    villages_df['slope_degrees'] = slope
    villages_df['terrain_roughness'] = terrain_roughness
    
    return villages_df

def extract_worldcover_features(villages_df):
    """
    Extract land cover class from ESA WorldCover tiles.
    """
    print("\n--- WorldCover Feature Extraction ---")
    
    wc_files = [f for f in os.listdir(WORLDCOVER_DIR) if f.endswith('.tif')]
    print(f"Found {len(wc_files)} WorldCover tiles")
    
    # Create tile mapping
    import re
    tile_map = {}
    for f in wc_files:
        # ESA_WorldCover_10m_2021_v200_N18E090_Map.tif -> lat=18, lon=90
        match = re.search(r'N(\d+)E(\d+)', f)
        if match:
            lat = int(match.group(1))
            lon = int(match.group(2))
            tile_map[(lat, lon)] = os.path.join(WORLDCOVER_DIR, f)
    
    n = len(villages_df)
    landcover = np.full(n, np.nan)
    
    processed = 0
    errors = 0
    
    for idx, (_, row) in enumerate(villages_df.iterrows()):
        lat = row['latitude']
        lon = row['longitude']
        
        # Find tile
        tile_lat = int(lat)
        tile_lon = int(lon)
        
        tile_path = tile_map.get((tile_lat, tile_lon))
        if not tile_path:
            # Try nearest
            for dlat in [-1, 0, 1]:
                for dlon in [-1, 0, 1]:
                    key = (tile_lat + dlat, tile_lon + dlon)
                    if key in tile_map:
                        tile_path = tile_map[key]
                        break
                if tile_path:
                    break
        
        if not tile_path:
            errors += 1
            continue
        
        try:
            with rasterio.open(tile_path) as src:
                row_col = list(src.sample([(lon, lat)]))[0]
                if row_col[0] != src.nodata:
                    landcover[idx] = float(row_col[0])
                    processed += 1
        except:
            errors += 1
        
        if (idx + 1) % 5000 == 0:
            print(f"  Processed {idx + 1:,} / {n:,} villages...")
    
    print(f"  WorldCover extraction complete: {processed:,} villages, {errors:,} errors")
    
    villages_df = villages_df.copy()
    villages_df['landcover_class'] = landcover
    
    # Map class codes to names
    class_names = {
        10: 'Tree cover', 20: 'Shrubland', 30: 'Grassland', 40: 'Cropland',
        50: 'Built-up', 60: 'Bare/sparse', 70: 'Snow/Ice', 80: 'Water',
        90: 'Wetland', 95: 'Mangroves', 100: 'Moss/lichen'
    }
    villages_df['landcover_name'] = villages_df['landcover_class'].map(class_names)
    
    return villages_df

def extract_rainfall_features(villages_df):
    """
    Extract rainfall statistics from IMD NetCDF files.
    For each village, extracts daily rainfall at the nearest grid cell,
    then computes max, mean, 90th percentile over the 5-year period.
    """
    print("\n--- IMD Rainfall Feature Extraction ---")
    
    nc_files = sorted([f for f in os.listdir(IMD_DIR) if f.endswith('.nc')])
    print(f"Found {len(nc_files)} NetCDF files")
    
    if not nc_files:
        print("  WARNING: No NetCDF files found!")
        villages_df = villages_df.copy()
        villages_df['max_daily_rainfall_mm'] = np.nan
        villages_df['mean_daily_rainfall_mm'] = np.nan
        villages_df['rainfall_90th_percentile_mm'] = np.nan
        villages_df['rainfall_95th_percentile_mm'] = np.nan
        villages_df['rain_days_per_year'] = np.nan
        return villages_df
    
    # Load all rainfall data
    print("  Loading rainfall data...")
    ds = xr.open_mfdataset(
        [os.path.join(IMD_DIR, f) for f in nc_files],
        combine='by_coords',
        engine='netcdf4'
    )
    print(f"  Dataset shape: {ds['rain'].shape}")
    print(f"  Time range: {ds.time.values[0]} to {ds.time.values[-1]}")
    
    # Extract rainfall at village coordinates
    n = len(villages_df)
    lats = villages_df['latitude'].values
    lons = villages_df['longitude'].values
    
    # Select nearest grid points for all villages at once
    print("  Extracting rainfall at village coordinates...")
    
    # Use xarray's sel with method='nearest'
    rain_data = ds['rain']
    
    max_rain = np.full(n, np.nan)
    mean_rain = np.full(n, np.nan)
    p90_rain = np.full(n, np.nan)
    p95_rain = np.full(n, np.nan)
    rain_days = np.full(n, np.nan)
    
    # Process in chunks to manage memory
    chunk_size = 1000
    for i in range(0, n, chunk_size):
        end = min(i + chunk_size, n)
        chunk_lats = lats[i:end]
        chunk_lons = lons[i:end]
        
        for j in range(end - i):
            try:
                # Select nearest grid point
                point_rain = rain_data.sel(
                    lat=chunk_lats[j], 
                    lon=chunk_lons[j], 
                    method='nearest'
                )
                
                # Compute statistics
                values = point_rain.values.flatten()
                values = values[~np.isnan(values)]
                
                if len(values) > 0:
                    max_rain[i + j] = np.nanmax(values)
                    mean_rain[i + j] = np.nanmean(values)
                    p90_rain[i + j] = np.percentile(values, 90)
                    p95_rain[i + j] = np.percentile(values, 95)
                    # Rain days: days with > 2.5mm (IMD threshold)
                    rain_days[i + j] = np.sum(values > 2.5) / len(nc_files)  # per year
                    
            except Exception as e:
                continue
        
        if (i + chunk_size) % 5000 == 0 or end == n:
            print(f"  Processed {end:,} / {n:,} villages...")
    
    ds.close()
    
    print(f"  Rainfall extraction complete")
    
    villages_df = villages_df.copy()
    villages_df['max_daily_rainfall_mm'] = max_rain
    villages_df['mean_daily_rainfall_mm'] = mean_rain
    villages_df['rainfall_90th_percentile_mm'] = p90_rain
    villages_df['rainfall_95th_percentile_mm'] = p95_rain
    villages_df['rain_days_per_year'] = rain_days
    
    return villages_df

def main():
    """Main execution."""
    print("=" * 60)
    print("Phase 1a: Raster Feature Extraction")
    print("=" * 60)
    
    # Load village coordinates
    villages_df = load_village_coords()
    
    # Extract features
    villages_df = extract_srtm_features(villages_df)
    villages_df = extract_worldcover_features(villages_df)
    villages_df = extract_rainfall_features(villages_df)
    
    # Save output
    output_path = os.path.join(OUTPUT_DIR, 'village_raster_features.csv')
    villages_df.to_csv(output_path, index=False)
    print(f"\nSaved: {output_path}")
    print(f"Shape: {villages_df.shape}")
    
    # Summary statistics
    print("\n--- Feature Summary ---")
    for col in ['elevation_m', 'slope_degrees', 'terrain_roughness', 
                'landcover_class', 'max_daily_rainfall_mm', 'mean_daily_rainfall_mm',
                'rainfall_90th_percentile_mm', 'rainfall_95th_percentile_mm', 'rain_days_per_year']:
        if col in villages_df.columns:
            valid = villages_df[col].notna().sum()
            print(f"  {col}: {valid:,} / {len(villages_df):,} valid ({valid/len(villages_df)*100:.1f}%)")

if __name__ == '__main__':
    main()
