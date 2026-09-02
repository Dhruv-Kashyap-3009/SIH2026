#!/usr/bin/env python3
"""
Task 1a: Carrying Capacity Engine

For every GREEN or low-ORANGE village, compute a carrying_capacity_score (0-1)
and estimated_absorbable_population based on:
  - Available land (geographical area minus built-up, forest, water)
  - Population density (inverse — lower density = more capacity)
  - Water source count and adequacy
  - Power supply coverage
  - Road connectivity
  - Distance to hospital/school

Output: data/processed/carrying_capacity.csv
"""

import pandas as pd
import numpy as np
import os
import sys


def compute_carrying_capacity(df):
    """
    Compute carrying capacity score for candidate relocation sites.
    
    Only GREEN villages and ORANGE with risk_score < 0.5 are eligible.
    """
    print("Computing carrying capacity scores...")
    
    # Select candidate villages (safe sites)
    zone_col = 'predicted_risk_zone' if 'predicted_risk_zone' in df.columns else 'risk_zone'
    candidates = df[
        (df[zone_col] == 'GREEN') | 
        ((df[zone_col] == 'ORANGE') & (df['risk_score'] < 0.5))
    ].copy()
    
    print(f"  Candidate villages (GREEN + low-ORANGE): {len(candidates)}")
    
    # --- Feature 1: Available Land (0-1) ---
    # Higher available land = higher capacity
    total_area = candidates['Total Geographical Area (in Hectares)'].fillna(0)
    forest_area = candidates['Forest Area (in Hectares)'].fillna(0)
    barren_area = candidates['Barren & Un-cultivable Land Area (in Hectares)'].fillna(0)
    non_agri = candidates['Area under Non-Agricultural Uses (in Hectares)'].fillna(0)
    
    # Available land = total - forest - barren - non-agricultural (built-up)
    available_land = (total_area - forest_area - barren_area - non_agri).clip(lower=0)
    land_score = (available_land / total_area.replace(0, np.nan)).fillna(0).clip(0, 1)
    
    # --- Feature 2: Population Density (inverse) ---
    # Lower current density = more room for newcomers
    population = candidates['Total Population of Village'].fillna(0)
    density = population / total_area.replace(0, np.nan)
    density = density.fillna(density.median() if density.notna().any() else 0)
    # Normalize: 0 = very dense (bad), 1 = very sparse (good)
    # Use inverse: villages with low density get high score
    p95 = max(density.quantile(0.95), 1.0)
    density_score = 1.0 - (density / p95)
    density_score = density_score.clip(0, 1).fillna(0.5)
    
    # --- Feature 3: Water Sources (0-1) ---
    # Count functional water sources (Status A(1) = available)
    water_cols = [
        'Tap Water-Treated (Status A(1)/NA(2))',
        'Tap Water Untreated (Status A(1)/NA(2))',
        'Covered Well (Status A(1)/NA(2))',
        'Uncovered  Well (Status A(1)/NA(2))',
        'Hand Pump (Status A(1)/NA(2))',
        'Tube Wells/Borehole (Status A(1)/NA(2))',
        'Spring (Status A(1)/NA(2))',
        'River/Canal (Status A(1)/NA(2))',
        'Tank/Pond/Lake (Status A(1)/NA(2))',
    ]
    water_count = pd.DataFrame(index=candidates.index)
    for col in water_cols:
        if col in candidates.columns:
            water_count[col] = (candidates[col] == 1).astype(int)
    water_score = water_count.sum(axis=1) / len(water_cols)
    
    # --- Feature 4: Power Supply (0-1) ---
    power_col = 'Power Supply For Domestic Use  (Status A(1)/NA(2))'
    power_hours_col = 'Power Supply For Domestic Use Summer (April-Sept.) per day (in Hours)'
    if power_col in candidates.columns:
        power_status = (candidates[power_col] == 1).astype(float)
    else:
        power_status = pd.Series(0.5, index=candidates.index)
    
    if power_hours_col in candidates.columns:
        power_hours = candidates[power_hours_col].fillna(0)
        power_hours_norm = (power_hours / 24.0).clip(0, 1)
    else:
        power_hours_norm = pd.Series(0.5, index=candidates.index)
    
    power_score = (power_status * 0.4 + power_hours_norm * 0.6)
    
    # --- Feature 5: Road Connectivity (0-1) ---
    road_dist = candidates['dist_to_nearest_road_km'].fillna(5)
    road_score = 1.0 - (road_dist / 10).clip(0, 1)  # <1km = good, >10km = bad
    
    # --- Feature 6: Health Access (0-1) ---
    hosp_dist = candidates['dist_to_nearest_hospital_km'].fillna(20)
    hosp_score = 1.0 - (hosp_dist / 30).clip(0, 1)  # <5km = good, >30km = bad
    
    # --- Feature 7: Education Access (0-1) ---
    school_dist = candidates['dist_to_nearest_school_km'].fillna(5)
    school_score = 1.0 - (school_dist / 10).clip(0, 1)  # <1km = good, >10km = bad
    
    # --- Combined Score with weights ---
    weights = {
        'land': 0.20,
        'density': 0.20,
        'water': 0.20,
        'power': 0.10,
        'road': 0.15,
        'health': 0.10,
        'education': 0.05,
    }
    
    carrying_capacity_score = (
        weights['land'] * land_score +
        weights['density'] * density_score +
        weights['water'] * water_score +
        weights['power'] * power_score +
        weights['road'] * road_score +
        weights['health'] * hosp_score +
        weights['education'] * school_score
    ).clip(0, 1)
    
    # --- Identify limiting factor ---
    scores = pd.DataFrame({
        'land': land_score,
        'density': density_score,
        'water': water_score,
        'power': power_score,
        'road': road_score,
        'health': hosp_score,
        'education': school_score,
    }, index=candidates.index)
    limiting_factor = scores.idxmin(axis=1)
    
    # --- Estimate absorbable population ---
    # Based on land area per capita norms (India: ~0.05 hectares/person for rural)
    # and existing population
    hectares_per_person = 0.05  # 500 sq meters per person
    max_pop_by_land = (available_land / hectares_per_person).clip(lower=0)
    existing_pop = candidates['Total Population of Village'].fillna(0)
    # Absorbable = max capacity - current population (can't go negative)
    estimated_absorbable = ((max_pop_by_land - existing_pop) * carrying_capacity_score).clip(lower=0)
    
    # Build output
    result = pd.DataFrame({
        'village_id': candidates['habitation_id'].values,
        'village_name': candidates['Village Name'].values,
        'state': candidates['State Name'].values,
        'district': candidates['District Name'].values,
        'latitude': candidates['latitude'].values,
        'longitude': candidates['longitude'].values,
        'carrying_capacity_score': carrying_capacity_score.values,
        'estimated_absorbable_population': estimated_absorbable.values.astype(int),
        'limiting_factor': limiting_factor.values,
        'available_land_hectares': available_land.values,
        'current_population': existing_pop.values.astype(int),
        'risk_zone': candidates[zone_col].values,
        'risk_score': candidates['risk_score'].values,
    })
    
    print(f"  Carrying capacity scores: min={result['carrying_capacity_score'].min():.3f}, "
          f"max={result['carrying_capacity_score'].max():.3f}, "
          f"mean={result['carrying_capacity_score'].mean():.3f}")
    print(f"  Total absorbable population: {result['estimated_absorbable_population'].sum():,.0f}")
    print(f"  Limiting factors: {result['limiting_factor'].value_counts().to_dict()}")
    
    return result


def main():
    # prediction_output.csv already has ALL columns (Census + features + predictions)
    pred_path = os.path.join('data', 'processed', 'prediction_output.csv')
    
    print("Loading prediction output (has all Census + feature + prediction columns)...")
    df = pd.read_csv(pred_path, low_memory=False)
    print(f"  Loaded {len(df)} villages with {len(df.columns)} columns")
    
    # Compute carrying capacity
    result = compute_carrying_capacity(df)
    
    # Save
    output_path = os.path.join('data', 'processed', 'carrying_capacity.csv')
    result.to_csv(output_path, index=False)
    print(f"\nSaved carrying_capacity.csv: {len(result)} villages")
    print(f"  Columns: {list(result.columns)}")
    
    return result


if __name__ == '__main__':
    main()
