#!/usr/bin/env python3
"""
Task 1b: Relocation Site Matching

For every RED (and HIGH-priority ORANGE) village, find the top 3 candidate
GREEN/safe villages within a configurable radius (default 50km), ranked by a
combined score of carrying_capacity_score and inverse distance.

Uses greedy allocation: once a target village's absorbable population is
exhausted by higher-priority matches, it's removed from the candidate pool.

Output: data/processed/relocation_matches.csv
"""

import pandas as pd
import numpy as np
import os


def haversine_km_vec(lat1, lon1, lat2_arr, lon2_arr):
    """Vectorized haversine: one point vs array of points. Returns km array."""
    R = 6371.0
    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2_arr)
    lon2 = np.radians(lon2_arr)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))


def match_relocation_sites(capacity_df, pred_df, radius_km=50, top_n=3):
    """
    Match RED/HIGH-priority villages to safe relocation sites.
    
    Uses greedy allocation: higher-priority source villages get first pick.
    Once a target's absorbable population is exhausted, it's skipped.
    """
    print(f"Matching relocation sites (radius={radius_km}km, top_n={top_n})...")
    
    # Source villages: RED zone or HIGH priority ORANGE (use model predictions, not training labels)
    zone_col = 'predicted_risk_zone' if 'predicted_risk_zone' in pred_df.columns else 'risk_zone'
    sources = pred_df[
        (pred_df[zone_col] == 'RED') |
        ((pred_df[zone_col] == 'ORANGE') & (pred_df['priority_level'] == 'HIGH'))
    ].copy()
    
    # Sort by risk_score descending (highest risk first = greedy priority)
    sources = sources.sort_values('risk_score', ascending=False).reset_index(drop=True)
    
    print(f"  Source villages (RED + HIGH-priority ORANGE): {len(sources)}")
    print(f"  Candidate targets: {len(capacity_df)}")
    
    # Target villages (from carrying_capacity output)
    targets = capacity_df.copy()
    targets['remaining_capacity'] = targets['estimated_absorbable_population'].copy()
    
    # Pre-compute target coordinates as numpy arrays for speed
    target_lats = targets['latitude'].values
    target_lons = targets['longitude'].values
    target_ids = targets['village_id'].values
    target_scores = targets['carrying_capacity_score'].values
    target_remaining = targets['remaining_capacity'].values.copy()
    
    matches = []
    no_match_count = 0
    
    for idx, source in sources.iterrows():
        if idx % 5000 == 0:
            print(f"    Processing source {idx+1}/{len(sources)}...")
        
        src_lat = source['latitude']
        src_lon = source['longitude']
        src_pop = source.get('Total Population of Village', 1000)
        if pd.isna(src_pop) or src_pop == 0:
            src_pop = 1000
        
        # Vectorized haversine distance to all targets
        distances = haversine_km_vec(src_lat, src_lon, target_lats, target_lons)
        
        # Filter: within radius and has remaining capacity
        within_radius = distances <= radius_km
        has_capacity = target_remaining > 0
        candidate_mask = within_radius & has_capacity
        
        if not candidate_mask.any():
            no_match_count += 1
            matches.append({
                'source_village_id': source['habitation_id'],
                'source_village_name': source['Village Name'],
                'source_state': source['State Name'],
                'source_district': source['District Name'],
                'source_latitude': src_lat,
                'source_longitude': src_lon,
                'source_risk_score': source['risk_score'],
                'target_village_id': 'NO_SAFE_SITE_FOUND',
                'target_village_name': '',
                'target_state': '',
                'target_district': '',
                'target_latitude': np.nan,
                'target_longitude': np.nan,
                'distance_km': np.nan,
                'target_carrying_capacity_score': np.nan,
                'target_remaining_capacity': np.nan,
            })
            continue
        
        # Rank candidates: combined score = capacity_score * (1 - distance/radius)
        cand_indices = np.where(candidate_mask)[0]
        cand_distances = distances[cand_indices]
        cand_scores = target_scores[cand_indices]
        combined = cand_scores * (1 - cand_distances / radius_km)
        
        # Sort by combined score descending
        top_indices = cand_indices[np.argsort(-combined)][:top_n]
        
        # Build distance lookup for matched indices
        ti_distances = distances[top_indices]
        
        for i, ti in enumerate(top_indices):
            alloc_pop = min(src_pop, target_remaining[ti])
            target_remaining[ti] -= alloc_pop
            
            matches.append({
                'source_village_id': source['habitation_id'],
                'source_village_name': source['Village Name'],
                'source_state': source['State Name'],
                'source_district': source['District Name'],
                'source_latitude': src_lat,
                'source_longitude': src_lon,
                'source_risk_score': source['risk_score'],
                'target_village_id': target_ids[ti],
                'target_village_name': targets.iloc[ti]['village_name'],
                'target_state': targets.iloc[ti]['state'],
                'target_district': targets.iloc[ti]['district'],
                'target_latitude': target_lats[ti],
                'target_longitude': target_lons[ti],
                'distance_km': round(float(ti_distances[i]), 2),
                'target_carrying_capacity_score': round(float(target_scores[ti]), 3),
                'target_remaining_capacity': int(target_remaining[ti]),
            })
    
    result = pd.DataFrame(matches)
    
    print(f"\n  Matched {len(result)} rows")
    print(f"  Unique source villages: {result['source_village_id'].nunique()}")
    print(f"  No safe site found: {no_match_count}")
    print(f"  Target utilization: {len(targets) - (target_remaining > 0).sum()}/{len(targets)} targets used")
    
    return result


def main():
    capacity_path = os.path.join('data', 'processed', 'carrying_capacity.csv')
    pred_path = os.path.join('data', 'processed', 'prediction_output.csv')
    
    print("Loading carrying capacity data...")
    capacity_df = pd.read_csv(capacity_path)
    print(f"  Loaded {len(capacity_df)} candidate sites")
    
    print("Loading prediction output...")
    pred_df = pd.read_csv(pred_path, low_memory=False)
    print(f"  Loaded {len(pred_df)} villages")
    
    result = match_relocation_sites(capacity_df, pred_df, radius_km=50, top_n=3)
    
    output_path = os.path.join('data', 'processed', 'relocation_matches.csv')
    result.to_csv(output_path, index=False)
    print(f"\nSaved relocation_matches.csv: {len(result)} matches")
    print(f"  Columns: {list(result.columns)}")


if __name__ == '__main__':
    main()
