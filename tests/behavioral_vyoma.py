#!/usr/bin/env python3
"""End-to-end behavioral verification of the VYOMA export pipeline.

Drives the REAL scripts (generate_relocation_sites.py, generate_vyoma_export.py)
and asserts the full lifecycle is consistent:
  prediction_output.csv  ->  relocation_plan.csv  ->  relocation_sites  ->  vyoma exports
Checks the easy-to-get-wrong steps: capacity bookkeeping, occupied sums from
the plan, recommended_site_id traceability back to plan rows, canonical
(susceptibility) field mapping, zone purity, and idempotent re-runs.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

DATA = os.path.join('data', 'processed')
PASS = 0
FAIL = 0
ERRORS = []


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail}")


def run_script(args):
    """Run a pipeline script and capture stdout."""
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


def main():
    print("=" * 70)
    print("Behavioral test: VYOMA export pipeline (end-to-end)")
    print("=" * 70)

    pred = pd.read_csv(os.path.join(DATA, 'prediction_output.csv'), low_memory=False)
    plan = pd.read_csv(os.path.join(DATA, 'relocation_plan.csv'))
    cc = pd.read_csv(os.path.join(DATA, 'carrying_capacity.csv'))
    pred['Village Code'] = pred['Village Code'].astype(int)
    cc['Village Code'] = cc['village_id'].astype(int)

    # ── 1. Idempotent re-runs of both scripts ───────────────────────────────
    print("\n[1] Re-running scripts (idempotency)")
    code1, out1 = run_script(['scripts/generate_relocation_sites.py'])
    check("generate_relocation_sites.py exits 0", code1 == 0, out1[-800:])
    code2, out2 = run_script(['scripts/generate_vyoma_export.py', '--state', 'Mizoram'])
    check("generate_vyoma_export.py (Mizoram) exits 0", code2 == 0, out2[-800:])
    check("sites script reports 10,603 rows / 406 ideal",
          '10,603 rows, is_ideal (>= 0.8): 406' in out1, out1[-500:])
    check("no dangling warnings in either run",
          '⚠️' not in out1 and '⚠️' not in out2, out1[-300:] + out2[-300:])

    # ── 2. Village export contract + canonical mapping ──────────────────────
    print("\n[2] Village export contract (canonical = susceptibility)")
    villages = json.load(open(os.path.join(DATA, 'vyoma_export_mizoram.json'),
                              encoding='utf-8'))
    check("830 Mizoram villages exported", len(villages) == 830, len(villages))
    vkeys = set(villages[0].keys())
    expected_keys = {'village_id', 'name', 'district', 'state', 'latitude',
                     'longitude', 'population', 'risk_score', 'risk_level',
                     'relocation_priority', 'vulnerability_multiplier',
                     'top_factors', 'low_confidence', 'recommended_site_id',
                     'recommended_site_distance_km', 'recommended_site_fit',
                     'prediction_timestamp', 'model_version'}
    check("exact 18 canonical fields (16 + relocation distance/fit extensions)",
          vkeys == expected_keys, str(vkeys ^ expected_keys))

    vdf = pd.DataFrame(villages)
    hid2 = pred.set_index('habitation_id')
    check("village_id unique", vdf['village_id'].is_unique)
    check("risk_score equals susceptibility_score (canonical)",
          np.allclose(vdf['risk_score'], vdf['village_id'].map(
              lambda h: hid2.loc[h, 'susceptibility_score']), atol=1e-4))
    check("risk_level equals susceptibility_risk_zone (canonical)",
          (vdf['risk_level'] == vdf['village_id'].map(
              lambda h: hid2.loc[h, 'susceptibility_risk_zone'])).all())
    check("relocation_priority equals relocation_timeline",
          (vdf['relocation_priority'] == vdf['village_id'].map(
              lambda h: hid2.loc[h, 'relocation_timeline'])).all())
    check("vulnerability_multiplier equals vulnerability_score",
          np.allclose(vdf['vulnerability_multiplier'], vdf['village_id'].map(
              lambda h: hid2.loc[h, 'vulnerability_score']), atol=1e-4))
    check("Mizoram zone mix = 613 RED / 216 ORANGE / 1 GREEN",
          vdf['risk_level'].value_counts().to_dict() ==
          {'RED': 613, 'ORANGE': 216, 'GREEN': 1},
          str(vdf['risk_level'].value_counts().to_dict()))
    check("types: numbers not strings, booleans not strings, ISO timestamps",
          all(isinstance(x, (int, float)) for x in vdf['risk_score']) and
          all(isinstance(x, bool) for x in vdf['low_confidence']) and
          all(isinstance(x, str) and x.startswith('20') for x in
              vdf['prediction_timestamp']))
    check("no nulls in required fields (id/name/zone/priority)",
          vdf[['village_id', 'name', 'risk_level', 'relocation_priority']]
          .notna().all().all())

    # ── 3. Sites export contract + capacity bookkeeping ─────────────────────
    print("\n[3] Sites export contract + capacity bookkeeping")
    sites = json.load(open(os.path.join(DATA, 'vyoma_sites_export_mizoram.json'),
                           encoding='utf-8'))
    check("Mizoram sites export non-empty", len(sites) >= 26, len(sites))
    sites_reg = json.load(open(os.path.join(DATA, 'relocation_sites.json'),
                               encoding='utf-8'))
    check("full site register = 10,603 rows (canonical-GREEN only)",
          len(sites_reg) == 10603, len(sites_reg))
    n_ideal = sum(1 for s in sites_reg if s['is_ideal'])
    check("is_ideal == carrying_capacity_score >= 0.8 (406)",
          n_ideal == 406, n_ideal)

    reg = pd.DataFrame(sites_reg)
    # Canonical-safety invariant: NO destination may be RED/ORANGE under the
    # susceptibility model — the same model the export reports as risk_level.
    reg_sus_zone = reg['site_id'].map(lambda h: hid2.loc[h, 'susceptibility_risk_zone']
                                      if h in hid2.index else 'UNKNOWN')
    check("0 register sites are canonical RED/ORANGE (all GREEN)",
          (reg_sus_zone == 'GREEN').all(),
          reg_sus_zone.value_counts().to_dict())
    site_code = reg['site_id'].map(lambda h: hid2.loc[h, 'Village Code']
                                   if h in hid2.index else np.nan)
    cc_by_code = cc.set_index('Village Code')
    samp = reg.sample(min(400, len(reg)), random_state=7)
    ok_suit = ok_cap = True
    for _, s in samp.iterrows():
        c = site_code[s.name]
        if np.isnan(c):
            ok_suit = False
            continue
        row = cc_by_code.loc[c]
        if abs(s['suitability_score'] - round(float(row['carrying_capacity_score']) * 100, 2)) > 0.01:
            ok_suit = False
        if s['total_capacity'] != int(row['estimated_absorbable_population']):
            ok_cap = False
    check("suitability_score == carrying_capacity_score × 100 (sample of 400)",
          ok_suit)
    check("total_capacity == estimated_absorbable_population (sample of 400)",
          ok_cap)
    check("available == max(0, total_capacity − occupied) on ALL sites",
          ((reg['available'].values) == np.maximum(
              0, reg['total_capacity'].values - reg['occupied'].values)).all())
    check("infrastructure flags are real booleans on ALL sites",
          all(all(isinstance(v, bool) for v in s['infrastructure'].values())
              for s in sites_reg))

    # ── 4. occupied matches relocation_plan demand (site-level) ─────────────
    print("\n[4] occupied == sum of assigned red-village populations")
    assigned = plan[plan['feasibility_flag'] == 'assigned'].copy()
    assigned['green_village_code'] = pd.to_numeric(assigned['green_village_id'],
                                                   errors='coerce')
    code_to_hid = pred.drop_duplicates('Village Code').set_index('Village Code')['habitation_id']
    assigned['site_id'] = assigned['green_village_code'].map(code_to_hid)
    expected_occ = assigned.groupby('site_id')['red_population'].sum()
    # Compare across every site that has a non-zero occupancy in the register
    occ_sites = reg[reg['occupied'] > 0]
    mism = 0
    for _, s in occ_sites.iterrows():
        exp = int(expected_occ.get(s['site_id'], 0))
        if s['occupied'] != exp:
            mism += 1
            if mism <= 3:
                print(f"    mismatch: {s['site_id']} got={s['occupied']} exp={exp}")
    check("occupied equals plan demand on all occupied sites "
          f"({len(occ_sites)} sites, {mism} mismatches)", mism == 0)

    # ── 5. recommended_site_id traces back to the actual plan row ───────────
    print("\n[5] recommended_site_id ↔ relocation_plan traceability")
    hid_to_plan_site = assigned.set_index('red_habitation_id')['site_id']
    rec = vdf[vdf['recommended_site_id'].notna()]
    check("47 Mizoram villages have a recommended site", len(rec) == 47, len(rec))
    mism = sum(1 for _, r in rec.iterrows()
               if hid_to_plan_site.get(r['village_id']) != r['recommended_site_id'])
    check("every village recommended_site_id equals its plan row's target "
          f"({mism} mismatches)", mism == 0)
    # Relocation cost fields ride along with the assignment: distance + fit
    # must mirror the plan rows for the same 66 assigned villages.
    dist_ok = np.allclose(
        vdf.loc[rec.index, 'recommended_site_distance_km'],
        rec['village_id'].map(lambda h: plan.set_index('red_habitation_id')
                              .loc[h, 'distance_km']), atol=0.15)
    check("recommended_site_distance_km mirrors plan distance on assigned rows",
          dist_ok)
    fit_ok = (vdf.loc[rec.index, 'recommended_site_fit'] ==
              rec['village_id'].map(lambda h: plan.set_index('red_habitation_id')
                                    .loc[h, 'capacity_fit'])).all()
    check("recommended_site_fit mirrors plan capacity_fit on assigned rows",
          fit_ok)
    no_rec = vdf[vdf['recommended_site_id'].isna()]
    check("distance/fit null on every village without an assignment",
          no_rec['recommended_site_distance_km'].isna().all()
          and no_rec['recommended_site_fit'].isna().all())
    site_id_set = set(sites_reg_ids := [s['site_id'] for s in sites_reg])
    dangling = rec[~rec['recommended_site_id'].isin(site_id_set)]
    check("all recommended_site_id exist in the full site register",
          len(dangling) == 0, len(dangling))
    # In the Mizoram sites file specifically
    miz_site_ids = {s['site_id'] for s in sites}
    dang2 = rec[~rec['recommended_site_id'].isin(miz_site_ids)]
    check("all Mizoram recommended_site_id exist in the Mizoram sites export",
          len(dang2) == 0, len(dang2))

    # ── 6. relocation_plan internal invariants ──────────────────────────────
    print("\n[6] relocation_plan invariants")
    mask = (pred['predicted_risk_zone'] == 'RED') | (
        (pred['predicted_risk_zone'] == 'ORANGE') & (pred['priority_level'] == 'HIGH'))
    check(f"plan rows ({len(plan)}) == current RED + HIGH-ORANGE sources "
          f"({mask.sum()})", len(plan) == int(mask.sum()))
    check("every red_habitation_id exists in prediction_output",
          plan['red_habitation_id'].isin(pred['habitation_id']).all())
    check("distances within 50 km on assigned rows",
          (plan.loc[plan['feasibility_flag'] == 'assigned', 'distance_km'] <= 50.001)
          .all())
    check("feasibility_flag vocabulary correct",
          set(plan['feasibility_flag']) ==
          {'assigned', 'no_feasible_relocation_site_within_range'})
    green_ids = pd.to_numeric(plan.loc[plan['feasibility_flag'] == 'assigned',
                                       'green_village_id'], errors='coerce')
    check("all assigned green targets are real capacity candidates",
          green_ids.isin(cc['Village Code']).all())
    assigned_frac = (plan['feasibility_flag'] == 'assigned').mean()
    check("8,431/29,105 assigned (29.0%)",
          abs(assigned_frac - 0.2897) < 0.002, assigned_frac)
    # Canonical-safety: every assigned target must itself be canonical GREEN
    tgt_zone = (cc.merge(pred[['Village Code', 'susceptibility_risk_zone']],
                         on='Village Code', how='left')
                .set_index('Village Code')['susceptibility_risk_zone'])
    tgt_codes = set(pd.to_numeric(
        plan.loc[plan['feasibility_flag'] == 'assigned', 'green_village_id'],
        errors='coerce').dropna().astype(int))
    bad_tgt = [c for c in tgt_codes if tgt_zone.get(c) != 'GREEN']
    check("0 assigned destinations are canonical RED/ORANGE",
          len(bad_tgt) == 0, len(bad_tgt))

    # ── 7. All-state export path ────────────────────────────────────────────
    print("\n[7] All-state export path")
    code3, out3 = run_script(['scripts/generate_vyoma_export.py'])
    check("generate_vyoma_export.py (all states) exits 0", code3 == 0, out3[-500:])
    allv = json.load(open(os.path.join(DATA, 'vyoma_export_all_states.json'),
                           encoding='utf-8'))
    check("43,996 villages in full export", len(allv) == 43996, len(allv))
    all_ids = [x['village_id'] for x in allv]
    check("village_id unique in full export", len(set(all_ids)) == 43996)
    check("full export zones sum to susceptibility totals "
          "(RED 20,129 / ORANGE 12,496 / GREEN 11,371)",
          {k: sum(1 for x in allv if x['risk_level'] == k)
           for k in ('RED', 'ORANGE', 'GREEN')} ==
          {'RED': 20129, 'ORANGE': 12496, 'GREEN': 11371})

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAIL:
        for e in ERRORS:
            print(f"  ❌ {e}")
        return 1
    print("ALL BEHAVIORAL CHECKS PASSED")
    return 0


if __name__ == '__main__':
    sys.exit(main())
