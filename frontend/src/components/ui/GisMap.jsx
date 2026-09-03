import { useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import * as maplibregl from "maplibre-gl";

const RISK_COLORS = {
  RED: "#DC2626",
  ORANGE: "#D97706",
  GREEN: "#16A34A",
};

// Default view: the 7 North-Eastern states (the real dataset). The mock data
// era centered the map on Idukki, Kerala — that no longer applies.
const DEFAULT_CENTER = [93.5, 25.8];
const DEFAULT_ZOOM = 6;

const CIRCLE_LAYER_ID = "villages-circle";
const RED_HALO_LAYER_ID = "villages-red-halo";
const VILLAGE_SOURCE_ID = "villages";

// Risk-colored circles are visible at EVERY zoom level. The old low-zoom
// heatmap blended every village into a density-based red "blur" regardless of
// its true risk color, so it was removed — circle colors now always reflect
// risk_level, whether zoomed in or out.
const CIRCLE_MINZOOM = 0;
// The RED halo is only decorative emphasis once points separate on screen;
// below this zoom it would wash neighboring ORANGE/GREEN dots with red tint.
const RED_HALO_MINZOOM = 8;

/**
 * Build GeoJSON FeatureCollection from village data.
 */
function buildVillageGeoJSON(data) {
  return {
    type: "FeatureCollection",
    features: data.map((v) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [v.longitude, v.latitude] },
      properties: {
        village_id: v.village_id,
        name: v.name,
        district: v.district,
        risk_level: v.risk_level,
        risk_score: v.risk_score,
        population: v.population,
      },
    })),
  };
}

/**
 * Build a MapLibre filter expression for risk_level + district.
 * Returns an expression array usable with map.setFilter().
 */
function buildFilterExpression(activeRiskLevels, district) {
  const riskList = Array.from(activeRiskLevels);
  const riskFilter =
    riskList.length === 3
      ? null // all visible, no filter needed
      : ["in", ["get", "risk_level"], ["literal", riskList]];

  const districtFilter = district
    ? ["==", ["get", "district"], district]
    : null;

  if (riskFilter && districtFilter) return ["all", riskFilter, districtFilter];
  if (riskFilter) return riskFilter;
  if (districtFilter) return districtFilter;
  return null;
}

/**
 * Dark-themed popup HTML for a village feature.
 */
function buildPopupHTML(props) {
  return `<div style="padding:10px;font-family:Geist,sans-serif;background:#12151C;color:#E8EAED;border-radius:4px;border:1px solid #1E2330;min-width:160px;">
    <div style="font-size:14px;font-weight:500;margin-bottom:2px;">${props.name}</div>
    <div style="font-size:11px;color:#9CA3AF;font-family:JetBrains Mono,monospace;margin-bottom:6px;">${props.village_id}</div>
    <div style="font-size:12px;font-family:JetBrains Mono,monospace;margin-bottom:8px;">
      Score: <span style="color:${RISK_COLORS[props.risk_level]};font-weight:600;">${props.risk_score}</span>
      &nbsp;&middot;&nbsp; Pop: ${props.population.toLocaleString()}
    </div>
    <button id="popup-navigate-btn" data-village-id="${props.village_id}" style="width:100%;padding:5px 8px;font-size:11px;font-family:Geist,sans-serif;font-weight:500;background:#1A1E28;color:#E8EAED;border:1px solid #2A3040;border-radius:2px;cursor:pointer;text-align:center;transition:background 0.15s;">
      View Details &rarr;
    </button>
  </div>`;
}

/**
 * GisMap — reusable MapLibre GL JS map component.
 *
 * Props:
 *   height            — CSS height (default "100%")
 *   className         — extra classes on the container div
 *   activeRiskLevels  — Set<string> of visible risk levels ("RED", "ORANGE", "GREEN")
 *   district          — string filter (null = all districts)
 *   showControls      — show zoom controls (default true)
 *   showPopups        — enable click-to-popup (default true)
 *   externalMapRef    — optional React ref to expose the map instance
 *   villages          — array of village objects (null = empty)
 */
