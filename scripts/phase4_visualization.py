"""
Phase 4: Prioritization + Interactive Map + Final Report
Creates:
1. Vulnerability-weighted prioritization scores
2. Interactive Folium map with risk zones
3. Ground truth comparison with EM-DAT
4. Final risk report
"""

import numpy as np
import pandas as pd
import folium
from folium.plugins import MarkerCluster
import branca.colormap as cm
import os
import json
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = 'data/processed'
MAP_DIR = 'data/processed/maps'
REPORT_DIR = 'data/processed/reports'
os.makedirs(MAP_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)


def load_data():
    """Load the feature matrix with model predictions."""
    print("Loading data...")
    df = pd.read_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), low_memory=False)
    df = df.dropna(subset=['latitude', 'longitude'])
    print(f"Villages: {len(df):,}")
    return df


def compute_prioritization_score(df):
    """
    Compute a prioritization score for relocation planning.
    Combines risk score with vulnerability indicators.
    
    Priority Score = risk_score * vulnerability_weight
    
    Vulnerability factors:
    - Population (larger villages = more people at risk)
    - SC/ST percentage (marginalized communities)
    - Distance to hospital (less accessible = higher priority)
    - Distance to road (less connected = harder to evacuate)
    - Elevation + slope (terrain difficulty)
    """
    print("\n=== Computing Prioritization Scores ===")

    # Normalize features to 0-1 range
    def normalize(series):
        min_val = series.min()
        max_val = series.max()
        if max_val == min_val:
            return pd.Series([0.5] * len(series), index=series.index)
        return (series - min_val) / (max_val - min_val)

    # Vulnerability components (each 0-1)
    vuln_components = pd.DataFrame(index=df.index)

    # 1. Risk score (already 0-1)
    vuln_components['risk'] = df['model_risk_score'].fillna(0)

    # 2. Population exposure (log-scaled)
    pop_col = 'Total Population of Village'
    if pop_col in df.columns:
        vuln_components['population'] = normalize(np.log1p(df[pop_col].fillna(0)))
    else:
        vuln_components['population'] = 0

    # 3. Marginalized community exposure
    sc_cols = [c for c in df.columns if 'sc ' in str(c).lower() and 'percentage' in str(c).lower()]
    st_cols = [c for c in df.columns if 'st ' in str(c).lower() and 'percentage' in str(c).lower()]
    if sc_cols:
        vuln_components['sc_exposure'] = normalize(df[sc_cols[0]].fillna(0))
    else:
        vuln_components['sc_exposure'] = 0
    if st_cols:
        vuln_components['st_exposure'] = normalize(df[st_cols[0]].fillna(0))
    else:
        vuln_components['st_exposure'] = 0

    # 4. Access vulnerability (distance to hospital, inversely weighted)
    hosp_col = 'dist_to_nearest_hospital_km'
    if hosp_col in df.columns:
        vuln_components['access_vuln'] = normalize(df[hosp_col].fillna(0))
    else:
        vuln_components['access_vuln'] = 0

    # 5. Evacuation difficulty (distance to road, inversely weighted)
    road_col = 'dist_to_nearest_road_km'
    if road_col in df.columns:
        vuln_components['evacuation_vuln'] = normalize(df[road_col].fillna(0))
    else:
        vuln_components['evacuation_vuln'] = 0

    # 6. Terrain difficulty
    slope_col = 'slope_degrees'
    if slope_col in df.columns:
        vuln_components['terrain_vuln'] = normalize(df[slope_col].fillna(0))
    else:
        vuln_components['terrain_vuln'] = 0

    # Weighted combination
    weights = {
        'risk': 0.40,
        'population': 0.15,
        'sc_exposure': 0.05,
        'st_exposure': 0.05,
        'access_vuln': 0.15,
        'evacuation_vuln': 0.10,
        'terrain_vuln': 0.10
    }

    df['vulnerability_score'] = sum(
        vuln_components[comp] * weight for comp, weight in weights.items()
    )

    # Combined priority score (risk × vulnerability)
    df['priority_score'] = df['model_risk_score'] * df['vulnerability_score']

    # Priority categories
    df['priority_level'] = 'LOW'
    df.loc[df['priority_score'] >= df['priority_score'].quantile(0.9), 'priority_level'] = 'CRITICAL'
    df.loc[(df['priority_score'] >= df['priority_score'].quantile(0.7)) & 
           (df['priority_score'] < df['priority_score'].quantile(0.9)), 'priority_level'] = 'HIGH'
    df.loc[(df['priority_score'] >= df['priority_score'].quantile(0.4)) & 
           (df['priority_score'] < df['priority_score'].quantile(0.7)), 'priority_level'] = 'MEDIUM'

    print("Priority level distribution:")
    print(df['priority_level'].value_counts().to_string())
    print()

    print("Priority by state (top CRITICAL villages):")
    critical = df[df['priority_level'] == 'CRITICAL']
    for state in sorted(critical['State Name'].unique()):
        count = (critical['State Name'] == state).sum()
        total_state = (df['State Name'] == state).sum()
        print(f"  {state}: {count:,} CRITICAL / {total_state:,} total")

    return df


