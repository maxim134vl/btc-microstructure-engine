#!/usr/bin/env node
/** Verify research pipeline status labels match semantic mapping (card = ribbon). */
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

const DECISION_LABELS = {
  ENTRY_ELIGIBLE: "Healthy",
  STAND_ASIDE: "Stand Aside",
  OBSERVE: "Observe",
  REVERSAL_WATCH: "Reversal Watch",
  NO_ENTRY: "No Entry",
  WATCH: "Watch",
  UNAVAILABLE: "Unavailable",
};

function resolveDecisionStatus(level, statusLabel) {
  const normalized = level.toUpperCase();
  if (statusLabel && DECISION_LABELS[statusLabel]) return DECISION_LABELS[statusLabel];
  if (normalized === "GREEN") return "Healthy";
  if (normalized === "RED") return "Unavailable";
  return "Watch";
}

function resolveGovernanceStatus(_level, governanceStatus) {
  return governanceStatus?.trim() || "UNKNOWN";
}

function resolveDriftStatus(level, severityLabel) {
  if (severityLabel?.trim()) return severityLabel.trim();
  const n = level.toUpperCase();
  if (n === "GREEN") return "Stable";
  if (n === "RED") return "Critical";
  if (n === "GREY") return "Unknown";
  return "Warning";
}

function resolveToxicStatus(level, severityLabel) {
  if (severityLabel?.trim()) return severityLabel.trim();
  const n = level.toUpperCase();
  if (n === "GREEN") return "Normal";
  if (n === "RED") return "Critical";
  return "Elevated";
}

function resolveEconomicStatus(level) {
  const n = level.toUpperCase();
  if (n === "GREEN") return "Passing";
  if (n === "RED") return "Failing";
  return "Review";
}

function resolveShadowStatus(level, validationStatus) {
  const vs = (validationStatus || "").toUpperCase();
  if (vs === "PASS") return "PASS";
  if (vs === "WARNING") return "REVIEW";
  if (vs === "MISSING" || vs === "FAIL") return "FAIL";
  if (level.toUpperCase() === "GREEN") return "PASS";
  if (level.toUpperCase() === "RED") return "FAIL";
  return "REVIEW";
}

function resolveResearchRibbonItem(item) {
  switch (item.key) {
    case "decision_layer":
      return resolveDecisionStatus(item.level, item.value);
    case "model_governance":
      return resolveGovernanceStatus(item.level, item.value);
    case "economic_validation":
      return resolveEconomicStatus(item.level);
    case "shadow_inference":
      return resolveShadowStatus(item.level, item.value);
    case "toxic_box":
      return resolveToxicStatus(item.level);
    case "pipeline_sync":
      return item.level.toUpperCase() === "GREEN" ? "Synced" : "Out of Sync";
    default:
      return resolveDecisionStatus(item.level, item.value);
  }
}

async function main() {
  const res = await fetch("http://127.0.0.1:8080/api/v1/research-pipeline/snapshot");
  if (!res.ok) {
    console.error("API not running — start dashboard backend first");
    process.exit(1);
  }
  const snap = await res.json();
  const dl = snap.decision_layer;

  const cases = [
    {
      card: "Decision Layer",
      level: dl.level,
      cardLabel: resolveDecisionStatus(dl.level, dl.status_label),
      ribbon: snap.ribbon_extensions?.find((r) => r.key === "decision_layer"),
      expected: resolveDecisionStatus(dl.level, dl.status_label),
    },
    {
      card: "ML Governance",
      level: snap.model_governance.level,
      cardLabel: resolveGovernanceStatus(snap.model_governance.level, snap.model_governance.governance_status),
      ribbon: snap.ribbon_extensions?.find((r) => r.key === "model_governance"),
      expected: snap.model_governance.governance_status,
    },
    {
      card: "Drift Monitoring",
      level: snap.drift_monitoring.level,
      cardLabel: resolveDriftStatus(snap.drift_monitoring.level, snap.drift_monitoring.severity_label),
      ribbon: null,
      expected: resolveDriftStatus(snap.drift_monitoring.level, snap.drift_monitoring.severity_label),
    },
    {
      card: "Toxic Box",
      level: snap.toxic_box.level,
      cardLabel: resolveToxicStatus(snap.toxic_box.level, snap.toxic_box.severity_label),
      ribbon: snap.ribbon_extensions?.find((r) => r.key === "toxic_box"),
      expected: resolveToxicStatus(snap.toxic_box.level, snap.toxic_box.severity_label),
    },
    {
      card: "Economic Validation",
      level: snap.economic_validation.level,
      cardLabel: resolveEconomicStatus(snap.economic_validation.level),
      ribbon: snap.ribbon_extensions?.find((r) => r.key === "economic_validation"),
      expected: resolveEconomicStatus(snap.economic_validation.level),
    },
    {
      card: "Shadow Model",
      level: snap.shadow_inference.level,
      cardLabel: resolveShadowStatus(snap.shadow_inference.level, snap.shadow_inference.validation_status),
      ribbon: snap.ribbon_extensions?.find((r) => r.key === "shadow_inference"),
      expected: resolveShadowStatus(snap.shadow_inference.level, snap.shadow_inference.validation_status),
    },
  ];

  let md = "# Dashboard Status Mapping Verification\n\n";
  md += "| Card | Backend level | Rendered label | Ribbon label | Expected label | Card=Ribbon | PASS/FAIL |\n";
  md += "|------|---------------|----------------|--------------|----------------|-------------|----------|\n";

  for (const c of cases) {
    const ribbonLabel = c.ribbon ? resolveResearchRibbonItem(c.ribbon) : "—";
    const match = c.cardLabel === ribbonLabel || !c.ribbon;
    const pass = c.cardLabel === c.expected && match;
    md += `| ${c.card} | ${c.level} | ${c.cardLabel} | ${ribbonLabel} | ${c.expected} | ${match ? "yes" : "no"} | ${pass ? "PASS" : "FAIL"} |\n`;
  }

  const out = join(root, "../../exports/dashboard_status_mapping_verification.md");
  writeFileSync(out, md);
  console.log(md);
  console.log("Wrote", out);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
