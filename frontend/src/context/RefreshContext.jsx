/**
 * Global "refresh data" control (top-bar sync button).
 *
 * Clicking refresh does NOT merely re-download what the browser already has —
 * it triggers a REAL model re-run on the backend:
 *
 *   POST /api/admin/refresh   → the server re-runs both models over all
 *                               43,996 villages (scripts/refresh_predictions.py),
 *                               regenerates the relocation sites + VYOMA exports,
 *                               rebuilds the Tier-3 static bundles, reloads the
 *                               database via `npm run seed`, and clears the API
 *                               response cache. This takes ~5-15 minutes and
 *                               runs as a single in-flight job.
 *   GET  /api/admin/refresh/status → polled here every few seconds for progress.
 *
 * When the job completes successfully the page does a hard reload, so every
 * view (dashboard numbers, map, detail pages, the "Predicted <date>" chip) is
 * rebuilt from the fresh bundles + DB — the chip then shows the new model-run
 * date. The sync time is persisted to localStorage so the chip still shows
 * "✓ Synced …" right after the reload.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import { apiFetch } from "../lib/api.js";

const RefreshContext = createContext(null);

const LAST_SYNC_KEY = "vyoma:lastSyncedAt";
const POLL_INTERVAL_MS = 2500;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function loadLastSyncedAt() {
  try {
    const raw = localStorage.getItem(LAST_SYNC_KEY);
    const d = raw ? new Date(raw) : null;
    return d && !Number.isNaN(d.getTime()) ? d : null;
  } catch {
    return null;
  }
}

export function RefreshProvider({ children }) {
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStep, setRefreshStep] = useState(null); // { stepId, stepLabel, message }
  const [refreshError, setRefreshError] = useState(null);
  const [lastSyncedAt, setLastSyncedAt] = useState(loadLastSyncedAt);

  const refreshAll = useCallback(async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError(null);
    setRefreshStep(null);
    try {
      // 1) Kick off the server-side model re-run.
      const started = await apiFetch("/api/admin/refresh", {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (started.status === "error") {
        throw new Error(started.error || "Model refresh failed to start.");
      }

      // 2) Poll until the job is no longer running.
      for (;;) {
        await sleep(POLL_INTERVAL_MS);
        const job = await apiFetch("/api/admin/refresh/status");
        if (job.status === "error") {
          throw new Error(job.error || "Model refresh failed — see server log.");
        }
        if (job.status === "running") {
          setRefreshStep({
            stepId: job.stepId,
            stepLabel: job.stepLabel,
            message: job.message,
          });
          continue;
        }
        // done
        break;
      }

      // 3) Remember when we synced, then hard-reload so every page (including
      //    the "Predicted <date>" chip) is rebuilt from the fresh data.
      const nowIso = new Date().toISOString();
      try {
        localStorage.setItem(LAST_SYNC_KEY, nowIso);
      } catch {
        /* private mode — ignore */
      }
      setLastSyncedAt(new Date(nowIso));
      setRefreshing(false);
      window.location.reload();
    } catch (err) {
      setRefreshing(false);
      setRefreshStep(null);
      setRefreshError(err instanceof Error ? err.message : String(err));
    }
  }, [refreshing]);

  const value = useMemo(
    () => ({
      refreshing,
      refreshStep,
      refreshError,
      lastSyncedAt,
      refreshAll,
    }),
    [refreshing, refreshStep, refreshError, lastSyncedAt, refreshAll]
  );

  return (
    <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>
  );
}

export function useRefresh() {
  const ctx = useContext(RefreshContext);
  if (!ctx) throw new Error("useRefresh must be used inside <RefreshProvider>");
  return ctx;
}