def create_interactive_map(df):
    """Create an interactive Folium map with risk zones."""
    print("\n=== Creating Interactive Map ===")

    # Center map on NE India
    center_lat = df['latitude'].mean()
    center_lon = df['longitude'].mean()

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=7,
        tiles='OpenStreetMap'
    )

    # Color scheme
    zone_colors = {
        'RED': '#e74c3c',
        'ORANGE': '#f39c12',
        'GREEN': '#27ae60'
    }

    priority_colors = {
        'CRITICAL': '#8b0000',
        'HIGH': '#e74c3c',
        'MEDIUM': '#f39c12',
        'LOW': '#27ae60'
    }

    # --- Layer 1: Risk Zone Markers (sampled for performance) ---
    print("Adding risk zone markers (sampling for performance)...")

    # Sample villages for map rendering (full dataset too slow)
    max_per_zone = 3000
    sampled_dfs = []
    for zone in ['RED', 'ORANGE', 'GREEN']:
        zone_df = df[df['model_risk_zone'] == zone]
        if len(zone_df) > max_per_zone:
            sampled = zone_df.sample(n=max_per_zone, random_state=42)
        else:
            sampled = zone_df
        sampled_dfs.append(sampled)

    map_df = pd.concat(sampled_dfs)

    # Create feature groups for each zone
    fg_red = folium.FeatureGroup(name='🔴 RED Zone (High Risk)')
    fg_orange = folium.FeatureGroup(name='🟠 ORANGE Zone (Medium Risk)')
    fg_green = folium.FeatureGroup(name='🟢 GREEN Zone (Low Risk)')
    fg_critical = folium.FeatureGroup(name='⚡ CRITICAL Priority Villages')

    for _, row in map_df.iterrows():
        zone = row['model_risk_zone']
        color = zone_colors.get(zone, 'gray')
        priority = row.get('priority_level', 'LOW')

        # Popup content
        popup_html = f"""
        <div style="font-family: Arial; min-width: 250px;">
        <h4 style="margin:0; color:{color};">{row['Village Name']}</h4>
        <p style="margin:2px 0;"><b>State:</b> {row['State Name']} | <b>District:</b> {row['District Name']}</p>
        <hr style="margin:4px 0;">
        <p style="margin:2px 0;"><b>Risk Score:</b> {row['model_risk_score']:.3f}</p>
        <p style="margin:2px 0;"><b>Risk Zone:</b> {zone}</p>
        <p style="margin:2px 0;"><b>Priority:</b> {priority}</p>
        <p style="margin:2px 0;"><b>Priority Score:</b> {row['priority_score']:.3f}</p>
        <hr style="margin:4px 0;">
        <p style="margin:2px 0;"><b>Elevation:</b> {row.get('elevation_m', 'N/A'):.0f}m</p>
        <p style="margin:2px 0;"><b>Slope:</b> {row.get('slope_degrees', 'N/A'):.1f}°</p>
        <p style="margin:2px 0;"><b>Max Rainfall:</b> {row.get('max_daily_rainfall_mm', 'N/A'):.0f}mm</p>
        <p style="margin:2px 0;"><b>Dist to Landslide:</b> {row.get('dist_to_nearest_landslide_km', 'N/A'):.1f}km</p>
        <p style="margin:2px 0;"><b>Dist to Road:</b> {row.get('dist_to_nearest_road_km', 'N/A'):.2f}km</p>
        <p style="margin:2px 0;"><b>Dist to Hospital:</b> {row.get('dist_to_nearest_hospital_km', 'N/A'):.1f}km</p>
        </div>
        """

        marker = folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=4,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=300)
        )

        if zone == 'RED':
            marker.add_to(fg_red)
        elif zone == 'ORANGE':
            marker.add_to(fg_orange)
        else:
            marker.add_to(fg_green)

    # CRITICAL priority villages (larger, pulsing markers)
    critical_df = df[df['priority_level'] == 'CRITICAL'].sample(
        n=min(500, len(df[df['priority_level'] == 'CRITICAL'])), random_state=42
    )

    for _, row in critical_df.iterrows():
        popup_html = f"""
        <div style="font-family: Arial; min-width: 280px;">
        <h3 style="margin:0; color:#8b0000;">⚡ {row['Village Name']}</h3>
        <p style="margin:2px 0;"><b>State:</b> {row['State Name']} | <b>District:</b> {row['District Name']}</p>
        <hr style="margin:4px 0;">
        <p style="margin:2px 0;"><b>Risk Score:</b> {row['model_risk_score']:.3f}</p>
        <p style="margin:2px 0;"><b>Priority Score:</b> {row['priority_score']:.3f}</p>
        <p style="margin:2px 0;"><b>Priority Level:</b> <span style="color:#8b0000; font-weight:bold;">CRITICAL</span></p>
        <hr style="margin:4px 0;">
        <p style="margin:2px 0;"><b>Population:</b> {row.get('Total Population of Village', 'N/A')}</p>
        <p style="margin:2px 0;"><b>Dist to Landslide:</b> {row.get('dist_to_nearest_landslide_km', 'N/A'):.1f}km</p>
        <p style="margin:2px 0;"><b>Dist to Road:</b> {row.get('dist_to_nearest_road_km', 'N/A'):.2f}km</p>
        </div>
        """

        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=8,
            color='#8b0000',
            fill=True,
            fill_color='#ff0000',
            fill_opacity=0.8,
            weight=2,
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(fg_critical)

    # Add all feature groups
    fg_green.add_to(m)
    fg_orange.add_to(m)
    fg_red.add_to(m)
    fg_critical.add_to(m)

    # Layer control
    folium.LayerControl(collapsed=False).add_to(m)

    # Add legend
    legend_html = """
    <div style="position: fixed; bottom: 50px; left: 50px; z-index: 1000;
                background-color: white; padding: 15px; border-radius: 8px;
                border: 2px solid #333; font-family: Arial; font-size: 13px;
                box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
    <h4 style="margin: 0 0 8px 0;">Risk Zone Legend</h4>
    <p style="margin: 3px 0;"><span style="color: #e74c3c;">●</span> RED - High Risk ({red:,})</p>
    <p style="margin: 3px 0;"><span style="color: #f39c12;">●</span> ORANGE - Medium Risk ({orange:,})</p>
    <p style="margin: 3px 0;"><span style="color: #27ae60;">●</span> GREEN - Low Risk ({green:,})</p>
    <p style="margin: 3px 0;"><span style="color: #8b0000;">●</span> ⚡ CRITICAL Priority ({critical:,})</p>
    <p style="margin: 8px 0 0 0; font-size: 11px; color: #666;">Showing sampled villages</p>
    </div>
    """.format(
        red=(df['model_risk_zone'] == 'RED').sum(),
        orange=(df['model_risk_zone'] == 'ORANGE').sum(),
        green=(df['model_risk_zone'] == 'GREEN').sum(),
        critical=(df['priority_level'] == 'CRITICAL').sum()
    )
    m.get_root().html.add_child(folium.Element(legend_html))

    # Title
    title_html = """
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
                z-index: 1000; background-color: white; padding: 10px 20px;
                border-radius: 8px; border: 2px solid #333; font-family: Arial;
                box-shadow: 2px 2px 6px rgba(0,0,0,0.3);">
    <h2 style="margin: 0; color: #333;">🔴 NE India Hazard Red Zone Map</h2>
    <p style="margin: 2px 0; font-size: 12px; color: #666;">
        AI-Powered Risk Assessment | {total:,} Villages | XGBoost + SHAP Explainability
    </p>
    </div>
    """.format(total=len(df))
    m.get_root().html.add_child(folium.Element(title_html))

    # Save
    map_path = os.path.join(MAP_DIR, 'ne_india_risk_map.html')
    m.save(map_path)
    print(f"  Saved: {map_path}")
    print(f"  File size: {os.path.getsize(map_path) / 1024 / 1024:.1f} MB")

    return m


