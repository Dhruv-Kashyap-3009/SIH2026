#!/usr/bin/env python3
"""
generate_frontend_static.py — Tier-3 static read bundles for the VYOMA UI.

The villages/sites datasets are static between model runs, so the frontend's
first page load should not query the database at all. This script turns the
canonical exports into two versioned JSON files served as plain static assets
(with immutable cache headers):

  data/processed/static/vyoma_compact_<model_version>.json
      { "meta": { "version", "predicted_at", "village_count" },
        "villages": [ ...43,996 compact rows, sorted by risk_score desc... ] }
      — the 11 map/table fields only (no heavy top_factors payloads)

  data/processed/static/vyoma_sites_<model_version>.json
      [ ...12,211 relocation site rows... ]  (same fields as the seed input)

Run after generate_vyoma_export.py / generate_relocation_sites.py whenever the
model version changes. The versioned filename + `immutable` Cache-Control means
each model version is downloaded by a browser at most once.

Note: frontend/src/lib/villagesStore.js pins STATIC_VERSION — keep it in sync
with the model_version these exports are stamped with.

BUILD_TAG disambiguates regenerations of the SAME model version (e.g. a
vocabulary/data fix): bump it whenever you regenerate, so browsers that have an
immutable-cached copy of the old bundle fetch the new one via a new URL.
"""
import json
import os

PROCESSED_DIR = os.path.join("data", "processed")
STATIC_DIR = os.path.join(PROCESSED_DIR, "static")

# Increment when regenerating bundles for the same model version (see docstring).
BUILD_TAG = "2"

VILLAGES_EXPORT = os.path.join(PROCESSED_DIR, "vyoma_export_all_states.json")
SITES_EXPORT = os.path.join(PROCESSED_DIR, "vyoma_sites_export_all_states.json")

# The 11 fields the map/table UI actually renders (matches the API's compact
# projection). Kept deliberately small so the bundle stays ~11 MB raw / ~1.5 MB
# gzipped instead of the ~40 MB of full records with per-village top_factors.
COMPACT_FIELDS = [
    "village_id",
    "name",
    "district",
    "state",
    "latitude",
    "longitude",
    "population",
    "risk_score",
    "risk_level",
    "relocation_priority",
    "low_confidence",
]

# The export keeps the model's original vocabulary, but the UI (and the seeded
# database — see backend/src/seed.ts) uses the translated one. The static bundle
# must match what the UI renders, so apply the same mapping here.
PRIORITY_TRANSLATION = {
    "SHORT_TERM": "SHORT-TERM",
    "MEDIUM_TERM": "MEDIUM-TERM",
    "MONITOR": "ROUTINE",
}


def translate_priority(value):
    return PRIORITY_TRANSLATION.get(value, value)



def main():
    with open(VILLAGES_EXPORT, encoding="utf-8") as fh:
        villages = json.load(fh)
    with open(SITES_EXPORT, encoding="utf-8") as fh:
        sites = json.load(fh)

    if not villages:
        raise SystemExit(f"Empty village export at {VILLAGES_EXPORT}")
    if not sites:
        raise SystemExit(f"Empty sites export at {SITES_EXPORT}")

    version = villages[0].get("model_version") or "unknown"
    predicted_at = max(
        (v.get("prediction_timestamp", "") for v in villages),
        default="",
    )

    # Sort like the API does (risk_score desc) so consumers that take the top
    # rows (e.g. the "critical habitations" table) see the same order, with a
    # stable tiebreak for reproducible builds.
    compact = []
    for v in sorted(
        villages,
        key=lambda v: (-(v.get("risk_score") or 0), v.get("village_id") or ""),
    ):
        row = {field: v.get(field) for field in COMPACT_FIELDS}
        row["relocation_priority"] = translate_priority(row.get("relocation_priority"))
        compact.append(row)

    os.makedirs(STATIC_DIR, exist_ok=True)
    compact_path = os.path.join(STATIC_DIR, f"vyoma_compact_{version}-{BUILD_TAG}.json")
    sites_path = os.path.join(STATIC_DIR, f"vyoma_sites_{version}-{BUILD_TAG}.json")

    with open(compact_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "meta": {
                    "version": version,
                    "predicted_at": predicted_at,
                    "village_count": len(compact),
                },
                "villages": compact,
            },
            fh,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    with open(sites_path, "w", encoding="utf-8") as fh:
        json.dump(sites, fh, ensure_ascii=False, separators=(",", ":"))

    def mb(path):
        return os.path.getsize(path) / 1024 / 1024

    print(f"model_version : {version}")
    print(f"build_tag     : {BUILD_TAG}")
    print(f"predicted_at  : {predicted_at}")
    print(f"villages      : {len(compact)}  -> {compact_path}  ({mb(compact_path):.1f} MB)")
    print(f"sites         : {len(sites)}  -> {sites_path}  ({mb(sites_path):.1f} MB)")


if __name__ == "__main__":
    main()
