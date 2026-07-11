import { useTranslation } from "../../i18n";
import type { ExecutiveKpi } from "./validationOverview";

const TONE_CLASS: Record<NonNullable<ExecutiveKpi["tone"]>, string> = {
  healthy: "text-ds-status-healthy",
  warning: "text-ds-status-warning",
  error: "text-ds-status-error",
  neutral: "text-ds-text-primary",
};

export function ValidationExecutiveOverview({ kpis }: { kpis: ExecutiveKpi[] }) {
  const { t } = useTranslation();

  return (
    <section aria-label={t("validation.executiveTitle")}>
      <div className="mb-3">
        <h2 className="font-ds-display text-[15px] font-semibold text-ds-text-primary">{t("validation.executiveTitle")}</h2>
        <p className="mt-0.5 text-[12px] text-ds-text-secondary">{t("validation.executiveSubtitle")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {kpis.map((kpi) => (
          <article key={kpi.id} className="ops-card relative min-w-0 p-4">
            <div
              className="ops-kpi-wash pointer-events-none absolute inset-0 opacity-[0.06]"
              style={{
                background: "radial-gradient(ellipse 80% 60% at 20% 0%, var(--ds-color-accent), transparent 70%)",
              }}
              aria-hidden
            />
            <div className="relative">
              <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-ds-text-tertiary">{kpi.label}</p>
              <p
                className={`mt-2 font-ds-display text-[clamp(1.25rem,2.5vw,1.75rem)] font-semibold tabular-nums tracking-tight ${
                  TONE_CLASS[kpi.tone ?? "neutral"]
                }`}
              >
                {kpi.value}
              </p>
              {kpi.hint ? <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-ds-text-secondary">{kpi.hint}</p> : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
