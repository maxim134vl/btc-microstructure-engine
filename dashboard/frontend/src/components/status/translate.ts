/**
 * UI-only translation layer — maps backend / legacy terminology to platform vocabulary.
 * APIs and stores remain unchanged; call these at render boundaries only.
 */
import type { StatusDomain } from "./types";
import {
  resolveActiveService,
  resolveAlertSeverity,
  resolveCollectorStatus,
  resolveConnectionLive,
  resolveEngineStatus,
  resolveFailedEngineCount,
  resolveFreshness,
  resolveHealthLevel,
  resolveOpenAlerts,
  resolveOpsLevel,
  resolveParquetSummary,
  resolvePipelineState,
  resolveResourceUsage,
  resolveRibbonItem,
  resolveStabilityRestarts,
  resolveStallCount,
  resolveRuntimeStability,
  resolveHealthDimensionStatus,
} from "./mappers";
import { resolveResearchRibbonItem } from "./researchMappers";

/** HEALTHY | GREEN → Operational */
export const translateSystemHealth = resolveHealthLevel;

/** CONNECTED | LIVE → Receiving Data */
export const translateFeedConnection = resolveCollectorStatus;

/** HEALTHY (engine) → Running */
export const translateEngineState = resolveEngineStatus;

/** YELLOW | WARNING | DEGRADED (validation) → Attention Required */
export const translateValidationLevel = (level: string) => resolveOpsLevel(level, "validation");

/** WARNING → Degraded (system) · CRITICAL → Critical */
export const translateAlertSeverity = resolveAlertSeverity;

/** Raw ops ribbon / feed / pipeline levels with domain hint */
export const translateOpsLevel = resolveOpsLevel;

export const translateResourceUsage = resolveResourceUsage;
export const translatePipelineState = resolvePipelineState;
export const translateFreshness = resolveFreshness;
export const translateFailedEngineCount = resolveFailedEngineCount;
export const translateStallCount = resolveStallCount;
export const translateOpenAlerts = resolveOpenAlerts;
export const translateParquetSummary = resolveParquetSummary;
export const translateStabilityRestarts = resolveStabilityRestarts;
export const translateRuntimeStability = resolveRuntimeStability;
export const translateHealthDimensionStatus = resolveHealthDimensionStatus;
export const translateConnectionLive = resolveConnectionLive;
export const translateRibbonItem = resolveRibbonItem;
export const translateResearchRibbonItem = resolveResearchRibbonItem;

export const translateActiveService = resolveActiveService;

/** Convenience: pick translator by domain */
export function translateByDomain(level: string, domain: StatusDomain) {
  return resolveOpsLevel(level, domain);
}
