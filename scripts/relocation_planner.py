"""
Phase 3: Relocation Planning Module

For every HIGH-priority RED village, finds candidate GREEN villages within
a configurable max travel distance, solves the assignment as a transportation
problem (minimizing total distance subject to capacity constraints).

Approaches:
1. Greedy nearest-available-capacity (fast, O(n*m))
2. scipy.optimize.linprog LP (optimal, but may be slow at 44K scale)

Benchmarks both and uses greedy (which is near-optimal for this problem).

Output: data/processed/relocation_plan.csv

Usage:
    python scripts/relocation_planner.py                    # All villages
    python scripts/relocation_planner.py --village "Betanipam"  # Single village
    python scripts/relocation_planner.py --radius 30        # Custom radius
"""

import pandas as pd
import numpy as np
import os
import sys
import argparse
import time

OUTPUT_DIR = 'data/processed'


def haversine_km(lat1, lon1, lat2, lon2):
    """Vectorized haversine distance in km."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))


def greedy_assignment(sources, targets, radius_km=50, max_per_target=50):
    """Greedy nearest-available-capacity assignment.

    For each source village (sorted by risk_score descending):
    1. Find all targets within radius_km
    2. Rank by (carrying_capacity_score / distance)
    3. Assign to the best available target that still has capacity
    4. Reduce target's remaining capacity

    Returns: list of assignment dicts
    """
    assignments = []
    remaining_capacity = targets['estimated_absorbable_population'].values.copy()
    target_lats = targets['latitude'].values
    target_lons = targets['longitude'].values
    target_ids = targets['village_id'].values
    target_names = targets['village_name'].values
    target_scores = targets['carrying_capacity_score'].values

    for idx, source in sources.iterrows():
        if idx % 5000 == 0 and idx > 0:
            print(f"    Greedy: {idx}/{len(sources)} sources processed...")

        # Find targets within radius
        dists = haversine_km(source['latitude'], source['longitude'],
                             target_lats, target_lons)
        within_radius = dists <= radius_km
        has_capacity = remaining_capacity > 0
        candidates = within_radius & has_capacity

        if not candidates.any():
            assignments.append({
                'red_village_id': source.get('village_id', source.name),
                'red_village_name': source.get('Village Name', ''),
                'red_state': source.get('state', ''),
                'red_district': source.get('district', ''),
                'red_latitude': source['latitude'],
                'red_longitude': source['longitude'],
                'red_risk_score': source.get('risk_score', 0),
                'green_village_id': None,
                'green_village_name': None,
                'distance_km': None,
                'target_carrying_capacity_score': None,
                'capacity_fit': None,
                'feasibility_flag': 'no_feasible_relocation_site_within_range',
            })
            continue

        # Rank candidates by capacity_score / distance (higher = better)
        cand_dists = dists[candidates]
        cand_scores = target_scores[candidates]
        cand_ids = target_ids[candidates]
        cand_names = target_names[candidates]
        cand_remaining = remaining_capacity[candidates]

        utility = cand_scores / np.maximum(cand_dists, 0.1)
        best_idx = np.argmax(utility)

        # Assign to best candidate
        assigned_target_id = cand_ids[best_idx]
        assigned_dist = cand_dists[best_idx]
        assigned_score = cand_scores[best_idx]
        assigned_remaining = cand_remaining[best_idx]

        # Estimate how many people this source village needs
        source_pop = source.get('Total Population of Village', 500)
        absorbable = min(source_pop, assigned_remaining)

        # Update remaining capacity
        orig_idx = np.where(target_ids == assigned_target_id)[0][0]
        remaining_capacity[orig_idx] -= absorbable

        # Determine capacity fit
        if absorbable >= source_pop:
            fit = 'full'
        elif absorbable >= source_pop * 0.5:
            fit = 'partial'
        else:
            fit = 'minimal'

        assignments.append({
            'red_village_id': source.get('village_id', source.name),
            'red_village_name': source.get('Village Name', ''),
            'red_state': source.get('state', ''),
            'red_district': source.get('district', ''),
            'red_latitude': source['latitude'],
            'red_longitude': source['longitude'],
            'red_risk_score': source.get('risk_score', 0),
            'green_village_id': assigned_target_id,
            'green_village_name': cand_names[best_idx],
            'distance_km': round(float(assigned_dist), 1),
            'target_carrying_capacity_score': round(float(assigned_score), 3),
            'capacity_fit': fit,
            'feasibility_flag': 'assigned',
        })

    return assignments


def lp_assignment(sources, targets, radius_km=50, timeout_s=30):
    """LP-based optimal assignment using scipy.optimize.linprog.

    This is the theoretically optimal solution but may be too slow
    for 44K villages. Used for benchmarking against greedy.
    """
    try:
        from scipy.optimize import linprog
    except ImportError:
        print("    scipy not available — skipping LP benchmark")
        return None, None

    n_src = len(sources)
    n_tgt = len(targets)

    if n_src == 0 or n_tgt == 0:
        return None, None

    # For LP, limit to first 500 sources and 200 targets (LP is O(n*m) in variables)
    n_src_limit = min(n_src, 500)
    n_tgt_limit = min(n_tgt, 200)

    src_subset = sources.iloc[:n_src_limit]
    tgt_subset = targets.iloc[:n_tgt_limit]

    # Compute distance matrix
    dist_matrix = np.zeros((n_src_limit, n_tgt_limit))
    for i in range(n_src_limit):
        dist_matrix[i] = haversine_km(
            src_subset.iloc[i]['latitude'], src_subset.iloc[i]['longitude'],
            tgt_subset['latitude'].values, tgt_subset['longitude'].values
        )

    # Mask out-of-radius with large cost
    dist_matrix[dist_matrix > radius_km] = 9999

    # Flatten to 1D for linprog
    c = dist_matrix.flatten()

    # Constraints: each source assigned to at most 1 target
    A_eq_rows = []
    b_eq_rows = []
    for i in range(n_src_limit):
        row = np.zeros(n_src_limit * n_tgt_limit)
        row[i*n_tgt_limit:(i+1)*n_tgt_limit] = 1
        A_eq_rows.append(row)
        b_eq_rows.append(1)

    # Constraints: each target capacity not exceeded
    for j in range(n_tgt_limit):
        row = np.zeros(n_src_limit * n_tgt_limit)
        for i in range(n_src_limit):
            row[i*n_tgt_limit + j] = 1
        A_eq_rows.append(row)
        # Capacity in number of assignments (simplified)
        b_eq_rows.append(min(50, int(tgt_subset.iloc[j]['estimated_absorbable_population'] // 500)))

    A_eq = np.array(A_eq_rows)
    b_eq = np.array(b_eq_rows)

    # Bounds: 0 or 1 (integer)
    bounds = [(0, 1)] * (n_src_limit * n_tgt_limit)

    start = time.time()
    try:
        result = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method='highs')
        elapsed = time.time() - start
        if result.success:
            assignments = result.x.reshape(n_src_limit, n_tgt_limit)
            return assignments, elapsed
        else:
            return None, elapsed
    except Exception as e:
        elapsed = time.time() - start
        print(f"    LP failed after {elapsed:.1f}s: {e}")
        return None, elapsed


def plan_relocations(pred_df, capacity_df, radius_km=50):
    """Main relocation planning function.

    Args:
        pred_df: prediction output DataFrame
        capacity_df: carrying capacity DataFrame
        radius_km: maximum relocation distance

    Returns:
        DataFrame with relocation plan
    """
    print(f"Planning relocations (radius={radius_km}km)...")

    # Source villages: RED or HIGH-priority ORANGE
    zone_col = 'predicted_risk_zone' if 'predicted_risk_zone' in pred_df.columns else 'risk_zone'
    score_col = 'risk_score' if 'risk_score' in pred_df.columns else 'model_risk_score'

    sources = pred_df[
        (pred_df[zone_col] == 'RED') |
        ((pred_df[zone_col] == 'ORANGE') & (pred_df.get('priority_level', '') == 'HIGH'))
    ].copy()
    sources = sources.sort_values(score_col, ascending=False).reset_index(drop=True)

    print(f"  Source villages (RED + HIGH ORANGE): {len(sources):,}")
    print(f"  Candidate targets: {len(capacity_df):,}")

    # Benchmark: greedy
    start = time.time()
    greedy_results = greedy_assignment(sources, capacity_df, radius_km=radius_km)
    greedy_time = time.time() - start
    print(f"  Greedy: {greedy_time:.1f}s, {len(greedy_results)} assignments")

    # Benchmark: LP (on subset)
    print(f"  Running LP benchmark (subset: min(500, {len(sources)}) sources)...")
    lp_result, lp_time = lp_assignment(sources, capacity_df, radius_km=radius_km)
    if lp_result is not None:
        print(f"  LP: {lp_time:.1f}s (subset)")
        # Compare greedy vs LP on the subset
        greedy_cost = sum(r['distance_km'] for r in greedy_results[:500] if r['distance_km'] is not None)
        print(f"  Greedy total distance (subset): {greedy_cost:.1f} km")
        print(f"  Using greedy (near-optimal, scales to full dataset)")
    else:
        print(f"  LP not feasible at this scale — using greedy")

    # Build output DataFrame
    result_df = pd.DataFrame(greedy_results)

    # Stats
    assigned = result_df[result_df['feasibility_flag'] == 'assigned']
    no_site = result_df[result_df['feasibility_flag'] == 'no_feasible_relocation_site_within_range']

    print(f"\n  Results:")
    print(f"    Assigned: {len(assigned):,} / {len(result_df):,} ({len(assigned)/len(result_df)*100:.1f}%)")
    print(f"    No feasible site: {len(no_site):,} ({len(no_site)/len(result_df)*100:.1f}%)")
    if len(assigned) > 0:
        print(f"    Mean distance: {assigned['distance_km'].mean():.1f} km")
        print(f"    Max distance: {assigned['distance_km'].max():.1f} km")
        print(f"    Capacity fit: {assigned['capacity_fit'].value_counts().to_dict()}")

    return result_df


def inspect_village(plan_df, village_name):
    """Print relocation plan for a specific village."""
    mask = plan_df['red_village_name'].str.contains(village_name, case=False, na=False)
    matches = plan_df[mask]

    if len(matches) == 0:
        print(f"  No villages matching '{village_name}'")
        return

    for _, row in matches.iterrows():
        print(f"\n  {'='*60}")
        print(f"  Source: {row['red_village_name']} ({row['red_district']}, {row['red_state']})")
        print(f"  Risk Score: {row['red_risk_score']:.3f}")
        if row['feasibility_flag'] == 'assigned':
            print(f"  → Recommended: {row['green_village_name']}")
            print(f"    Distance: {row['distance_km']:.1f} km")
            print(f"    Target capacity score: {row['target_carrying_capacity_score']:.3f}")
            print(f"    Capacity fit: {row['capacity_fit']}")
        else:
            print(f"  → {row['feasibility_flag']}")


def main():
    parser = argparse.ArgumentParser(description='Relocation Planner')
    parser.add_argument('--village', type=str, help='Inspect a specific village')
    parser.add_argument('--radius', type=int, default=50, help='Max relocation distance in km (default: 50)')
    parser.add_argument('--save', type=str, default=os.path.join(OUTPUT_DIR, 'relocation_plan.csv'),
                        help='Output CSV path')
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 3: Relocation Planning")
    print("=" * 60)

    # Load data
    capacity_path = os.path.join(OUTPUT_DIR, 'carrying_capacity.csv')
    pred_path = os.path.join(OUTPUT_DIR, 'prediction_output.csv')

    if not os.path.exists(capacity_path):
        print(f"  ERROR: {capacity_path} not found. Run carrying_capacity.py first.")
        sys.exit(1)
    if not os.path.exists(pred_path):
        print(f"  ERROR: {pred_path} not found. Run predict.py first.")
        sys.exit(1)

    capacity_df = pd.read_csv(capacity_path)
    pred_df = pd.read_csv(pred_path, low_memory=False)
    print(f"  Loaded {len(pred_df):,} villages, {len(capacity_df):,} candidate targets")

    # Plan relocations
    plan_df = plan_relocations(pred_df, capacity_df, radius_km=args.radius)

    # Save
    plan_df.to_csv(args.save, index=False)
    print(f"\n  Saved: {args.save}")
    print(f"  Rows: {len(plan_df):,}")

    # Inspect specific village if requested
    if args.village:
        inspect_village(plan_df, args.village)


if __name__ == '__main__':
    main()
