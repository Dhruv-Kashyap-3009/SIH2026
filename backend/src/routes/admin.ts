/**
 * Admin routes — trigger and monitor the model-refresh job.
 *
 *   POST /api/admin/refresh           → start the refresh chain (202 Accepted
 *                                      if started, 409 if one is already
 *                                      running, 500 on unexpected failure)
 *   GET  /api/admin/refresh/status    → live job state: status, current step,
 *                                      progress, predicted_at, recent log
 *
 * These are deliberately NOT cached by the Tier-1 GET cache (see index.ts —
 * every /api/admin path bypasses it), so the status endpoint always reports
 * live progress.
 *
 * Local/demo security note: there is no authentication on this API yet — the
 * route is intended for the local operator and the top-bar refresh button. Add
 * auth before exposing it publicly.
 */
import { Router, Request, Response } from "express";
import {
  getRefreshStatus,
  isRefreshRunning,
  startRefreshJob,
} from "../lib/refreshJob.js";

const router = Router();

router.post("/refresh", async (_req: Request, res: Response) => {
  try {
    if (isRefreshRunning()) {
      res.status(409).json(getRefreshStatus());
      return;
    }
    // Fire-and-forget: return immediately with the initial running state; the
    // frontend polls GET /api/admin/refresh/status until completion.
    startRefreshJob();
    res.status(202).json(getRefreshStatus());
  } catch (error) {
    console.error("POST /api/admin/refresh error:", error);
    res.status(500).json({
      status: "error",
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

router.get("/refresh/status", (_req: Request, res: Response) => {
  res.json(getRefreshStatus());
});

export default router;
