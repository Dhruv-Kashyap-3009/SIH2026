/**
 * Metrics row for the dashboard.
 * Fetches from GET /api/dashboard for live aggregate stats.
 */
import { useQuery } from "@tanstack/react-query";
import StatCard from "../ui/StatCard.jsx";
import { SkeletonCards } from "../ui/SkeletonLoader.jsx";
import ErrorState from "../ui/ErrorState.jsx";
import { apiFetch } from "../../lib/api.js";

function formatNumber(n) {
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toLocaleString();
}

export default function StatsRow() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch("/api/dashboard"),
  });

  if (isLoading) return <SkeletonCards count={5} />;
  if (error) return <ErrorState onRetry={() => refetch()} />;

  const immediateCount = data.relocation_priority?.IMMEDIATE ?? 0;
  const lowConfidence = data.low_confidence_count ?? 0;
  const availableSites = data.sites?.available ?? 0;

  // Details are real aggregates from GET /api/dashboard — no placeholder copy.
  const STATS = [
    {
      label: "RED Risk Villages",
      value: String(data.risk_level?.RED ?? 0),
      detail: `${immediateCount} immediate`,
      valueColor: "text-severity-red",
    },
    {
      label: "ORANGE Risk",
      value: String(data.risk_level?.ORANGE ?? 0),
      detail: `${lowConfidence} low-confidence`,
      valueColor: "text-severity-amber",
    },
    {
      label: "GREEN Risk",
      value: String(data.risk_level?.GREEN ?? 0),
      detail: "safe for habitation",
      valueColor: "text-severity-green",
    },
    {
      label: "Suitable Sites",
      value: String(data.sites?.total ?? 0),
      detail: `${formatNumber(availableSites)} places available`,
      valueColor: "text-severity-green",
    },
    {
      label: "Population at Risk",
      value: formatNumber(data.population_at_risk ?? 0),
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
