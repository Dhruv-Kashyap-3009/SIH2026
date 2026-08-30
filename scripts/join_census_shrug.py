"""
Join Census 2011 Village Directory with SHRUG Village Polygons
to add latitude/longitude coordinates to Census data.

This script:
1. Loads Census xlsx files for NE India states
2. Extracts village identifiers (State Code, District Code, Sub District Code, Village Code)
3. Loads SHRUG village polygon centroids (lat/lng)
4. Joins them using Census 2011 identifiers
5. Outputs a comprehensive CSV with all Census columns + coordinates
"""

import pandas as pd
import geopandas as gpd
import os
import warnings
warnings.filterwarnings('ignore')

# Configuration
CENSUS_DIR = 'data/raw/census'
SHRUG_DIR = 'data/raw/shrug'
OUTPUT_DIR = 'data/processed'

# NE India state mappings (Census state code -> state name)
NE_STATES = {
    '18': 'Assam',
    '17': 'Meghalaya',
    '12': 'Arunachal Pradesh',
    '14': 'Manipur',
    '15': 'Mizoram',
    '16': 'Tripura',
    '13': 'Nagaland',
    '11': 'Sikkim'
}

# Census xlsx file mapping
CENSUS_FILES = {
    '18': 'assam_village_directory.xlsx',
    '17': 'meghalaya_village_directory.xlsx',
    '12': 'arunachal_pradesh_village_directory.xlsx',
    '14': 'manipur_village_directory.xlsx',
    '15': 'mizoram_village_directory.xlsx',
    '16': 'tripura_village_directory.xlsx',
    '13': 'nagaland_village_directory.xlsx',
    # '11': 'sikkim_village_directory.xlsx',  # This is a PDF, skip
}


def load_census_data():
    """Load and combine Census xlsx files for NE India states."""
    print("Loading Census data...")
    all_census = []
    
    for state_code, filename in CENSUS_FILES.items():
        filepath = os.path.join(CENSUS_DIR, filename)
        if not os.path.exists(filepath):
            print(f"  WARNING: {filepath} not found, skipping")
            continue
        
        print(f"  Loading {filename}...")
        df = pd.read_excel(filepath, header=0)
        
        # The Census files have standard columns:
        # Col 0: State Code, Col 2: District Code, Col 4: Sub District Code
        # Col 6: Village Code, Col 7: Village Name
        # We need to ensure these columns are properly named
        cols = df.columns.tolist()
        
        # Rename first few columns if needed
        rename_map = {}
        if len(cols) > 0 and 'State' not in str(cols[0]):
            rename_map[cols[0]] = 'State Code'
        if len(cols) > 2 and 'District' not in str(cols[2]):
            rename_map[cols[2]] = 'District Code'
        if len(cols) > 4 and 'Sub' not in str(cols[4]):
            rename_map[cols[4]] = 'Sub District Code'
        if len(cols) > 6 and 'Village' not in str(cols[6]):
            rename_map[cols[6]] = 'Village Code'
        if len(cols) > 7 and 'Village' not in str(cols[7]):
            rename_map[cols[7]] = 'Village Name'
        
        if rename_map:
            df = df.rename(columns=rename_map)
        
        # Ensure state code is string
        df['State Code'] = df['State Code'].astype(str).str.strip()
        df['District Code'] = df['District Code'].astype(str).str.strip()
        df['Sub District Code'] = df['Sub District Code'].astype(str).str.strip()
        df['Village Code'] = df['Village Code'].astype(str).str.strip()
        
        # Add state name
        df['State Name'] = NE_STATES.get(state_code, f'State_{state_code}')
        
        print(f"    {len(df):,} villages loaded")
        all_census.append(df)
    
    if all_census:
        combined = pd.concat(all_census, ignore_index=True)
        print(f"\nTotal Census villages: {len(combined):,}")
        return combined
    else:
        print("ERROR: No Census data loaded!")
        return None


