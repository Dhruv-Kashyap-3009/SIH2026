/**
 * Dashboard page matching the exact Stitch design.
 * Composes all dashboard sections: header, stats, map+table, bottom row.
 */
import { useEffect, useRef } from "react";
import Icon from "../components/ui/Icon.jsx";
import StatsRow from "../components/dashboard/StatsRow.jsx";
import MapPanel from "../components/dashboard/MapPanel.jsx";
import CriticalHabitationsTable from "../components/dashboard/CriticalHabitationsTable.jsx";
import RelocationPrioritySummary from "../components/dashboard/RelocationPrioritySummary.jsx";
import RelocationSiteCapacity from "../components/dashboard/RelocationSiteCapacity.jsx";
import { useCompactVillages } from "../lib/villagesStore.js";
import { useRefresh } from "../context/RefreshContext.jsx";

function formatTimestamp(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Dashboard() {
  // National (all-state) overview by design — this page is NOT region-filtered,
  // so no State/District selection is read or shown here.

  // Tier 3: predicted_at / model_version come from the static bundle's meta
  // (embedded by scripts/generate_frontend_static.py) — the header is backed by
  // real run metadata without any database call.
  const { meta } = useCompactVillages();
  const { refreshing, lastSyncedAt, refreshStep } = useRefresh();

  const predictedLabel = formatTimestamp(meta?.predicted_at);
  // Bundle meta carries the run identity under `version` (not model_version).
  const runVersion = meta?.version || meta?.model_version;

  // Snapshot the run identity before a refresh starts, so we can flash
  // "Updated" when the re-pull actually delivered a newer model run.
  const prevRun = useRef(null);
  useEffect(() => {
    if (refreshing && meta?.predicted_at) {
      prevRun.current = `${meta.predicted_at}|${runVersion ?? ""}`;
    }
  }, [refreshing, meta, runVersion]);

  const runChanged =
    !refreshing &&
    prevRun.current !== null &&
    !!meta?.predicted_at &&
    prevRun.current !== `${meta.predicted_at}|${runVersion ?? ""}`;

  // Sync chip states:
  //   idle          → "Predicted <model run date>" (before the first refresh)
  //   refreshing    → spinning sync + "Refreshing data…"
  //   synced        → "✓ Synced <refresh date>" — PERSISTS after each refresh,
  //                   so clicking the button always visibly updates the date
  //                   (the model-run date is kept in the tooltip + title)
  //   run changed   → "✓ Updated · Predicted <new run date>" (a re-pull
  //                   actually delivered a newer model run)
  let chipIcon = "sync";
  let chipSpin = false;
  let chipText;
  let chipTitle;
  if (refreshing) {
    chipSpin = true;
    chipText = "Re-running model…";
    chipTitle =
      refreshStep?.message ||
      "Re-running the model on the server — predictions, exports and database reload. This takes several minutes…";
  } else if (runChanged) {
    chipIcon = "check_circle";
    chipText = `✓ Updated · Predicted ${predictedLabel}${runVersion ? ` · ${runVersion}` : ""}`;
    chipTitle = `New model run detected — the on-screen data now reflects the run of ${predictedLabel}.`;
  } else if (lastSyncedAt) {
    chipIcon = "check_circle";
    chipText = `✓ Synced ${formatTimestamp(lastSyncedAt)}${runVersion ? ` · ${runVersion}` : ""}`;
    chipTitle = `Last refreshed: ${formatTimestamp(lastSyncedAt)}. Model run date: ${predictedLabel ?? "n/a"} · ${runVersion ?? ""} — click the sync icon in the top bar to refresh again.`;
  } else {
    chipText = predictedLabel
      ? `Predicted ${predictedLabel}${runVersion ? ` · ${runVersion}` : ""}`
      : "Model run metadata unavailable";
    chipTitle = "The date/time the on-screen data was predicted by the model — click the sync icon in the top bar to refresh and re-sync now.";
  }
  const chipHighlighted = !refreshing && (runChanged || !!lastSyncedAt);

  return (
    <main className="flex-1 overflow-y-auto p-margin-page flex flex-col gap-stack-lg bg-surface-lowest">
      {/* 1. Header Section */}
      <div className="flex items-end justify-between border-b border-border-subtle pb-stack-sm">
        <div>
          <h2 className="font-headline-lg text-headline-lg text-primary">
            Overview
          </h2>
        </div>
        <div
          className={`flex items-center gap-2 bg-surface-base px-3 py-1 border rounded-[2px] transition-colors ${
            chipHighlighted
              ? "border-severity-green/40 text-severity-green"
              : "border-border-subtle text-on-surface-variant"
          }`}
          title={chipTitle}
        >
          <Icon name={chipIcon} className={`text-[14px] ${chipSpin ? "animate-spin" : ""}`} />
          <span className="font-label-sm text-label-sm">{chipText}</span>
        </div>
      </div>

      {/* 2. Metrics Row */}
      <StatsRow />

      {/* 3 & 4. Map + Side Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-gutter h-[600px]">
        <MapPanel />
        <CriticalHabitationsTable />
      </div>

      {/* 5. Bottom Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-gutter pb-margin-page">
        <RelocationPrioritySummary />
        <RelocationSiteCapacity />
      </div>
    </main>
  );
}
