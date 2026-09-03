/**
 * Metrics row for the dashboard.
 *
 * Tier 3: the numbers are aggregated in the browser from the static village +
 * site bundles (identical source rows to the old GET /api/dashboard call), so
 * the first page load never touches the database.
 */
import { useMemo } from "react";
import StatCard from "../ui/StatCard.jsx";
import { SkeletonCards } from "../ui/SkeletonLoader.jsx";
import ErrorState from "../ui/ErrorState.jsx";
import { useCompactVillages } from "../../lib/villagesStore.js";
import { useAllSites } from "../../lib/sitesStore.js";

function formatNumber(n) {
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toLocaleString();
}

export default function StatsRow() {
  const {
    villages,
    isLoading: villagesLoading,
    error: villagesError,
    refetch: refetchVillages,
  } = useCompactVillages();
  const {
    sites,
    isLoading: sitesLoading,
    error: sitesError,
    refetch: refetchSites,
  } = useAllSites();

  const isLoading = villagesLoading || sitesLoading;
  const error = villagesError || sitesError;

  const stats = useMemo(() => {
    const riskLevel = { RED: 0, ORANGE: 0, GREEN: 0 };
    let immediate = 0;
    let lowConfidence = 0;
    let populationAtRisk = 0;
    for (const v of villages) {
      if (riskLevel[v.risk_level] !== undefined) riskLevel[v.risk_level]++;
      if (v.relocation_priority === "IMMEDIATE") immediate++;
      if (v.low_confidence) lowConfidence++;
      if (v.risk_level === "RED" || v.risk_level === "ORANGE") {
        populationAtRisk += v.population;
      }
    }
    const totalCapacity = sites.reduce((sum, s) => sum + s.total_capacity, 0);
    const available = sites.reduce((sum, s) => sum + s.available, 0);
    return { riskLevel, immediate, lowConfidence, populationAtRisk, sitesTotal: sites.length, totalCapacity, available };
  }, [villages, sites]);

  if (isLoading) return <SkeletonCards count={5} />;
  if (error) return <ErrorState onRetry={() => { refetchVillages(); refetchSites(); }} />;

  // Same numbers and formatting as the previous /api/dashboard-backed row.
  const STATS = [
    {
      label: "RED Risk Villages",
      value: String(stats.riskLevel.RED),
      detail: `${stats.immediate} immediate`,
      valueColor: "text-severity-red",
    },
    {
      label: "ORANGE Risk",
      value: String(stats.riskLevel.ORANGE),
      detail: `${stats.lowConfidence} low-confidence`,
      valueColor: "text-severity-amber",
    },
    {
      label: "GREEN Risk",
      value: String(stats.riskLevel.GREEN),
      detail: "safe for habitation",
      valueColor: "text-severity-green",
    },
    {
      label: "Suitable Sites",
      value: String(stats.sitesTotal),
      detail: `${stats.available.toLocaleString()} places available`,
      valueColor: "text-severity-green",
    },
    {
      label: "Population at Risk",
      value: formatNumber(stats.populationAtRisk),
      detail: "RED + ORANGE pax",
      valueColor: "text-primary",
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-5 gap-gutter">
      {STATS.map((stat) => (
        <StatCard
          key={stat.label}
          label={stat.label}
          value={stat.value}
          detail={stat.detail}
          valueColor={stat.valueColor}
        />
      ))}
    </div>
  );
}
