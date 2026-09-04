#!/usr/bin/env python3
"""
generate_frontend_static.py — Tier-3 static read bundles for the VYOMA UI.

The villages/sites datasets are static between model runs, so the frontend's
first page load should not query the database at all. This script turns the
canonical exports into two versioned JSON files served as plain static assets
(with immutable cache headers):

  data/processed/static/vyoma_compact_<model_version>-<run_tag>.json
      { "meta": { "version", "predicted_at", "village_count" },
        "villages": [ ...43,996 compact rows, sorted by risk_score desc... ] }
      — the 11 map/table fields only (no heavy top_factors payloads)

  data/processed/static/vyoma_sites_<model_version>-<run_tag>.json
      [ ...12,211 relocation site rows... ]  (same fields as the seed input)

  data/processed/static/latest.json          — tiny pointer for the frontend:
      { "version", "predicted_at", "compact": "<compact filename>",
        "sites": "<sites filename>" }

WHY the filename embeds a RUN TAG instead of a fixed STATIC_VERSION:

  The refresh button (backend/src/lib/refreshJob.ts) re-runs the model and
  calls this generator. If the output filename stayed the same across runs,
  browsers that cached the previous file with `Cache-Control: immutable`
  would keep serving the STALE bundle forever — an immutable cache entry
  cannot be invalidated by a header change; only a NEW URL forces a refetch.

  So the run tag is derived from the model run's own predicted_at timestamp:
  every refresh stamps a new predicted_at, hence a new filename, hence a new
  URL, hence every browser fetches the fresh bundle automatically. No manual
  version bookkeeping anywhere (frontend reads latest.json to find the file).

Run after generate_vyoma_export.py / generate_relocation_sites.py whenever the
model is re-run. The frontend is version-agnostic: it fetches latest.json
(served with Cache-Control: no-store) and then the current bundle by name.
"""
import datetime as _dt
import json
import os

PROCESSED_DIR = os.path.join("data", "processed")
STATIC_DIR = os.path.join(PROCESSED_DIR, "static")

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


def run_tag_from_predicted_at(predicted_at):
    """Filesystem-safe run tag from an ISO predicted_at, e.g.
    2026-09-04T08:33:24.527124+00:00 -> 20260904T083324Z.
    Falls back to the current UTC time if the timestamp is unparseable."""
    try:
        dt = _dt.datetime.fromisoformat(predicted_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        dt = dt.astimezone(_dt.timezone.utc)
    except (ValueError, TypeError, AttributeError):
        dt = _dt.datetime.now(_dt.timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


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

    # Filename uniqueness: the run tag encodes the model run time, so two
    # consecutive refreshes always produce different URLs. If a file with the
    # exact same tag somehow already exists (e.g. a same-second re-run or a
    # hand edit), bump the tag deterministically so we never overwrite a file
    # a browser may already have immutable-cached.
    tag = run_tag_from_predicted_at(predicted_at)
    suffix = 2
    while any(
        os.path.exists(os.path.join(STATIC_DIR, f"vyoma_{kind}_{version}-{tag}.json"))
        for kind in ("compact", "sites")
    ):
        tag = f"{run_tag_from_predicted_at(predicted_at)}-{suffix}"
        suffix += 1

    compact_name = f"vyoma_compact_{version}-{tag}.json"
    sites_name = f"vyoma_sites_{version}-{tag}.json"
    compact_path = os.path.join(STATIC_DIR, compact_name)
    sites_path = os.path.join(STATIC_DIR, sites_name)

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

    # latest.json — the frontend fetches this tiny pointer (never cached) to
    # discover the current bundle filenames. Schema:
    #   { "version", "predicted_at", "compact": "<file>", "sites": "<file>" }
    manifest = {
        "version": version,
        "predicted_at": predicted_at,
        "compact": compact_name,
        "sites": sites_name,
    }
    manifest_path = os.path.join(STATIC_DIR, "latest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, separators=(",", ":"))

    # Prune superseded bundles for THIS model version only — the new files are
    # already written and latest.json points at them, so anything else with the
    # same version prefix is dead weight from an earlier run (each pair is
    # ~15 MB). Files of OTHER model versions are left untouched.
    for name in os.listdir(STATIC_DIR):
        if not (name.startswith("vyoma_compact_") or name.startswith("vyoma_sites_")):
            continue
        if name in (compact_name, sites_name):
            continue
        # Match only files of the current model version: prefix up to the first
        # "-" after the kind is "vyoma_<kind>_<version>", so strip that prefix.
        prefix = f"vyoma_{name.split('_')[1]}_{version}-"
        if name.startswith(prefix):
            try:
                os.remove(os.path.join(STATIC_DIR, name))
            except OSError:
                pass  # in use / locked — harmless, next run retries

    def mb(path):
        return os.path.getsize(path) / 1024 / 1024

    print(f"model_version : {version}")
    print(f"run tag       : {tag}  (derived from predicted_at={predicted_at})")
    print(f"villages      : {len(compact)}  -> {compact_path}  ({mb(compact_path):.1f} MB)")
    print(f"sites         : {len(sites)}  -> {sites_path}  ({mb(sites_path):.1f} MB)")
    print(f"manifest      : {manifest_path}  ({os.path.getsize(manifest_path)} B)")


if __name__ == "__main__":
    main()
