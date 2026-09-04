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
 *
 * VERSION DISCOVERY: the bundle filename embeds the model run's predicted_at
 * (scripts/generate_frontend_static.py derives it), so every model refresh
 * produces a NEW URL — that is the only thing that defeats a browser's
 * `immutable` cache. The frontend therefore never pins a version string; it
 * fetches the tiny latest.json pointer (served with Cache-Control: no-store)
 * and then the current bundle by name. Refresh → new run tag → new URL → the
 * browser downloads the fresh bundle automatically.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSelection } from "../context/SelectionContext.jsx";
import { apiFetch } from "./api.js";

/** Shared query keys — any consumer using these dedupes to one network fetch. */
export const MANIFEST_KEY = ["static", "manifest"];
export const COMPACT_KEY = ["villages", "all", "compact"];
export const FULL_KEY = ["villages", "all", "full"];

const MANIFEST_PATH = "/static/latest.json";

// Never let the browser cache the pointer: no-store forces a network fetch,
// so after a model refresh + page reload the manifest always names the newest
// bundle (whose immutable-cached content may have changed).
const fetchManifest = () => apiFetch(MANIFEST_PATH, { cache: "no-store" });

/**
 * Analytics-only: the full per-village records (top_factors, model_version,
 * prediction_timestamp) are not in the compact bundle, so they are lazily
 * fetched from the API once per session when /analytics is first opened
 * (query key FULL_KEY dedupes to a single network fetch).
 */
const fetchFullVillages = () => apiFetch("/api/villages");

const bundleKey = (kind, file) => ["static", kind, file];

/** latest.json — { version, predicted_at, compact: "<file>", sites: "<file>" }. */
export function useStaticManifest() {
  return useQuery({
    queryKey: MANIFEST_KEY,
    queryFn: fetchManifest,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

/** Warm the compact cache at app startup (see App.jsx). */
export async function prefetchCompactVillages(queryClient) {
  try {
    await queryClient.prefetchQuery({
      queryKey: MANIFEST_KEY,
      queryFn: fetchManifest,
      staleTime: Infinity,
      gcTime: Infinity,
    });
    const manifest = queryClient.getQueryData(MANIFEST_KEY);
    const file = manifest?.compact;
    if (file) {
      await queryClient.prefetchQuery({
        queryKey: bundleKey("compact", file),
        queryFn: () => apiFetch(`/static/${file}`),
        staleTime: Infinity,
        gcTime: Infinity,
      });
    }
  } catch {
    /* startup warm — a failure here surfaces through the hooks below */
  }
}

/**
 * The current static bundle { meta, villages } — 43,996 compact rows.
 * Resolves the filename from latest.json first, then fetches that bundle.
 */
export function useCompactBundle() {
  const manifestQ = useStaticManifest();
  const file = manifestQ.data?.compact;
  const compactQ = useQuery({
    queryKey: bundleKey("compact", file),
    queryFn: () => apiFetch(`/static/${file}`),
    enabled: !!file,
    // Bundles only change when the model is re-run and regenerated — never
    // during a browsing session. Keep the data forever so navigating between
    // pages never refetches. A full page reload starts fresh.
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return {
    data: compactQ.data,
    meta: compactQ.data?.meta,
    isLoading: manifestQ.isLoading || compactQ.isLoading,
    isFetching: manifestQ.isFetching || compactQ.isFetching,
    error: manifestQ.error ?? compactQ.error,
    refetch: () =>
      Promise.all([
        manifestQ.refetch(),
        file ? compactQ.refetch() : Promise.resolve(),
      ]),
  };
}

/** The 43,996 compact villages (11 map/table fields) + embedded run meta. */
export function useCompactVillages() {
  const query = useCompactBundle();
  return {
    data: query.data?.villages ?? [],
    villages: query.data?.villages ?? [],
    meta: query.meta,
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
