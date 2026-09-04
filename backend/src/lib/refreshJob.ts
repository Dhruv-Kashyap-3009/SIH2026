/**
 * Model-refresh job — the "real refresh" behind the top-bar sync button.
 *
 * The refresh button does NOT just re-fetch what the browser already has — it
 * runs the actual model re-run chain on the server (single in-flight job at a
 * time, status polled via GET /api/admin/refresh/status):
 *
 *   1. scripts/refresh_predictions.py   re-run BOTH trained models over all
 *      43,996 villages (in-place on prediction_output.csv; keeps downstream
 *      module columns) and stamp a NEW predicted_at = this run's timestamp
 *   2. scripts/generate_relocation_sites.py    site register + capacity pool
 *   3. scripts/relocation_planner.py --capacity …  RED→GREEN plan vs the pool
 *   4. scripts/generate_relocation_sites.py    re-run to fold in occupancy
 *   5. scripts/generate_vyoma_export.py        all-states village/site exports
 *   6. scripts/generate_vyoma_export.py --state Mizoram   test fixture refresh
 *   7. scripts/generate_frontend_static.py     Tier-3 static UI bundles
 *   8. npx tsx src/seed.ts                      reload Postgres (snapshot)
 *   9. clear the GET response cache so the new rows are served immediately
 *
 * Note on training: the job re-runs prediction with the EXISTING trained
 * models (models/*.json). Re-training XGBoost would need the ~5.6 GB raw
 * datasets and, with unchanged labels/features, produces bit-identical models
 * — so a browser button deliberately does not retrain. Training stays a
 * manual, data-driven step.
 *
 * The pipeline scripts are Python and run from the repo root; the seed runs
 * from backend/ (its dotenv loads DATABASE_URL from backend/.env).
 */
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { clearResponseCache } from "./responseCache.js";

export interface RefreshStatus {
  status: "idle" | "running" | "done" | "error";
  stepId: string | null;
  stepLabel: string | null;
  message: string;
  progress: number; // steps completed / STEPS.length
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
  newPredictedAt: string | null;
  log: string[]; // recent output lines (capped)
}

const REPO_ROOT = resolve(process.cwd(), "..");
const BACKEND_DIR = process.cwd();

interface Step {
  id: string;
  label: string;
  command: string;
  cwd: string;
}

const STEPS: Step[] = [
  {
    id: "predict",
    label: "Re-running model predictions on 43,996 villages",
    command: "python scripts/refresh_predictions.py",
    cwd: REPO_ROOT,
  },
  {
    id: "sites",
    label: "Regenerating relocation sites register",
    command: "python scripts/generate_relocation_sites.py",
    cwd: REPO_ROOT,
  },
  {
    id: "plan",
    label: "Re-solving the relocation plan against the new site pool",
    command:
      "python scripts/relocation_planner.py --capacity data/processed/relocation_capacity_pool.csv",
    cwd: REPO_ROOT,
  },
  {
    id: "sites2",
    label: "Folding relocation assignments into site occupancy",
    command: "python scripts/generate_relocation_sites.py",
    cwd: REPO_ROOT,
  },
  {
    id: "exports",
    label: "Regenerating VYOMA export (all states)",
    command: "python scripts/generate_vyoma_export.py",
    cwd: REPO_ROOT,
  },
  {
    id: "mizoram",
    label: "Regenerating VYOMA export (Mizoram fixture)",
    command: "python scripts/generate_vyoma_export.py --state Mizoram",
    cwd: REPO_ROOT,
  },
  {
    id: "static",
    label: "Rebuilding static UI bundles",
    command: "python scripts/generate_frontend_static.py",
    cwd: REPO_ROOT,
  },
  {
    id: "seed",
    label: "Reloading database (43,996 villages + 10,603 sites)",
    command: "npx tsx src/seed.ts",
    cwd: BACKEND_DIR,
  },
];

let state: RefreshStatus = {
  status: "idle",
  stepId: null,
  stepLabel: null,
  message: "No model refresh has been run yet.",
  progress: 0,
  startedAt: null,
  finishedAt: null,
  error: null,
  newPredictedAt: null,
  log: [],
};

let jobRunning = false;

export function getRefreshStatus(): RefreshStatus {
  return { ...state, log: [...state.log] };
}

export function isRefreshRunning(): boolean {
  return jobRunning;
}

function pushLog(line: string): void {
  const clean = line.replace(/\r?\n$/, "");
  if (!clean.trim()) return;
  state.log.push(clean);
  if (state.log.length > 400) state.log.splice(0, state.log.length - 400);
}

function runCommand(command: string, cwd: string): Promise<number> {
  return new Promise((resolvePromise) => {
    pushLog(`$ ${command}   (cwd: ${cwd})`);
    const child = spawn(command, {
      cwd,
      shell: true,
      // The Python pipeline prints emoji (✅/⚠️…) — without UTF-8 stdout it
      // crashes on Windows cp1252 consoles with UnicodeEncodeError.
      env: {
        ...process.env,
        PYTHONIOENCODING: process.env.PYTHONIOENCODING || "utf-8",
      },
    });
    const onData = (buf: Buffer) => pushLog(buf.toString());
    child.stdout?.on("data", onData);
    child.stderr?.on("data", onData);
    child.on("error", (err) => pushLog(`[spawn error] ${err.message}`));
    child.on("close", (code) => resolvePromise(code ?? -1));
  });
}

/** Start the refresh chain if one is not already running. */
export async function startRefreshJob(): Promise<RefreshStatus> {
  if (jobRunning) return getRefreshStatus();

  jobRunning = true;
  state = {
    status: "running",
    stepId: null,
    stepLabel: "Queued",
    message: "Starting model re-run…",
    progress: 0,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    error: null,
    newPredictedAt: null,
    log: [],
  };

  try {
    for (let i = 0; i < STEPS.length; i++) {
      const step = STEPS[i];
      state.stepId = step.id;
      state.stepLabel = step.label;
      state.message = step.label;
      state.progress = i;
      pushLog(`\n===== [${i + 1}/${STEPS.length}] ${step.label} =====`);
      const code = await runCommand(step.command, step.cwd);
      if (code !== 0) {
        state.status = "error";
        state.error = `${step.label} failed (exit code ${code}). See the log for details.`;
        state.finishedAt = new Date().toISOString();
        return getRefreshStatus();
      }
      if (step.id === "predict") {
        // Machine-readable marker printed by refresh_predictions.py (stdout
        // chunks can split mid-line, so scan the joined log text).
        const joined = state.log.join("\n");
        const m = joined.match(/REFRESH_PREDICTED_AT=([^\s\r\n]+)/);
        if (m) state.newPredictedAt = m[1];
      }
    }

    state.progress = STEPS.length;
    state.status = "done";
    state.stepId = null;
    state.stepLabel = null;
    state.message = "Model re-run complete — all data is fresh.";
    state.finishedAt = new Date().toISOString();
    clearResponseCache();
    pushLog(
      `\n[DONE] ${state.message} predicted_at=${state.newPredictedAt ?? "?"}`
    );
  } catch (err) {
    state.status = "error";
    state.error = err instanceof Error ? err.message : String(err);
    state.finishedAt = new Date().toISOString();
    pushLog(`[JOB ERROR] ${state.error}`);
  } finally {
    jobRunning = false;
  }

  return getRefreshStatus();
}