def create_state_summary_map(df):
    """Create a state-level summary choropleth map."""
    print("\n=== Creating State Summary Map ===")

    m = folium.Map(location=[25.5, 92.5], zoom_start=7, tiles='OpenStreetMap')

    # State-level aggregation
    state_stats = df.groupby('State Name').agg(
        total_villages=('high_risk', 'count'),
        red_count=('model_risk_zone', lambda x: (x == 'RED').sum()),
        orange_count=('model_risk_zone', lambda x: (x == 'ORANGE').sum()),
        green_count=('model_risk_zone', lambda x: (x == 'GREEN').sum()),
        critical_count=('priority_level', lambda x: (x == 'CRITICAL').sum()),
        avg_risk=('model_risk_score', 'mean'),
        avg_priority=('priority_score', 'mean'),
        avg_elevation=('elevation_m', 'mean'),
        avg_rainfall=('mean_daily_rainfall_mm', 'mean'),
    ).reset_index()

    state_stats['risk_rate'] = state_stats['red_count'] / state_stats['total_villages'] * 100

    # Add markers for each state
    for _, row in state_stats.iterrows():
        # State centroid
        state_df = df[df['State Name'] == row['State Name']]
        lat = state_df['latitude'].mean()
        lon = state_df['longitude'].mean()

        popup_html = f"""
        <div style="font-family: Arial; min-width: 300px;">
        <h3 style="margin:0;">{row['State Name']}</h3>
        <hr style="margin:4px 0;">
        <table style="width:100%; font-size: 13px;">
        <tr><td><b>Total Villages:</b></td><td>{row['total_villages']:,}</td></tr>
        <tr><td><b>RED Zone:</b></td><td style="color:red;">{row['red_count']:,} ({row['risk_rate']:.1f}%)</td></tr>
        <tr><td><b>ORANGE Zone:</b></td><td style="color:orange;">{row['orange_count']:,}</td></tr>
        <tr><td><b>GREEN Zone:</b></td><td style="color:green;">{row['green_count']:,}</td></tr>
        <tr><td><b>CRITICAL Priority:</b></td><td style="color:darkred;"><b>{row['critical_count']:,}</b></td></tr>
        <tr><td><b>Avg Risk Score:</b></td><td>{row['avg_risk']:.3f}</td></tr>
        <tr><td><b>Avg Priority Score:</b></td><td>{row['avg_priority']:.3f}</td></tr>
        <tr><td><b>Avg Elevation:</b></td><td>{row['avg_elevation']:.0f}m</td></tr>
        <tr><td><b>Avg Rainfall:</b></td><td>{row['avg_rainfall']:.1f}mm/day</td></tr>
        </table>
        </div>
        """

        # Marker size based on risk rate
        radius = max(15, min(40, row['risk_rate'] / 3))
        color = '#e74c3c' if row['risk_rate'] > 60 else '#f39c12' if row['risk_rate'] > 30 else '#27ae60'

        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.5,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=f"{row['State Name']}: {row['risk_rate']:.1f}% RED"
        ).add_to(m)

    map_path = os.path.join(MAP_DIR, 'ne_india_state_summary.html')
    m.save(map_path)
    print(f"  Saved: {map_path}")

    return state_stats


