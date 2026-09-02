"""Behavioral test: Verify README numbers match actual pipeline output."""
import pandas as pd
import sys

def test_readme_consistency():
    """Check every cross-referenced number in the README against actual data."""
    df = pd.read_csv('data/processed/prediction_output.csv', low_memory=False)
    total = len(df)
    errors = []

    # ── TEST 1: Headline zone counts ──
    pred = df['predicted_risk_zone'].value_counts()
    red = int(pred.get('RED', 0))
    orange = int(pred.get('ORANGE', 0))
    green = int(pred.get('GREEN', 0))

    # README claims
    readme_red, readme_orange, readme_green = 29687, 258, 14051

    print(f"Headline: RED={red} ORANGE={orange} GREEN={green} TOTAL={total}")
    if red != readme_red:
        errors.append(f"RED: actual={red} readme={readme_red}")
    if orange != readme_orange:
        errors.append(f"ORANGE: actual={orange} readme={readme_orange}")
    if green != readme_green:
        errors.append(f"GREEN: actual={green} readme={readme_green}")
    if red + orange + green != total:
        errors.append(f"RED+ORANGE+GREEN={red+orange+green} != TOTAL={total}")
    print(f"  ✅ Headline counts match" if not errors else f"  ❌ MISMATCHES: {errors}")

    # ── TEST 2: Per-state RED sums to headline ──
    state_red = df[df['predicted_risk_zone'] == 'RED'].groupby('State Name').size()
    state_orange = df[df['predicted_risk_zone'] == 'ORANGE'].groupby('State Name').size()
    state_green = df[df['predicted_risk_zone'] == 'GREEN'].groupby('State Name').size()
    state_total = df.groupby('State Name').size()

    state_errors = []
    for s in sorted(state_total.index):
        t = int(state_total[s])
        r = int(state_red.get(s, 0))
        o = int(state_orange.get(s, 0))
        g = int(state_green.get(s, 0))
        if r + o + g != t:
            state_errors.append(f"{s}: {r}+{o}+{g}={r+o+g} != {t}")
        print(f"  {s}: RED={r} ({100*r/t:.1f}%) ORANGE={o} GREEN={g}")

    if int(state_red.sum()) != red:
        state_errors.append(f"State RED sum {state_red.sum()} != headline {red}")
    if int(state_orange.sum()) != orange:
        state_errors.append(f"State ORANGE sum {state_orange.sum()} != headline {orange}")
    if int(state_green.sum()) != green:
        state_errors.append(f"State GREEN sum {state_green.sum()} != headline {green}")

    if state_errors:
        print(f"  ❌ STATE ERRORS: {state_errors}")
        errors.extend(state_errors)
    else:
        print(f"  ✅ Per-state sums match headline")

    # ── TEST 3: README per-state numbers match ──
    readme_states = {
        'Assam': (25854, 16314, 63.1),
        'Meghalaya': (6839, 4970, 72.7),
        'Arunachal Pradesh': (5589, 3397, 60.8),
        'Manipur': (2581, 2420, 93.8),
        'Nagaland': (1428, 1360, 95.2),
        'Tripura': (875, 422, 48.2),
        'Mizoram': (830, 804, 96.9),
    }
    for s, (rt, rr, rpct) in readme_states.items():
        actual_t = int(state_total.get(s, 0))
        actual_r = int(state_red.get(s, 0))
        actual_pct = round(100 * actual_r / actual_t, 1) if actual_t > 0 else 0
        if actual_t != rt:
            errors.append(f"{s} total: actual={actual_t} readme={rt}")
        if actual_r != rr:
            errors.append(f"{s} RED: actual={actual_r} readme={rr}")
        if actual_pct != rpct:
            errors.append(f"{s} RED%: actual={actual_pct} readme={rpct}")
    print(f"  ✅ Per-state numbers match README" if not [e for e in errors if "total" in e or "RED%" in e or "RED:" in e] else f"  ❌ Per-state mismatch")

    # ── TEST 4: Relocation priority counts ──
    if 'relocation_timeline' in df.columns:
        reloc = df['relocation_timeline'].value_counts()
        readme_reloc = {'IMMEDIATE': 24220, 'SHORT_TERM': 5467, 'MEDIUM_TERM': 157, 'MONITOR': 14152}
        reloc_errors = []
        for zone, count in readme_reloc.items():
            actual = int(reloc.get(zone, 0))
            if actual != count:
                reloc_errors.append(f"{zone}: actual={actual} readme={count}")
        if reloc_errors:
            errors.extend(reloc_errors)
            print(f"  ❌ Relocation: {reloc_errors}")
        else:
            print(f"  ✅ Relocation priority counts match")
    else:
        print(f"  ⚠️  relocation_timeline column missing")

    # ── TEST 5: Hazard decomposition counts ──
    if 'recommended_action' in df.columns:
        hazard = df['recommended_action'].value_counts()
        readme_hazard = {'RELOCATE': 13199, 'MITIGATE': 18833, 'MONITOR': 11964}
        hazard_errors = []
        for action, count in readme_hazard.items():
            actual = int(hazard.get(action, 0))
            if actual != count:
                hazard_errors.append(f"{action}: actual={actual} readme={count}")
        if hazard_errors:
            errors.extend(hazard_errors)
            print(f"  ❌ Hazard: {hazard_errors}")
        else:
            print(f"  ✅ Hazard decomposition counts match")
    else:
        print(f"  ⚠️  recommended_action column missing")

    # ── TEST 6: Carrying capacity candidates ──
    try:
        cap = pd.read_csv('data/processed/carrying_capacity.csv')
        cap_count = len(cap)
        if cap_count != 14109:
            errors.append(f"carrying_capacity.csv: actual={cap_count} readme=14109")
            print(f"  ❌ Carrying capacity: actual={cap_count} readme=14109")
        else:
            print(f"  ✅ Carrying capacity count matches")
    except Exception as e:
        print(f"  ⚠️  Could not read carrying_capacity.csv: {e}")

    # ── TEST 7: Zone definition is documented ──
    with open('README.md', encoding='utf-8') as f:
        readme_text = f.read()
    has_zone_def = 'predicted_risk_zone' in readme_text and 'zone definition' in readme_text.lower()
    if not has_zone_def:
        errors.append("Zone definition not documented in README")
        print(f"  ❌ Zone definition not documented")
    else:
        print(f"  ✅ Zone definition documented in README")

    # ── SUMMARY ──
    print(f"\n{'='*60}")
    if errors:
        print(f"FAILED: {len(errors)} errors found:")
        for e in errors:
            print(f"  ❌ {e}")
        return False
    else:
        print(f"PASSED: All 7 behavioral checks pass")
        return True

if __name__ == '__main__':
    success = test_readme_consistency()
    sys.exit(0 if success else 1)
