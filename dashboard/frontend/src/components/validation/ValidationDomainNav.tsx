import { useTranslation } from "../../i18n";
import { VALIDATION_DOMAIN_IDS, type ValidationDomain } from "./validationOverview";

export function ValidationDomainNav({
  active,
  onChange,
}: {
  active: ValidationDomain;
  onChange: (domain: ValidationDomain) => void;
}) {
  const { t } = useTranslation();

  return (
    <nav aria-label={t("validation.domainsNav")} className="ops-card p-2">
      <div className="flex flex-wrap gap-1">
        {VALIDATION_DOMAIN_IDS.map((id) => {
          const selected = id === active;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onChange(id)}
              aria-current={selected ? "page" : undefined}
              className={`rounded-xl px-3 py-2 text-left transition-all duration-ds ${
                selected
                  ? "bg-ds-surface-secondary shadow-ds-sm ring-1 ring-ds-border"
                  : "hover:bg-ds-surface-secondary/70"
              }`}
            >
              <span className="block text-[13px] font-medium text-ds-text-primary">{t(`validation.domains.${id}.label`)}</span>
              <span className="mt-0.5 hidden text-[10px] text-ds-text-tertiary sm:block">{t(`validation.domains.${id}.description`)}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
