export type {
  EngineStatusKey,
  FeedStatusKey,
  ResolvedStatus,
  StatusDomain,
  StatusKey,
  StatusTone,
  SystemStatusKey,
  ValidationStatusKey,
  ResearchStatusKey,
} from "./types";

export {
  ENGINE_STATUS,
  FEED_STATUS,
  RAW_STATUS_PATTERN,
  SYSTEM_STATUS,
  VALIDATION_STATUS,
  labelFor,
} from "./vocabulary";

export {
  TONE_ACCENT_BAR,
  TONE_BADGE_CLASS,
  TONE_DOT_CLASS,
  TONE_GLOW,
  TONE_ICON_CHIP,
  TONE_KPI_WASH,
  TONE_RING_GLOW_CLASS,
  TONE_RING_TRACK,
  TONE_STRIPE,
  TONE_STROKE,
} from "./visual";

export {
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
} from "./mappers";

export {
  isResearchRibbonKey,
  resolveDecisionStatus,
  resolveDriftStatus,
  resolveEconomicStatus,
  resolveGovernanceStatus,
  resolveModelSummaryStatus,
  resolvePipelineSyncStatus,
  resolveResearchRibbonItem,
  resolveShadowStatus,
  resolveToxicStatus,
} from "./researchMappers";

export {
  translateActiveService,
  translateAlertSeverity,
  translateByDomain,
  translateConnectionLive,
  translateEngineState,
  translateFailedEngineCount,
  translateFeedConnection,
  translateFreshness,
  translateOpenAlerts,
  translateOpsLevel,
  translateParquetSummary,
  translatePipelineState,
  translateResourceUsage,
  translateRibbonItem,
  translateResearchRibbonItem,
  translateStabilityRestarts,
  translateStallCount,
  translateSystemHealth,
  translateValidationLevel,
} from "./translate";

export { DOMAIN_STATUS_ICON } from "./defaultIcons";

export { StatusDot } from "./StatusDot";
export { StatusBadge } from "./StatusBadge";
export { StatusIndicator } from "./StatusIndicator";
export { StatusCardAccent, StatusCardAccentFromStatus, statusStripeClass } from "./StatusCardAccent";

export {
  StatusSimulatorProvider,
  useSimulatedStatus,
  useStatusSimulator,
} from "./StatusSimulatorContext";

export { StatusSimulatorPanel } from "./StatusSimulatorPanel";
export { applyStatusSimulator, STATUS_SIMULATOR_STORAGE_KEY } from "./simulator";
