import { useTheme } from "../../design-system";
import { useTranslation } from "../../i18n";
import { useReleaseManifest } from "../../releaseVersion";
import type { SupportedLocale } from "../../i18n";
import { StatusBadge, translateConnectionLive } from "../status";
import { SymbolHeart, SymbolSidebar } from "../icons/Symbols";
import { useMonitorStore } from "../../store/monitorStore";
import { ShellDivider, TimestampBadge, shellMotion } from "./ShellPrimitives";
import type { ThemeMode } from "../../design-system";
import type { ViewMode } from "./navConfig";

const THEME_MODES: ThemeMode[] = ["light", "dark", "system"];
const LOCALE_CODES: SupportedLocale[] = ["en", "ru"];

function ThemeSelector() {
  const { mode, setMode } = useTheme();
  const { t } = useTranslation();

  const labels: Record<ThemeMode, string> = {
    light: t("shell.themeLight"),
    dark: t("shell.themeDark"),
    system: t("shell.themeSystem"),
  };

  return (
    <div
      className={`theme-selector inline-flex rounded-ds-input border border-ds-border bg-ds-surface-secondary p-0.5 ${shellMotion}`}
      role="group"
      aria-label={t("shell.theme")}
    >
      {THEME_MODES.map((option) => {
        const active = mode === option;
        return (
          <button
            key={option}
            type="button"
            onClick={() => setMode(option)}
            className={`theme-selector-btn rounded-ds-input px-2.5 py-1 text-[12px] font-medium ${shellMotion} ${
              active ? "theme-selector-btn-active" : ""
            }`}
          >
            {labels[option]}
          </button>
        );
      })}
    </div>
  );
}

function LanguageSelector() {
  const { locale, setLocale, t } = useTranslation();

  return (
    <div
      className={`theme-selector inline-flex rounded-ds-input border border-ds-border bg-ds-surface-secondary p-0.5 ${shellMotion}`}
      role="group"
      aria-label={t("shell.language")}
    >
      {LOCALE_CODES.map((code) => {
        const active = locale === code;
        return (
          <button
            key={code}
            type="button"
            onClick={() => setLocale(code)}
            className={`theme-selector-btn rounded-ds-input px-2.5 py-1 text-[12px] font-medium uppercase ${shellMotion} ${
              active ? "theme-selector-btn-active" : ""
            }`}
          >
            {code}
          </button>
        );
      })}
    </div>
  );
}

function formatHeaderTime(iso?: string | null): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  } catch {
    return null;
  }
}

function ReleaseMark() {
  const manifest = useReleaseManifest();
  const version = manifest?.version || "DATA UNAVAILABLE";
  const label = `${manifest?.app || "Application"} ${manifest?.channel || ""} ${version}`;

  return (
    <a
      href="/release.json"
      className="font-mono text-[11px] font-medium tracking-wide text-ds-text-tertiary"
      title={label}
      aria-label={label}
    >
      {version}
    </a>
  );
}

export function AppHeader({
  view,
  navOpen,
  onToggleNav,
}: {
  view: ViewMode;
  navOpen: boolean;
  onToggleNav: () => void;
}) {
  const { t } = useTranslation();
  const showsLive = view === "ops" || view === "trading";
  const connected = useMonitorStore((s) => s.connected);
  const generatedAt = useMonitorStore((s) => s.snapshot?.generated_at);
  const lastUpdate = showsLive ? formatHeaderTime(generatedAt) : null;

  return (
    <header className="shell-header flex h-[52px] shrink-0 items-center justify-between gap-4 px-5">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onToggleNav}
          className="icon-chip inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px]"
          aria-expanded={navOpen}
          aria-label={navOpen ? t("shell.collapseNav") : t("shell.expandNav")}
          title={navOpen ? t("shell.collapseNav") : t("shell.expandNav")}
        >
          <SymbolSidebar className="h-[16px] w-[16px]" />
        </button>
        <h1 className="truncate font-ds-display text-[15px] font-semibold tracking-tight text-ds-text-primary">
          {t(`nav.${view}.label`)}
        </h1>

        {showsLive ? (
          <>
            <ShellDivider />
            <StatusBadge
              status={translateConnectionLive(connected)}
              icon={SymbolHeart}
              variant="pill"
              pulse={connected}
            />
            {lastUpdate ? (
              <>
                <ShellDivider className="hidden sm:block" />
                <span className="hidden sm:contents">
                  <TimestampBadge label={t("common.updated")} value={lastUpdate} />
                </span>
              </>
            ) : null}
          </>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <ReleaseMark />
        <ShellDivider />
        <LanguageSelector />
        <ShellDivider />
        <ThemeSelector />
      </div>
    </header>
  );
}
