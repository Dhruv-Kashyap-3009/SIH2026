#!/usr/bin/env python3
"""
Generate the VYOMA frontend ingestion export (single source of truth for what
the Express/Prisma backend consumes from the model side).

CANONICAL FIELD MAPPING (resolves VYOMA's Q1-Q5):
  village_id             = habitation_id (stable Census/SHRUG composite id,
                            unique across all 43,996 villages, deterministic
                            across re-runs — derived from Census codes, not a
                            random/regenerated surrogate)
  name                   = Village Name
  district / state       = district / state (aliases of District Name / State Name)
  latitude / longitude   = from SHRUG/Census coordinate join
  population             = Total Population of Village (Census 2011)
  risk_score             = susceptibility_score   (leakage-free model — CANONICAL)
  risk_level             = susceptibility_risk_zone (RED/ORANGE/GREEN, CANONICAL)
  relocation_priority    = relocation_timeline     (IMMEDIATE/SHORT_TERM/
                            MEDIUM_TERM/MONITOR — the 4 action tiers, NOT the
                            internal priority_level HIGH/MEDIUM/LOW bucket)
  vulnerability_multiplier = vulnerability_score   (there is no column named
                            population_vulnerability_multiplier; vulnerability_score
                            is the multiplier used in priority_score = risk × vuln)
  top_factors            = parsed list of {"feature","value","impact","shap_value"}
  low_confidence         = bool (missing SRTM elevation / WorldCover land cover)
  recommended_site_id    = site_id of the GREEN village assigned by
                            relocation_plan.csv, or null (no feasible site
                            within 50km / village not a relocation source)
  recommended_site_distance_km = relocation distance from relocation_plan.csv
                            (null when recommended_site_id is null)
  recommended_site_fit   = capacity fit of that assignment
                            ("full" / "partial" / "minimal", null when no
                            assignment) — relocation cost proxy: farther +
                            tighter fit = more expensive relocation
  prediction_timestamp   = predicted_at (ISO-8601 run timestamp)
  model_version          = "v1.1-susceptibility"

Deliberately EXCLUDED (per VYOMA schema): raw Census columns, all six zone
variants, all nine score variants. The two recommended_site_* fields are
OPTIONAL extensions of the original 16-field contract (null for every village
without a relocation assignment) — the village detail page renders them and
backends may ignore them if the extra keys are not needed.
This script is the single source of truth for "what VYOMA sees".

Sites export mirrors data/processed/relocation_sites.json (site_id == the
GREEN village's habitation_id, so recommended_site_id always resolves).

Outputs (all states): data/processed/vyoma_export_all_states.json +
data/processed/vyoma_sites_export_all_states.json
State-filtered:      data/processed/vyoma_export_<state>.json +
data/processed/vyoma_sites_export_<state>.json (e.g. vyoma_export_mizoram.json)

Usage:
  python scripts/generate_vyoma_export.py                  # all states
  python scripts/generate_vyoma_export.py --state Mizoram  # state-filtered
"""

import argparse
import json
import os

import numpy as np
import pandas as pd

DATA_DIR = os.path.join('data', 'processed')
PRED_PATH = os.path.join(DATA_DIR, 'prediction_output.csv')
PLAN_PATH = os.path.join(DATA_DIR, 'relocation_plan.csv')
SITES_PATH = os.path.join(DATA_DIR, 'relocation_sites.json')

MODEL_VERSION = 'v1.1-susceptibility'  # susceptibility-based export


def _num(v, nd=4):
    """float -> rounded float; NaN/None -> None"""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), nd)


