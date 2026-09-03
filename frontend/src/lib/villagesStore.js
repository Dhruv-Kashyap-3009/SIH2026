/**
 * Village data store — Tier 2 (one fetch per session) + Tier 3 (static files).
 *
 * The villages dataset is static between model runs, so it is pre-built into a
 * versioned JSON bundle by scripts/generate_frontend_static.py and served as a
 * plain static file with `Cache-Control: immutable`. The browser downloads each
 * model version once and the database is never queried — not even on the first
 * page load. Pages filter the in-memory list by the global State/District
 * selection in a few milliseconds; the map still receives ALL 43,996 villages
 * (or the region-filtered view) exactly as before.
 *
 * Bundle shape: { meta: { version, predicted_at, village_count }, villages: [...] }
 *
 * Analytics additionally needs the FULL per-village records (top_factors,
 * model_version, prediction_timestamp), so it lazily loads those from the API
 * once (only when the page is first opened) and filters the same way.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSelection } from "../context/SelectionContext.jsx";
import { apiFetch } from "./api.js";

/**
 * Identity of the current static bundles (model version + generator build tag,
 * e.g. "v1.1-susceptibility-2"). Must match the filenames emitted by
 * scripts/generate_frontend_static.py (BUILD_TAG there). Bump whenever the
 * exports are regenerated — the URL changes, so browsers with an
 * immutable-cached copy of an older bundle fetch the new one automatically.
 */
export const STATIC_VERSION = "v1.1-susceptibility-2";

/** Shared query keys — any consumer using these dedupes to one network fetch. */
export const COMPACT_KEY = ["villages", "all", "compact"];
export const FULL_KEY = ["villages", "all", "full"];

const COMPACT_PATH = `/static/vyoma_compact_${STATIC_VERSION}.json`;

const fetchCompactBundle = () => apiFetch(COMPACT_PATH);
const fetchFullVillages = () => apiFetch("/api/villages");

/** Warm the compact cache at app startup (see App.jsx). */
export function prefetchCompactVillages(queryClient) {
  return queryClient.prefetchQuery({
    queryKey: COMPACT_KEY,
    queryFn: fetchCompactBundle,
  });
}

/** The full static bundle { meta, villages } — 43,996 compact rows. */
export function useCompactBundle() {
  return useQuery({
    queryKey: COMPACT_KEY,
    queryFn: fetchCompactBundle,
    // The bundles only change when the model is re-run and the static assets
    // regenerated — never during a browsing session. Keep the data forever so
    // navigating between pages never refetches. A full page reload starts fresh
    // (and the browser's immutable cache makes even that free).
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

/** The 43,996 compact villages (11 map/table fields) + embedded run meta. */
export function useCompactVillages() {
  const query = useCompactBundle();
  return {
    data: query.data?.villages ?? [],
    villages: query.data?.villages ?? [],
    meta: query.data?.meta,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    isFetching: query.isFetching,
  };
}

/** All 43,996 villages, full records (incl. top_factors). Analytics-only. */
export function useFullVillages() {
  return useQuery({
    queryKey: FULL_KEY,
    queryFn: fetchFullVillages,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

/** Pure filter: apply the global State/District selection to a village list. */
export function filterVillagesByRegion(villages, state, district) {
  if (!Array.isArray(villages)) return [];
  if (district) return villages.filter((v) => v.district === district);
  if (state) return villages.filter((v) => v.state === state);
  return villages;
}

/**
 * Shared wrapper: full list from the given store hook + the region-filtered
 * view for the current global selection. Exposes the same fields pages
 * already consumed from their per-page useQuery (data/isLoading/error/refetch),
 * so swapping a page over is a drop-in change.
 */
function useRegionVillages(useAllVillages) {
  const { selectedState, selectedDistrict } = useSelection();
  const query = useAllVillages();
  const allVillages = query.data || [];
  const regionVillages = useMemo(
    () => filterVillagesByRegion(allVillages, selectedState, selectedDistrict),
    [allVillages, selectedState, selectedDistrict]
  );
  return {
    villages: regionVillages,
    regionVillages,
    allVillages,
    data: regionVillages,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

/** Region-filtered view over the shared compact (map/table) store. */
export function useRegionCompactVillages() {
  return useRegionVillages(useCompactVillages);
}

/** Region-filtered view over the shared full (analytics) store. */
export function useRegionFullVillages() {
  return useRegionVillages(useFullVillages);
}
