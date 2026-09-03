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
import { STATIC_VERSION } from "./villagesStore.js";

export const SITES_KEY = ["sites", "all", "static"];

const SITES_PATH = `/static/vyoma_sites_${STATIC_VERSION}.json`;

const fetchSites = () => apiFetch(SITES_PATH);

/** All 12,211 relocation sites (static bundle). */
export function useAllSites() {
  const query = useQuery({
    queryKey: SITES_KEY,
    queryFn: fetchSites,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return {
    data: query.data ?? [],
    sites: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    isFetching: query.isFetching,
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