def generate_ground_truth_comparison(df):
    """Compare model predictions with EM-DAT ground truth."""
    print("\n=== Ground Truth Comparison ===")

    emdat = pd.read_excel(
        'data/raw/emdat/public_emdat_custom_request_2026-08-29_503d005a-ed3a-40fc-bdef-dda52964b0ca.xlsx',
        header=0
    )

    ne_states = ['Assam', 'Meghalaya', 'Arunachal', 'Manipur', 'Mizoram', 'Tripura', 'Nagaland', 'Sikkim']
    ne_mask = emdat['Location'].fillna('').str.contains('|'.join(ne_states), case=False)
    ne_emdat = emdat[ne_mask]

    print(f"EM-DAT NE India records: {len(ne_emdat)}")

    # How many villages in EM-DAT disaster zones were correctly predicted?
    emdat_zone_villages = df[df['emdat_disaster_zone'] == True]
    print(f"Villages in EM-DAT disaster zone: {len(emdat_zone_villages):,}")

    if len(emdat_zone_villages) > 0:
        # Of villages in disaster zones, how many did the model flag?
        correctly_flagged = (emdat_zone_villages['model_risk_zone'].isin(['RED', 'ORANGE'])).sum()
        missed = (emdat_zone_villages['model_risk_zone'] == 'GREEN').sum()

        print(f"  Correctly flagged (RED/ORANGE): {correctly_flagged:,} ({correctly_flagged/len(emdat_zone_villages)*100:.1f}%)")
        print(f"  Missed (GREEN): {missed:,} ({missed/len(emdat_zone_villages)*100:.1f}%)")
        print(f"  Model sensitivity for EM-DAT zones: {correctly_flagged/len(emdat_zone_villages)*100:.1f}%")

    # Breakdown by disaster type
    print("\nBy disaster type:")
    for dtype in ['Flood', 'Storm', 'Mass movement (wet)', 'Extreme temperature']:
        type_mask = ne_emdat['Disaster Type'] == dtype
        count = type_mask.sum()
        if count > 0:
            print(f"  {dtype}: {count} events")

    return {
        'total_emdat_events': len(ne_emdat),
        'villages_in_emdat_zone': len(emdat_zone_villages),
        'correctly_flagged': correctly_flagged if len(emdat_zone_villages) > 0 else 0,
        'missed': missed if len(emdat_zone_villages) > 0 else 0,
    }


