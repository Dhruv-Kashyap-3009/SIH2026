#!/usr/bin/env python3
"""Validate the VYOMA export against the agreed ingestion schema.

Checks: exact field set, value types (numbers not strings, booleans not
'true'/'false', ISO-8601 prediction_timestamp), no nulls in required fields,
recommended_site_id always resolves to a site row, zone/priority vocabularies
are correct, and site capacity bookkeeping is consistent.
"""
import json
import os
import sys
from datetime import datetime

DATA_DIR = os.path.join('data', 'processed')

VILLAGE_KEYS = [
    'village_id', 'name', 'district', 'state', 'latitude', 'longitude',
    'population', 'risk_score', 'risk_level', 'relocation_priority',
    'vulnerability_multiplier', 'top_factors', 'low_confidence',
    'recommended_site_id', 'prediction_timestamp', 'model_version',
]
SITE_KEYS = [
    'site_id', 'name', 'district', 'state', 'latitude', 'longitude',
    'suitability_score', 'total_capacity', 'occupied', 'available',
    'is_ideal', 'infrastructure',
]
INFRA_KEYS = ['water_supply', 'electricity', 'road_access', 'shelter',
              'medical_facility', 'sanitation']


def check(cond, msg, errors):
    if not cond:
        errors.append(msg)
        print(f"  ❌ {msg}")
    else:
        print(f"  ✅ {msg}")


def validate(vpath, spath):
    errors = []
    villages = json.load(open(vpath, encoding='utf-8'))
    sites = json.load(open(spath, encoding='utf-8'))
    print(f"\n== {os.path.basename(vpath)}: {len(villages):,} villages | "
          f"{os.path.basename(spath)}: {len(sites):,} sites ==")

    # ── Field sets ─────────────────────────────────────────────────────────
    bad_keys = [v for v in villages if set(v.keys()) != set(VILLAGE_KEYS)]
    check(f"All village rows have exactly the {len(VILLAGE_KEYS)} VYOMA fields",
          len(bad_keys) == 0, errors)
    bad_skeys = [s for s in sites if set(s.keys()) != set(SITE_KEYS)]
    check(f"All site rows have exactly the {len(SITE_KEYS)} fields",
          len(bad_skeys) == 0, errors)
    bad_infra = [s for s in sites
                 if set(s['infrastructure'].keys()) != set(INFRA_KEYS)]
    check("All sites expose all 6 infrastructure booleans",
          len(bad_infra) == 0, errors)

    # ── Village-row invariants ─────────────────────────────────────────────
    ids = [v['village_id'] for v in villages]
    check("village_id present + unique (no nulls)",
          all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids),
          errors)
    check("name/district/state non-null strings",
          all(isinstance(v['name'], str) and v['name'] and
              isinstance(v['district'], str) and v['district'] and
              isinstance(v['state'], str) and v['state'] for v in villages),
          errors)
    check("latitude/longitude numeric (not strings)",
          all(isinstance(v['latitude'], (int, float)) and
              isinstance(v['longitude'], (int, float)) for v in villages),
          errors)
    check("risk_score numeric in [0,1]",
          all(isinstance(v['risk_score'], (int, float))
              and 0 <= v['risk_score'] <= 1 for v in villages), errors)
    check("risk_level in {RED, ORANGE, GREEN}",
          all(v['risk_level'] in ('RED', 'ORANGE', 'GREEN') for v in villages),
          errors)
    check("relocation_priority in {IMMEDIATE, SHORT_TERM, MEDIUM_TERM, MONITOR}",
          all(v['relocation_priority'] in
              ('IMMEDIATE', 'SHORT_TERM', 'MEDIUM_TERM', 'MONITOR')
              for v in villages), errors)
    check("vulnerability_multiplier numeric in [0,1]",
          all(isinstance(v['vulnerability_multiplier'], (int, float))
              and 0 <= v['vulnerability_multiplier'] <= 1 for v in villages),
          errors)
    check("top_factors is a non-empty list of dicts with feature/value/impact",
          all(isinstance(v['top_factors'], list) and len(v['top_factors']) >= 3
              and all(isinstance(t, dict) and 'feature' in t and 'value' in t
                      and 'impact' in t for t in v['top_factors'])
              for v in villages), errors)
    check("low_confidence is a real boolean (not a string)",
          all(isinstance(v['low_confidence'], bool) for v in villages), errors)
    check("prediction_timestamp is ISO-8601 parseable",
          all(_iso_parseable(v['prediction_timestamp']) for v in villages),
          errors)
    check("model_version == v1.1-susceptibility",
          all(v['model_version'] == 'v1.1-susceptibility' for v in villages),
          errors)

    # ── recommended_site_id resolves ───────────────────────────────────────
    site_ids = {s['site_id'] for s in sites}
    dangling = {v['recommended_site_id'] for v in villages
                if v['recommended_site_id'] and v['recommended_site_id'] not in site_ids}
    check("every recommended_site_id resolves to a site row (null allowed)",
          len(dangling) == 0, errors)

    # ── Site-row invariants ────────────────────────────────────────────────
    check("site_id unique, non-null",
          all(isinstance(s['site_id'], str) and s['site_id'] for s in sites)
          and len({s['site_id'] for s in sites}) == len(sites), errors)
    check("suitability_score numeric (0-100)",
          all(isinstance(s['suitability_score'], (int, float))
              and 0 <= s['suitability_score'] <= 100 for s in sites), errors)
    check("capacity bookkeeping: total >= 0, available == max(0, total-occupied)",
          all(isinstance(s['total_capacity'], int) and s['total_capacity'] >= 0
              and isinstance(s['occupied'], int) and s['occupied'] >= 0
              and isinstance(s['available'], int)
              and s['available'] == max(0, s['total_capacity'] - s['occupied'])
              for s in sites), errors)
    check("infrastructure flags are real booleans",
          all(all(isinstance(v, bool) for v in s['infrastructure'].values())
              for s in sites), errors)

    print(f"\n{'='*60}")
    if errors:
        print(f"FAILED: {len(errors)} schema errors")
        return False
    print("PASSED: schema fully conforms to the VYOMA ingestion contract")
    return True


def _iso_parseable(s):
    if not isinstance(s, str) or not s:
        return False
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


if __name__ == '__main__':
    ok = True
    for pair in [('vyoma_export_mizoram.json', 'vyoma_sites_export_mizoram.json')]:
        ok = validate(os.path.join(DATA_DIR, pair[0]),
                      os.path.join(DATA_DIR, pair[1])) and ok
    sys.exit(0 if ok else 1)