def load_shrug_coordinates():
    """Load SHRUG village polygon centroids."""
    print("\nLoading SHRUG village polygons...")
    
    gpkg_path = os.path.join(SHRUG_DIR, 'village_modified.gpkg')
    if not os.path.exists(gpkg_path):
        print(f"ERROR: {gpkg_path} not found!")
        return None
    
    # Load all villages
    gdf = gpd.read_file(gpkg_path)
    
    # Filter for NE India states
    ne_state_ids = list(NE_STATES.keys())
    gdf['pc11_state_id'] = gdf['pc11_state_id'].astype(str)
    ne_mask = gdf['pc11_state_id'].isin(ne_state_ids)
    gdf_ne = gdf[ne_mask].copy()
    
    print(f"  Total SHRUG villages: {len(gdf):,}")
    print(f"  NE India villages: {len(gdf_ne):,}")
    
    # Compute centroids (project to UTM first for accuracy)
    # NE India is in UTM zone 46N (EPSG:32646)
    print("  Computing centroids...")
    gdf_ne_proj = gdf_ne.to_crs(epsg=32646)
    centroids = gdf_ne_proj.geometry.centroid
    centroids_geog = centroids.to_crs(epsg=4326)
    
    gdf_ne['latitude'] = centroids_geog.y
    gdf_ne['longitude'] = centroids_geog.x
    
    # Create a DataFrame with matching columns
    shrug_df = gdf_ne[['pc11_state_id', 'pc11_district_id', 'pc11_subdistrict_id', 
                       'pc11_town_village_id', 'town_village_name', 'latitude', 'longitude']].copy()
    
    # Rename columns to match Census
    shrug_df = shrug_df.rename(columns={
        'pc11_state_id': 'State Code',
        'pc11_district_id': 'District Code',
        'pc11_subdistrict_id': 'Sub District Code',
        'pc11_town_village_id': 'Village Code',
        'town_village_name': 'SHRUG Village Name'
    })
    
    # Ensure codes are strings
    for col in ['State Code', 'District Code', 'Sub District Code', 'Village Code']:
        shrug_df[col] = shrug_df[col].astype(str).str.strip()
    
    print(f"  SHRUG coordinates ready: {len(shrug_df):,} villages")
    return shrug_df


def join_census_shrug(census_df, shrug_df):
    """Join Census data with SHRUG coordinates."""
    print("\nJoining Census + SHRUG...")
    
    # Join on composite key
    join_keys = ['State Code', 'District Code', 'Sub District Code', 'Village Code']
    
    merged = census_df.merge(
        shrug_df,
        on=join_keys,
        how='left',
        suffixes=('', '_shrug')
    )
    
    # Check match rate
    matched = merged['latitude'].notna().sum()
    total = len(merged)
    match_rate = matched / total * 100
    
    print(f"  Matched: {matched:,} / {total:,} villages ({match_rate:.1f}%)")
    
    # Report unmatched by state
    unmatched = merged[merged['latitude'].isna()]
    if len(unmatched) > 0:
        print(f"\n  Unmatched villages by state:")
        for state, count in unmatched['State Name'].value_counts().items():
            total_state = len(merged[merged['State Name'] == state])
            print(f"    {state}: {count:,} / {total_state:,} unmatched")
    
    return merged


def select_key_columns(df):
    """Select the most important columns for the prediction pipeline."""
    # Key vulnerability/infrastructure columns from Census
    key_cols = [
        'State Code', 'State Name', 'District Code', 'District Name',
        'Sub District Code', 'Sub District Name',
        'Village Code', 'Village Name',
        'latitude', 'longitude'
    ]
    
    # Available population/demographic columns (check which exist)
    demo_cols = [col for col in df.columns if any(kw in str(col).lower() for kw in [
        'population', 'male', 'female', 'child', 'sc ', 'st ', 'literacy',
        'household', 'area', 'density'
    ])]
    
    # Infrastructure columns
    infra_cols = [col for col in df.columns if any(kw in str(col).lower() for kw in [
        'road', 'school', 'hospital', 'health', 'electric', 'water', 'bank',
        'post office', 'telephone', 'internet', 'mobile'
    ])]
    
    # Select all available key columns
    available_cols = [col for col in key_cols + demo_cols + infra_cols if col in df.columns]
    
    # Always include latitude/longitude
    for col in ['latitude', 'longitude']:
        if col not in available_cols:
            available_cols.append(col)
    
    return df[available_cols].copy()


def main():
    """Main execution."""
    print("=" * 60)
    print("Census + SHRUG Join Script")
    print("=" * 60)
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Load data
    census_df = load_census_data()
    if census_df is None:
        return
    
    shrug_df = load_shrug_coordinates()
    if shrug_df is None:
        return
    
    # Join
    merged = join_census_shrug(census_df, shrug_df)
    
    # Select key columns
    output_df = select_key_columns(merged)
    
    # Save full output
    output_path = os.path.join(OUTPUT_DIR, 'ne_india_villages_with_coords.csv')
    output_df.to_csv(output_path, index=False)
    print(f"\nSaved: {output_path}")
    print(f"Shape: {output_df.shape}")
    
    # Save summary stats
    summary_path = os.path.join(OUTPUT_DIR, 'join_summary.txt')
    with open(summary_path, 'w') as f:
        f.write("Census + SHRUG Join Summary\n")
        f.write("=" * 40 + "\n\n")
        f.write(f"Total villages: {len(output_df):,}\n")
        f.write(f"With coordinates: {output_df['latitude'].notna().sum():,}\n")
        f.write(f"Match rate: {output_df['latitude'].notna().sum() / len(output_df) * 100:.1f}%\n\n")
        f.write("Villages by state:\n")
        for state, count in output_df['State Name'].value_counts().items():
            f.write(f"  {state}: {count:,}\n")
    
    print(f"Summary saved: {summary_path}")
    print("\nDone!")


if __name__ == '__main__':
    main()
