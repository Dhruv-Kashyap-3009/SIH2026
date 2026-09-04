/**
 * Relocation-sites store — Tier-3 static read path (same pattern as
 * villagesStore.js).
 *
 * The 12,211 relocation sites are static between model runs, so the frontend
 * loads the versioned static bundle once per session (immutable-cached by the
 * browser) and filters it in memory by the global State/District selection —
 * no database query, no per-filter refetch.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSelection } from "../context/SelectionContext.jsx";
import { apiFetch } from "./api.js";
import { useStaticManifest } from "./villagesStore.js";

export const SITES_KEY = ["sites", "all", "static"];

const bundleKey = (file) => ["static", "sites", file];

/**
 * All relocation sites (static bundle named by latest.json).
 * The filename embeds the model run tag (see villagesStore.js), so after a
 * model refresh + reload the manifest names a NEW file — a browser that has
 * the old file immutable-cached fetches the fresh one via the new URL.
 */
export function useAllSites() {
  const manifestQ = useStaticManifest();
  const file = manifestQ.data?.sites;
  const query = useQuery({
    queryKey: bundleKey(file),
    queryFn: () => apiFetch(`/static/${file}`),
    enabled: !!file,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const data = query.data ?? [];
  return {
    data,
    sites: data,
    allSites: data,
    isLoading: manifestQ.isLoading || query.isLoading,
    error: manifestQ.error ?? query.error,
    refetch: () =>
      Promise.all([
        manifestQ.refetch(),
        file ? query.refetch() : Promise.resolve(),
      ]),
    isFetching: manifestQ.isFetching || query.isFetching,
  };
}

/** Region-filtered view of the sites for the current State/District selection. */
export function useRegionSites() {
  const { selectedState, selectedDistrict } = useSelection();
  const query = useAllSites();
  const allSites = query.allSites ?? query.data ?? [];
  const regionSites = useMemo(() => {
    if (selectedDistrict) return allSites.filter((s) => s.district === selectedDistrict);
    if (selectedState) return allSites.filter((s) => s.state === selectedState);
    return allSites;
  }, [allSites, selectedState, selectedDistrict]);
  return {
    sites: regionSites,
    regionSites,
    allSites,
    data: regionSites,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
