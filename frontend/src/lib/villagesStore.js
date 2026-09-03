/**
 * Village data store — Tier-2 client-side filtering.
 *
 * Before: every page re-queried the API with ?state= / &district= filters, so
 * each navigation and each filter change paid a fresh ~10-15s DB round trip
 * for the 43,996-village list (the remote-DB latency + serialization cost).
 *
 * Now: the full COMPACT village list is fetched ONCE per app session
 * (prefetched at startup by App.jsx) and kept in the React Query cache for the
 * lifetime of the tab — the data is static between model runs, so it never
 * goes stale. Pages filter that in-memory array by the global State/District
 * selection in a few milliseconds. The map still receives ALL villages (or the
 * region-filtered subset) exactly as before — nothing is hidden or dropped.
 *
 * Analytics additionally needs the FULL per-village records (top_factors,
 * model_version, prediction_timestamp), so it lazily loads the full list once
 * (only when the page is first opened) and filters the same way.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSelection } from "../context/SelectionContext.jsx";
import { apiFetch } from "./api.js";

/** Shared query keys — any consumer using these dedupes to one network fetch. */
export const COMPACT_KEY = ["villages", "all", "compact"];
export const FULL_KEY = ["villages", "all", "full"];

const fetchCompactVillages = () => apiFetch("/api/villages?compact=1");
const fetchFullVillages = () => apiFetch("/api/villages");

/** Warm the compact cache at app startup (see App.jsx). */
export function prefetchCompactVillages(queryClient) {
  return queryClient.prefetchQuery({
    queryKey: COMPACT_KEY,
    queryFn: fetchCompactVillages,
  });
}

/** All 43,996 villages, compact projection (11 map/table fields). */
export function useCompactVillages() {
  return useQuery({
    queryKey: COMPACT_KEY,
    queryFn: fetchCompactVillages,
    // The exports only change when the model is re-run and the DB re-seeded —
    // never during a browsing session. Keep the data forever so navigating
    // between pages never refetches. A full page reload starts fresh.
    staleTime: Infinity,
    gcTime: Infinity,
  });
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
