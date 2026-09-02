"""
FIX 1: Correct corrupted slope_degrees values.

Root cause: extract_raster_features.py computed the elevation gradient using
pixel size in degrees (EPSG:4326) instead of meters, causing rise(meters)/
run(degrees) to blow up toward ~90° for every village.

Fix: Re-compute slope using pixel_m = pixel_degrees * 111320 * cos(lat).

This script reads ne_india_village_features.csv, re-computes slope for all
44K villages from the original SRTM tiles, and overwrites the slope_degrees
column in-place.
"""

import rasterio
import numpy as np
import pandas as pd
import os
import re

SRTM_DIR = os.path.join('data', 'raw', 'srtm')
FEATURES_CSV = os.path.join('data', 'processed', 'ne_india_village_features.csv')


def get_srtm_tile(lat, lon, tile_map):
    """Find the SRTM tile file for a given lat/lon."""
    tile_lat = int(np.floor(lat))
    tile_lon = int(np.floor(lon))
    key = (tile_lat, tile_lon)
    return tile_map.get(key)


def build_tile_map():
    """Build a mapping of (lat, lon) -> tile file path."""
    srtm_files = [f for f in os.listdir(SRTM_DIR) if f.endswith('.tif')]
    tile_map = {}
    for f in srtm_files:
        match = re.search(r'n(\d+)_e(\d+)', f)
        if match:
            lat = int(match.group(1))
            lon = int(match.group(2))
            tile_map[(lat, lon)] = os.path.join(SRTM_DIR, f)
    return tile_map


def compute_slope_fixed(lat, lon, tile_map):
    """Compute slope in degrees using proper meter-based gradient.

    Returns (elevation, slope_degrees) or (None, None) on failure.
    """
    tile_path = get_srtm_tile(lat, lon, tile_map)
    if not tile_path:
        return None, None

    try:
        with rasterio.open(tile_path) as src:
            row_col = list(src.sample([(lon, lat)]))[0]
            if row_col[0] == src.nodata or np.isnan(row_col[0]):
                return None, None

            elev = float(row_col[0])

            # Read 3x3 window around village
            px, py = src.index(lon, lat)
            half_w = 1
            r0 = max(0, px - half_w)
            r1 = min(src.height, px + half_w + 1)
            c0 = max(0, py - half_w)
            c1 = min(src.width, py + half_w + 1)

            if (r1 - r0) < 3 or (c1 - c0) < 3:
                return elev, None

            window = src.read(1, window=((r0, r1), (c0, c1))).astype(float)
            window[window == src.nodata] = np.nan

            if np.all(np.isnan(window)):
                return elev, None

            # FIXED: convert pixel size from degrees to meters
            lat_rad = np.radians(lat)
            pixel_m_x = src.res[0] * 111320 * np.cos(lat_rad)  # longitude
            pixel_m_y = src.res[1] * 111320  # latitude

            dy, dx = np.gradient(window, pixel_m_y, pixel_m_x)
            slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
            slope_deg = np.nanmean(np.degrees(slope_rad))

            return elev, slope_deg

    except Exception:
        return None, None


def main():
    print("=" * 60)
    print("FIX 1: Correcting corrupted slope_degrees")
    print("=" * 60)

    # Load features
    print("Loading feature matrix...")
    df = pd.read_csv(FEATURES_CSV, low_memory=False)
    n = len(df)
    print(f"  Loaded {n:,} villages")

    # Show current (broken) slope distribution
    print(f"\n  BEFORE fix:")
    print(f"    Mean: {df['slope_degrees'].mean():.2f}°")
    print(f"    Median: {df['slope_degrees'].median():.2f}°")
    print(f"    > 15°: {(df['slope_degrees'] > 15).sum():,} ({(df['slope_degrees'] > 15).mean()*100:.1f}%)")
    print(f"    > 80°: {(df['slope_degrees'] > 80).sum():,} ({(df['slope_degrees'] > 80).mean()*100:.1f}%)")

    # Build SRTM tile map
    print("\nBuilding SRTM tile map...")
    tile_map = build_tile_map()
    print(f"  Found {len(tile_map)} tiles")

    # Re-compute slope for all villages
    print(f"\nRe-computing slope for {n:,} villages...")
    slope_fixed = np.full(n, np.nan)
    elev_fixed = np.full(n, np.nan)

    for idx, row in df.iterrows():
        lat, lon = row['latitude'], row['longitude']
        if pd.isna(lat) or pd.isna(lon):
            continue

        elev, slope = compute_slope_fixed(lat, lon, tile_map)
        if elev is not None:
            elev_fixed[idx] = elev
        if slope is not None:
            slope_fixed[idx] = slope

        if (idx + 1) % 5000 == 0:
            print(f"  Processed {idx+1:,} / {n:,}...")

    # Show corrected distribution
    valid = ~np.isnan(slope_fixed)
    print(f"\n  AFTER fix ({valid.sum():,} villages with valid slope):")
    print(f"    Mean: {np.nanmean(slope_fixed):.2f}°")
    print(f"    Median: {np.nanmedian(slope_fixed):.2f}°")
    print(f"    > 15°: {(slope_fixed[valid] > 15).sum():,} ({(slope_fixed[valid] > 15).mean()*100:.1f}%)")
    print(f"    > 80°: {(slope_fixed[valid] > 80).sum():,} ({(slope_fixed[valid] > 80).mean()*100:.1f}%)")
    print(f"    < 5°: {(slope_fixed[valid] < 5).sum():,} ({(slope_fixed[valid] < 5).mean()*100:.1f}%)")

    # Update DataFrame
    df['slope_degrees'] = slope_fixed
    # Also update elevation if we have better values
    elev_mask = ~np.isnan(elev_fixed)
    df.loc[elev_mask, 'elevation_m'] = elev_fixed[elev_mask]

    # Save
    df.to_csv(FEATURES_CSV, index=False)
    print(f"\n  Saved: {FEATURES_CSV}")


if __name__ == '__main__':
    main()
