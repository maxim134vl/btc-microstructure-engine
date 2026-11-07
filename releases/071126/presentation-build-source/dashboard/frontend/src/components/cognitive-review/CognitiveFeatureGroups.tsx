import { useMemo, useState } from "react";
import type { CognitiveFeatureGroup, CognitiveFeatureMeta } from "../../types/cognitiveReview";
import { asFeatureGroups, asFeatureMeta } from "../../types/cognitiveReview";
import { displayRaw } from "../../types/eventReview";

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-2 border-b border-ds-border/60 py-1.5 text-[11px] last:border-b-0">
      <div className="text-ds-text-tertiary">{label}</div>
      <div className="break-all text-ds-text-primary">{value}</div>
    </div>
  );
}

export function CognitiveSignalGroups({
  groups,
  featureMeta: featureMetaInput,
  features,
}: {
  groups: CognitiveFeatureGroup[];
  featureMeta?: CognitiveFeatureMeta[];
  features: Record<string, unknown>;
}) {
  const featureMeta = asFeatureMeta(featureMetaInput);
  const safeGroups = asFeatureGroups(groups);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const metaByName = useMemo(() => {
    const map = new Map<string, CognitiveFeatureMeta>();
    for (const item of featureMeta) map.set(item.name, item);
    return map;
  }, [featureMeta]);

  if (safeGroups.length === 0) {
    return <div className="text-[11px] text-ds-text-tertiary">Нет семантических признаков cognition.</div>;
  }

  return (
    <div className="space-y-2">
      {safeGroups.map((group) => {
        const isCollapsed = collapsed[group.id] ?? false;
        return (
          <div key={group.id} className="overflow-hidden rounded-xl border border-ds-border/80 bg-ds-surface-secondary/30">
            <button
              type="button"
              onClick={() => setCollapsed((prev) => ({ ...prev, [group.id]: !isCollapsed }))}
              className="flex w-full items-center justify-between px-2.5 py-2 text-left text-[10px] font-medium uppercase tracking-[0.06em] text-ds-text-primary transition-colors hover:bg-ds-surface-secondary/60"
            >
              <span>{group.label}</span>
              <span className="text-ds-text-tertiary">{isCollapsed ? "+" : "−"}</span>
            </button>
            {!isCollapsed ? (
              <div className="border-t border-ds-border/60 px-1 pb-1">
                {group.features.map((name) => {
                  const meta = metaByName.get(name);
                  return (
                    <InfoRow
                      key={name}
                      label={meta?.label ?? name}
                      value={displayRaw(features[name])}
                    />
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function CognitiveDynamicsFeaturePicker({
  groups,
  featureMeta: featureMetaInput,
  selected,
  onChange,
}: {
  groups: CognitiveFeatureGroup[];
  featureMeta?: CognitiveFeatureMeta[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const featureMeta = asFeatureMeta(featureMetaInput);
  const safeGroups = asFeatureGroups(groups);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const metaByName = useMemo(() => {
    const map = new Map<string, CognitiveFeatureMeta>();
    for (const item of featureMeta) map.set(item.name, item);
    return map;
  }, [featureMeta]);

  function toggle(name: string) {
    onChange(selected.includes(name) ? selected.filter((item) => item !== name) : [...selected, name]);
  }

  return (
    <div className="space-y-1">
      {safeGroups.map((group) => {
        const isCollapsed = collapsed[group.id] ?? false;
        return (
          <div key={group.id} className="overflow-hidden rounded-xl border border-ds-border/80">
            <button
              type="button"
              onClick={() => setCollapsed((prev) => ({ ...prev, [group.id]: !isCollapsed }))}
              className="flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[10px] font-medium text-ds-text-secondary transition-colors hover:bg-ds-surface-secondary/50"
            >
              <span>{group.label}</span>
              <span className="text-ds-text-tertiary">{isCollapsed ? "+" : "−"}</span>
            </button>
            {!isCollapsed ? (
              <div className="space-y-0.5 border-t border-ds-border/60 px-2 py-1.5">
                {group.features.map((name) => {
                  const meta = metaByName.get(name);
                  return (
                    <label key={name} className="flex cursor-pointer items-center gap-2 text-[10px] text-ds-text-secondary">
                      <input
                        type="checkbox"
                        checked={selected.includes(name)}
                        onChange={() => toggle(name)}
                      />
                      {meta?.label ?? name}
                    </label>
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
