/**
 * Villages routes — GET /api/villages, GET /api/villages/districts, GET /api/villages/:id
 *
 * Returns JSON shaped exactly like the VYOMA export so the frontend never needs
 * data-shape translation.
 *
 * Query params (all optional):
 *   ?district= / ?state= / ?risk_level= / ?relocation_priority=  — exact-match filters
 *   ?compact=1  — slim projection (11 map/table fields, ~5 MB vs ~40 MB at 44k rows).
 *                 Omits heavy per-row payloads (top_factors, timestamps, census data).
 *   ?limit=  ?offset=  — server-side pagination (applied after the risk_score sort).
 */
import { Router, Request, Response } from "express";
import prisma from "../lib/prisma.js";

const router = Router();

function toPositiveInt(value: unknown): number | undefined {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return undefined;
  const n = parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

/** Fields the map + list/table UI actually renders (compact projection). */
function toCompactVillage(v: any) {
  return {
    village_id: v.village_id,
    name: v.name,
    district: v.district,
    state: v.state,
    latitude: v.latitude,
    longitude: v.longitude,
    population: v.population,
    risk_score: v.risk_score,
    risk_level: v.risk_level,
    relocation_priority: v.relocation_priority,
    low_confidence: v.low_confidence,
  };
}

/** Full per-village record (matches the export / detail shape). */
function toFullVillage(v: any) {
  return {
    village_id: v.village_id,
    name: v.name,
    district: v.district,
    state: v.state,
    latitude: v.latitude,
    longitude: v.longitude,
    population: v.population,
    risk_score: v.risk_score,
    risk_level: v.risk_level,
    relocation_priority: v.relocation_priority,
    vulnerability_multiplier: v.vulnerability_multiplier,
    top_factors: v.top_factors,
    low_confidence: v.low_confidence,
    recommended_site_id: v.recommended_site_id,
    prediction_timestamp: v.prediction_timestamp.toISOString(),
    model_version: v.model_version,
  };
}

// GET /api/villages/districts — distinct district names, optionally per ?state=
// (registered BEFORE /:id so "districts" is never treated as a village id)
router.get("/districts", async (req: Request, res: Response) => {
  try {
    const { state } = req.query;
    const where: Record<string, any> = {};
    if (typeof state === "string" && state.trim() !== "") where.state = state.trim();

    const rows = await prisma.village.findMany({
      where,
      distinct: ["district"],
      select: { district: true },
    });

    const districts = rows
      .map((r) => r.district)
      .filter((d): d is string => typeof d === "string" && d.trim() !== "")
      .sort((a, b) => a.localeCompare(b));

    res.json(districts);
  } catch (error) {
    console.error("GET /api/villages/districts error:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// GET /api/villages — list all, with optional filters / compact / pagination
router.get("/", async (req: Request, res: Response) => {
  try {
    const { district, risk_level, state, relocation_priority, compact } = req.query;

    const where: Record<string, any> = {};
    if (typeof district === "string") where.district = district;
    if (typeof state === "string") where.state = state;
    if (typeof risk_level === "string") where.risk_level = risk_level;
    if (typeof relocation_priority === "string") where.relocation_priority = relocation_priority;

    const limit = toPositiveInt(req.query.limit);
    const offset = toPositiveInt(req.query.offset);
    const isCompact = compact === "1" || compact === "true";

    const villages = await prisma.village.findMany({
      where,
      orderBy: { risk_score: "desc" },
      ...(limit ? { take: limit } : {}),
      ...(offset ? { skip: offset } : {}),
    });

    const response = villages.map(isCompact ? toCompactVillage : toFullVillage);
    res.json(response);
  } catch (error) {
    console.error("GET /api/villages error:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// GET /api/villages/:id — single village by village_id
router.get("/:id", async (req: Request, res: Response) => {
  try {
    const id = String(req.params.id);

    const village = await prisma.village.findUnique({
      where: { village_id: id },
    });

    if (!village) {
      res.status(404).json({ error: "Village not found", village_id: id });
      return;
    }

    const response = {
      village_id: village.village_id,
      name: village.name,
      district: village.district,
      state: village.state,
      latitude: village.latitude,
      longitude: village.longitude,
      population: village.population,
      risk_score: village.risk_score,
      risk_level: village.risk_level,
      relocation_priority: village.relocation_priority,
      vulnerability_multiplier: village.vulnerability_multiplier,
      top_factors: village.top_factors,
      low_confidence: village.low_confidence,
      recommended_site_id: village.recommended_site_id,
      prediction_timestamp: village.prediction_timestamp.toISOString(),
      model_version: village.model_version,
    };

    res.json(response);
  } catch (error) {
    console.error("GET /api/villages/:id error:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

export default router;
