/**
 * Relocation Site Capacity card.
 * Fetches sites from GET /api/sites and displays capacity bars.
 * Capacity thresholds: <70% = green, 70-90% = amber, >=90% = red
 */
import { useQuery } from "@tanstack/react-query";
import ProgressBar from "../ui/ProgressBar.jsx";
import { SkeletonBars } from "../ui/SkeletonLoader.jsx";
import ErrorState from "../ui/ErrorState.jsx";
import { apiFetch } from "../../lib/api.js";

function capacityColor(pct) {
  if (pct >= 90) return "bg-severity-red";
  if (pct >= 70) return "bg-severity-amber";
  return "bg-severity-green";
}

// Real data has 12k+ registered sites; rendering every bar would freeze the
// dashboard. Show the most-utilized ones (occupancy is the interesting signal).
const MAX_SITES_SHOWN = 30;

export default function RelocationSiteCapacity() {
  const { data: sites = [], isLoading, error, refetch } = useQuery({
    queryKey: ["sites", "capacity-card"],
    queryFn: () => apiFetch("/api/sites"),
  });

  const shownSites = sites
    .slice()
    .filter((s) => s.total_capacity > 0)
    .sort((a, b) => b.occupied / b.total_capacity - a.occupied / a.total_capacity)
    .slice(0, MAX_SITES_SHOWN);

  return (
    <div className="border border-border-subtle rounded-[4px] p-4 bg-surface-container-high">
      <h3 className="font-body-lg text-body-lg font-medium text-primary mb-4 border-b border-border-subtle pb-2">
        Relocation Site Capacity
      </h3>
      <div className="flex flex-col gap-4 font-label-md text-label-md">
        {isLoading ? (
          <SkeletonBars count={3} />
        ) : error ? (
          <ErrorState onRetry={() => refetch()} />
        ) : (
          shownSites.map((site) => {
            const pct = Math.round((site.occupied / site.total_capacity) * 100);
            return (
              <ProgressBar
                key={site.site_id}
                label={`${site.name} (${pct > 100 ? ">100%" : `${pct}%`})`}
                // occupied can exceed total_capacity (occupied = full routed population,
                // see validate_vyoma_export) — clamp the bar so layout never breaks.
                percentage={Math.min(pct, 100)}
                barColor={capacityColor(pct)}
              />
            );
          })
        )}
      </div>
      <div className="mt-2 text-[11px] font-mono text-on-surface-variant">
        Top {MAX_SITES_SHOWN} most-utilized of {sites.length} registered sites
      </div>
    </div>
  );
}