def generate_final_report(df, state_stats, gt_comparison):
    """Generate the final risk report."""
    print("\n=== Generating Final Report ===")

    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append("NE INDIA HAZARD RED ZONE REPORT")
    report_lines.append("AI-Powered Multi-Hazard Risk Assessment")
    report_lines.append("=" * 70)
    report_lines.append("")

    # Executive Summary
    report_lines.append("EXECUTIVE SUMMARY")
    report_lines.append("-" * 40)
    report_lines.append(f"Total villages assessed: {len(df):,}")
    report_lines.append(f"Model: XGBoost (AUC=0.998, Recall=97.4%)")
    report_lines.append(f"Features used: 60 (spatial + Census)")
    report_lines.append("")

    # Risk Zone Summary
    report_lines.append("RISK ZONE DISTRIBUTION")
    report_lines.append("-" * 40)
    for zone in ['RED', 'ORANGE', 'GREEN']:
        count = (df['model_risk_zone'] == zone).sum()
        report_lines.append(f"  {zone:8s}: {count:>6,} villages ({count/len(df)*100:.1f}%)")

    report_lines.append("")

    # Priority Summary
    report_lines.append("RELOCATION PRIORITY")
    report_lines.append("-" * 40)
    for level in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        count = (df['priority_level'] == level).sum()
        report_lines.append(f"  {level:8s}: {count:>6,} villages")

    report_lines.append("")

    # State Breakdown
    report_lines.append("STATE-WISE BREAKDOWN")
    report_lines.append("-" * 40)
    report_lines.append(f"{'State':<25s} {'Total':>6s} {'RED':>6s} {'ORANGE':>6s} {'GREEN':>6s} {'CRITICAL':>8s} {'Risk%':>6s}")
    for _, row in state_stats.sort_values('risk_rate', ascending=False).iterrows():
        report_lines.append(
            f"  {row['State Name']:<23s} {row['total_villages']:>6,} "
            f"{row['red_count']:>6,} {row['orange_count']:>6,} "
            f"{row['green_count']:>6,} {row['critical_count']:>8,} "
            f"{row['risk_rate']:>5.1f}%"
        )

    report_lines.append("")

    # Ground Truth
    report_lines.append("GROUND TRUTH VALIDATION (EM-DAT)")
    report_lines.append("-" * 40)
    report_lines.append(f"  EM-DAT NE India events: {gt_comparison['total_emdat_events']}")
    report_lines.append(f"  Villages in disaster zones: {gt_comparison['villages_in_emdat_zone']:,}")
    if gt_comparison['villages_in_emdat_zone'] > 0:
        rate = gt_comparison['correctly_flagged'] / gt_comparison['villages_in_emdat_zone'] * 100
        report_lines.append(f"  Correctly flagged: {gt_comparison['correctly_flagged']:,} ({rate:.1f}%)")
        report_lines.append(f"  Missed: {gt_comparison['missed']:,}")

    report_lines.append("")

    # Top Risk Features
    report_lines.append("KEY RISK FACTORS (by SHAP importance)")
    report_lines.append("-" * 40)
    report_lines.append("  1. Distance to nearest landslide")
    report_lines.append("  2. Mean daily rainfall")
    report_lines.append("  3. Landslide density (100km radius)")
    report_lines.append("  4. Landslide density (50km radius)")
    report_lines.append("  5. Elevation")
    report_lines.append("  6. Max daily rainfall")
    report_lines.append("  7. Distance to nearest school")
    report_lines.append("  8. Rainfall 90th percentile")
    report_lines.append("  9. Rain days per year")
    report_lines.append(" 10. Total geographical area")

    report_lines.append("")

    # Recommendations
    report_lines.append("RECOMMENDATIONS FOR NDRF/SDMA")
    report_lines.append("-" * 40)
    report_lines.append("  1. IMMEDIATE: Relocate CRITICAL priority villages")
    report_lines.append("     (top 10% by risk × vulnerability score)")
    report_lines.append("  2. SHORT-TERM: Strengthen early warning in RED zones")
    report_lines.append("     Focus on Assam and Meghalaya (largest village counts)")
    report_lines.append("  3. MEDIUM-TERM: Build infrastructure in GREEN zones")
    report_lines.append("     to prepare for relocation")
    report_lines.append("  4. MONITOR: Update model with new disaster events")
    report_lines.append("     Retrain annually with fresh EM-DAT and GSI data")

    report_lines.append("")
    report_lines.append("=" * 70)
    report_lines.append("Generated by AI-powered Hazard Red Zone Platform")
    report_lines.append("Model: XGBoost + SHAP Explainability")
    report_lines.append("=" * 70)

    # Save report
    report_text = "\n".join(report_lines)
    report_path = os.path.join(REPORT_DIR, 'ne_india_risk_report.txt')
    with open(report_path, 'w') as f:
        f.write(report_text)
    print(f"  Saved: {report_path}")

    # Print report
    print("\n" + report_text)

    return report_text