export default function GisMap({
  height = "100%",
  className = "",
  activeRiskLevels = new Set(["RED", "ORANGE", "GREEN"]),
  district = null,
  showControls = true,
  showPopups = true,
  externalMapRef,
  villages = null,
  center = DEFAULT_CENTER,
  zoom = DEFAULT_ZOOM,
}) {
  const villageData = villages || [];
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const navigate = useNavigate();

  // Latest villages, readable from the map-creation closure (data may arrive
  // asynchronously after mount). Kept in a ref updated on every render.
  const villagesRef = useRef(villageData);
  villagesRef.current = villageData;
  const lastFitDistrict = useRef(null);

  // Expose map instance to parent via ref
  useEffect(() => {
    if (externalMapRef) {
      externalMapRef.current = mapRef.current;
    }
  });

  // Update filters when risk levels or district change
  const riskKey = Array.from(activeRiskLevels).sort().join(",");
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const filter = buildFilterExpression(activeRiskLevels, district);
    [CIRCLE_LAYER_ID, RED_HALO_LAYER_ID].forEach((layerId) => {
      if (!map.getLayer(layerId)) return;
      if (layerId === RED_HALO_LAYER_ID) {
        // Halo is always RED-only, intersect with user filter
        map.setFilter(layerId, filter ? ["all", filter, ["==", ["get", "risk_level"], "RED"]] : ["==", ["get", "risk_level"], "RED"]);
      } else {
        map.setFilter(layerId, filter);
      }
    });
  }, [riskKey, district]);

  const handlePopupNavigate = useCallback(
    (villageId) => {
      navigate(`/villages/${villageId}`);
    },
    [navigate]
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "&copy; OpenStreetMap contributors",
          },
        },
        layers: [
          {
            id: "osm-base",
            type: "raster",
            source: "osm",
          },
        ],
      },
      center,
      zoom,
      maxZoom: 18,
    });

    if (showControls) {
      map.addControl(new maplibregl.NavigationControl(), "top-right");
    }

    map.on("load", () => {
      // --- GeoJSON source (single colored-dot layer, visible at all zooms) ---
      // Use the latest villages via ref so a late-resolving query is included.
      const geojson = buildVillageGeoJSON(villagesRef.current);
      map.addSource(VILLAGE_SOURCE_ID, {
        type: "geojson",
        data: geojson,
      });

      // --- RED pulse halo layer (behind main circles, larger + lower opacity) ---
      map.addLayer({
        id: RED_HALO_LAYER_ID,
        type: "circle",
        source: VILLAGE_SOURCE_ID,
        minzoom: RED_HALO_MINZOOM,
        filter: ["==", ["get", "risk_level"], "RED"],
        paint: {
          "circle-radius": 16,
          "circle-color": RISK_COLORS.RED,
          "circle-opacity": 0.2,
          "circle-stroke-width": 0,
        },
      });

      // --- Main circle layer (risk-colored, visible at every zoom level) ---
      map.addLayer({
        id: CIRCLE_LAYER_ID,
        type: "circle",
        source: VILLAGE_SOURCE_ID,
        minzoom: CIRCLE_MINZOOM,
        paint: {
          // Small dots when zoomed far out (keeps 44k points readable), growing
          // to the full dot size as you zoom toward village level.
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            0, 2.5,
            5, 3.5,
            9, 5,
            12, 6.5,
            15, 8,
          ],
          "circle-color": [
            "match",
            ["get", "risk_level"],
            "RED", RISK_COLORS.RED,
            "ORANGE", RISK_COLORS.ORANGE,
            "GREEN", RISK_COLORS.GREEN,
            "#9CA3AF", // fallback
          ],
          "circle-stroke-color": [
            "match",
            ["get", "risk_level"],
            "RED", "#F87171",
            "ORANGE", "#FBBF24",
            "GREEN", "#4ADE80",
            "#9CA3AF",
          ],
          // Thinner stroke at low zoom so small dots stay legible
          "circle-stroke-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            0, 1,
            10, 1.5,
            14, 2,
          ],
        },
      });

      // --- Cursor change on hover ---
      map.on("mouseenter", CIRCLE_LAYER_ID, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", CIRCLE_LAYER_ID, () => {
        map.getCanvas().style.cursor = "";
      });

      // --- Click-to-popup ---
      if (showPopups) {
        // Close any existing popup
        const closePopup = () => {
          if (popupRef.current) {
            popupRef.current.remove();
            popupRef.current = null;
          }
        };

        map.on("click", CIRCLE_LAYER_ID, (e) => {
          if (!e.features || e.features.length === 0) return;
          const props = e.features[0].properties;
          const coords = e.features[0].geometry.coordinates.slice();

          closePopup();

          const popup = new maplibregl.Popup({ offset: 12, closeButton: false })
            .setLngLat(coords)
            .setHTML(buildPopupHTML({
              village_id: props.village_id,
              name: props.name,
              risk_level: props.risk_level,
              risk_score: props.risk_score,
              population: props.population,
            }))
            .addTo(map);

          popupRef.current = popup;

          // Wire navigate button after popup renders
          popup.on("open", () => {
            const btn = popup.getElement()?.querySelector("#popup-navigate-btn");
            if (btn) {
              btn.addEventListener("click", () => handlePopupNavigate(props.village_id));
              btn.addEventListener("mouseenter", () => { btn.style.background = "#2A3040"; });
              btn.addEventListener("mouseleave", () => { btn.style.background = "#1A1E28"; });
            }
          });
        });

        // Close popup when clicking empty map area
        map.on("click", (e) => {
          if (!e.defaultPrevented) closePopup();
        });
      }
    });

    mapRef.current = map;
    if (externalMapRef) externalMapRef.current = map;

    return () => {
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        if (externalMapRef) externalMapRef.current = null;
      }
    };
  }, []);

  // Push updated village data into the GeoJSON source whenever the query
  // resolves or the parent refetches. Without this the map stays empty when
  // data arrives after mount (async fetches are the norm, not the exception).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource(VILLAGE_SOURCE_ID);
    if (!source || typeof source.setData !== "function") return;
    source.setData(buildVillageGeoJSON(villages || []));
  }, [villages]);

  // When a district filter is applied, fly the viewport to that district's
  // villages so the filter visibly changes what the map shows.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !district) {
      lastFitDistrict.current = null;
      return;
    }
    if (lastFitDistrict.current === district) return;
    const pts = (villages || []).filter((v) => v.district === district);
    if (!pts.length) return;
    lastFitDistrict.current = district;
    const bounds = new maplibregl.LngLatBounds();
    pts.forEach((v) => bounds.extend([v.longitude, v.latitude]));
    if (pts.length === 1) {
      map.jumpTo({ center: [pts[0].longitude, pts[0].latitude], zoom: 14 });
    } else {
      map.fitBounds(bounds, { padding: 90, maxZoom: 14, duration: 1200 });
    }
  }, [villages, district]);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        height,
        width: "100%",
        backgroundColor: "#0B0E14",
      }}
    />
  );
}