def _parse_top_factors(raw):
    """top_factors column is a JSON-encoded string; parse to a real list."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _slug(state):
    return state.strip().lower().replace(' ', '_')


def build_village_rows(pred_df, plan_df, state=None):
    """Build the village-level export list for `state` (or all villages).

    pred_df must be the FULL prediction frame (the green-target mapping below
    is cross-state: e.g. a Mizoram red village can be assigned to an Assam
    green site), so we only filter it for the rows we emit.
    """
    pred_all = pred_df
    if state:
        pred_df = pred_df[pred_df['State Name'] == state].copy()
        if len(pred_df) == 0:
            raise ValueError(f"No villages found for state '{state}'")

    # Relocation assignments: RED (and HIGH-priority ORANGE) village ->
    # assigned GREEN site. red_habitation_id was added to relocation_planner.py
    # output; older files fall back to the deterministic positional replay.
    if 'red_habitation_id' not in plan_df.columns:
        plan_df = plan_df.copy()
        # Replay planner selection/sort (see relocation_planner.plan_relocations)
        mask = (pred_all['predicted_risk_zone'] == 'RED') | (
            (pred_all['predicted_risk_zone'] == 'ORANGE') & (pred_all['priority_level'] == 'HIGH')
        )
        sources = pred_all[mask].sort_values('risk_score', ascending=False).reset_index(drop=True)
        plan_scores = pd.to_numeric(plan_df['red_risk_score'], errors='coerce').values
        src_scores = sources['risk_score'].round(6).values
        if len(plan_scores) != len(src_scores) or int((plan_scores != src_scores).sum()) > 0:
            raise ValueError(
                "relocation_plan.csv is stale or missing red_habitation_id. "
                "Re-run: python scripts/relocation_planner.py"
            )
        plan_df['red_habitation_id'] = plan_df['red_village_id'].map(
            dict(enumerate(sources['habitation_id'])))

    assigned = plan_df[plan_df['feasibility_flag'] == 'assigned'].copy()
    assigned['green_village_code'] = pd.to_numeric(assigned['green_village_id'],
                                                   errors='coerce')
    # green village code -> its habitation_id (the site_id used in sites export)
    # NOTE: built from the FULL frame — targets can be in another state.
    code_to_hid = (pred_all.drop_duplicates('Village Code')
                   .set_index('Village Code')['habitation_id'])
    assigned['recommended_site_id'] = assigned['green_village_code'].map(code_to_hid)

    site_by_red_hid = assigned.set_index('red_habitation_id')['recommended_site_id']
    site_by_red_hid = site_by_red_hid[site_by_red_hid.notna() & (site_by_red_hid != '')]
    # Relocation cost proxy per assignment: distance to the destination + how
    # well the site's capacity fits the village's population (from the plan).
    dist_by_red_hid = assigned.set_index('red_habitation_id')['distance_km']
    fit_by_red_hid = assigned.set_index('red_habitation_id')['capacity_fit']

    pred_by_hid = pred_df.set_index('habitation_id')
    red_assigned = assigned['red_habitation_id'].dropna()
    n_assigned = int(red_assigned.isin(pred_df['habitation_id']).sum())

    rows = []
    for _, r in pred_df.iterrows():
        hid = r['habitation_id']
        pop = r.get('Total Population of Village')
        rec_site = None
        rec_dist = None
        rec_fit = None
        if hid in site_by_red_hid.index:
            rec_site = site_by_red_hid[hid]
            rec_dist = dist_by_red_hid[hid]
            rec_fit = fit_by_red_hid[hid]

        rows.append({
            'village_id': hid,
            'name': r.get('Village Name'),
            'district': r.get('district', r.get('District Name')),
            'state': r.get('state', r.get('State Name')),
            'latitude': _num(r.get('latitude'), 6),
            'longitude': _num(r.get('longitude'), 6),
            'population': (int(pop) if pd.notna(pop) else None),
            'risk_score': _num(r.get('susceptibility_score'), 4),
            'risk_level': r.get('susceptibility_risk_zone'),
            'relocation_priority': r.get('relocation_timeline'),
            'vulnerability_multiplier': _num(r.get('vulnerability_score'), 4),
            'top_factors': _parse_top_factors(r.get('top_factors')),
            'low_confidence': bool(r.get('low_confidence', False)),
            'recommended_site_id': rec_site,
            'recommended_site_distance_km': _num(rec_dist, 1),
            'recommended_site_fit': (rec_fit if isinstance(rec_fit, str) else None),
            'prediction_timestamp': r.get('predicted_at'),
            'model_version': MODEL_VERSION,
        })

    print(f"  {len(rows):,} village rows for "
          f"{state if state else 'ALL STATES'} | {n_assigned:,} with a "
          f"recommended site")
    return rows


def build_site_rows(state=None, village_rows=None):
    """Filter relocation_sites.json to sites relevant to `state`:
    (a) GREEN sites located in the state, plus
    (b) sites in any state that received >=1 assignment from this state's
        red villages (so recommended_site_id always resolves)."""
    with open(SITES_PATH) as f:
        sites = pd.DataFrame(json.load(f))

    if not state:
        return sites.to_dict('records')

    in_state = sites['state'] == state
    if village_rows:
        assigned_ids = {v['recommended_site_id'] for v in village_rows
                        if v['recommended_site_id']}
        received_from_state = sites['site_id'].isin(assigned_ids)
        sites = sites[in_state | received_from_state]
    else:
        sites = sites[in_state]
    return sites.to_dict('records')


def main():
    parser = argparse.ArgumentParser(description='Generate VYOMA export')
    parser.add_argument('--state', type=str, default=None,
                        help='Filter to one state (e.g. Mizoram)')
    args = parser.parse_args()

    print("Loading prediction output + relocation plan...")
    pred_df = pd.read_csv(PRED_PATH, low_memory=False)
    plan_df = pd.read_csv(PLAN_PATH)
    print(f"  {len(pred_df):,} villages, {len(plan_df):,} plan rows")

    villages = build_village_rows(pred_df, plan_df, state=args.state)
    sites = build_site_rows(state=args.state, village_rows=villages)
    print(f"  {len(sites):,} site rows in sites export")

    # Validate recommended_site_id references a real site in the export
    if sites:
        known_site_ids = {s['site_id'] for s in sites}
        dangling = {v['recommended_site_id'] for v in villages
                    if v['recommended_site_id']          # skip nulls
                    and v['recommended_site_id'] not in known_site_ids}
        if dangling:
            print(f"  ⚠️  {len(dangling)} recommended_site_id values point "
                  f"outside the sites export")
        else:
            print(f"  ✅ every recommended_site_id resolves to a site row")

    if args.state:
        vpath = os.path.join(DATA_DIR, f'vyoma_export_{_slug(args.state)}.json')
        spath = os.path.join(DATA_DIR, f'vyoma_sites_export_{_slug(args.state)}.json')
    else:
        vpath = os.path.join(DATA_DIR, 'vyoma_export_all_states.json')
        spath = os.path.join(DATA_DIR, 'vyoma_sites_export_all_states.json')

    with open(vpath, 'w') as f:
        json.dump(villages, f)
    with open(spath, 'w') as f:
        json.dump(sites, f)
    print(f"\n  Saved: {vpath}")
    print(f"  Saved: {spath}")


if __name__ == '__main__':
    main()