def save_priority_villages(df):
    """Save prioritized village list for action."""
    print("\n=== Saving Priority Village Lists ===")

    # CRITICAL villages (top priority)
    critical = df[df['priority_level'] == 'CRITICAL'].sort_values('priority_score', ascending=False)

    # Select key columns
    priority_cols = [
        'State Name', 'District Name', 'Village Name', 'latitude', 'longitude',
        'model_risk_score', 'model_risk_zone', 'priority_level', 'priority_score',
        'vulnerability_score', 'elevation_m', 'slope_degrees',
        'max_daily_rainfall_mm', 'dist_to_nearest_landslide_km',
        'dist_to_nearest_road_km', 'dist_to_nearest_hospital_km',
        'landslide_density_50km'
    ]

    # Population if available
    pop_col = 'Total Population of Village'
    if pop_col in df.columns:
        priority_cols.insert(14, pop_col)

    available = [c for c in priority_cols if c in critical.columns]
    critical_out = critical[available].copy()

    critical_path = os.path.join(REPORT_DIR, 'critical_priority_villages.csv')
    critical_out.to_csv(critical_path, index=False)
    print(f"  CRITICAL villages: {critical_path} ({len(critical_out):,} villages)")

    # All villages ranked by priority
    all_ranked = df.sort_values('priority_score', ascending=False)
    ranked_path = os.path.join(REPORT_DIR, 'all_villages_ranked.csv')
    ranked_out = all_ranked[available].copy()
    ranked_out.to_csv(ranked_path, index=False)
    print(f"  All villages ranked: {ranked_path} ({len(ranked_out):,} villages)")

    # Top 100 most vulnerable
    print("\n  Top 10 Most Vulnerable Villages:")
    print(f"  {'State':<15s} {'District':<20s} {'Village':<25s} {'Risk':>6s} {'Priority':>8s}")
    print("  " + "-" * 80)
    for _, row in critical.head(10).iterrows():
        print(f"  {row['State Name']:<15s} {str(row['District Name'])[:19]:<20s} "
              f"{str(row['Village Name'])[:24]:<25s} {row['model_risk_score']:.3f} "
              f"{row['priority_score']:.3f}")


def main():
    """Main execution."""
    print("=" * 60)
    print("Phase 4: Prioritization + Visualization + Report")
    print("=" * 60)

    # 1. Load data
    df = load_data()

    # 2. Compute prioritization scores
    df = compute_prioritization_score(df)

    # 3. Create interactive maps
    create_interactive_map(df)
    state_stats = create_state_summary_map(df)

    # 4. Ground truth comparison
    gt_comparison = generate_ground_truth_comparison(df)

    # 5. Generate final report
    generate_final_report(df, state_stats, gt_comparison)

    # 6. Save priority village lists
    save_priority_villages(df)

    # 7. Save updated data
    df.to_csv(os.path.join(OUTPUT_DIR, 'ne_india_village_features.csv'), index=False)
    print(f"\nSaved final dataset: {OUTPUT_DIR}/ne_india_village_features.csv")

    print("\n" + "=" * 60)
    print("PHASE 4 COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
