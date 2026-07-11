import { ProductLogoMark, NavSymbol } from "../icons/Symbols";
import { useTranslation } from "../../i18n";
import { EnvironmentStatus, IconChip, shellMotion } from "./ShellPrimitives";
import { getVisibleNavItems, type ViewMode } from "./navConfig";

type AppSidebarProps = {
  view: ViewMode;
  /** Icon-only rail when true and sidebar is not manually expanded. */
  focusMode?: boolean;
  expanded?: boolean;
  onToggleExpanded?: () => void;
};

export function AppSidebar({ view, focusMode = false, expanded = true, onToggleExpanded }: AppSidebarProps) {
  const { t } = useTranslation();
  const compact = focusMode && !expanded;
  const navItems = getVisibleNavItems();

  return (
    <aside
      className={`shell-sidebar flex shrink-0 flex-col overflow-hidden border-r border-ds-border/60 transition-[width] duration-200 ease-out ${
        compact ? "w-14" : "w-[248px]"
      }`}
    >
      <div className={`shrink-0 border-b border-ds-border/50 ${compact ? "px-2 py-3" : "px-4 py-4"}`}>
        {compact ? (
          <div className="flex justify-center" title={t("shell.platform")}>
            <ProductLogoMark className="h-9 w-9 shrink-0 shadow-ds-sm" />
          </div>
        ) : (
          <div className="flex items-start gap-3">
            <ProductLogoMark className="h-10 w-10 shrink-0 shadow-ds-sm" />
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="font-ds-display text-[14px] font-semibold leading-tight tracking-tight text-ds-text-primary">
                {t("shell.platform")}
              </div>
              <div className="mt-1.5">
                <EnvironmentStatus />
              </div>
            </div>
          </div>
        )}
      </div>

      <nav className="panel-scroll flex-1 overflow-y-auto px-2 py-4 sm:px-3" aria-label={t("shell.mainNav")}>
        <ul className="space-y-1">
          {navItems.map((item, index) => {
            const active = view === item.id;
            const previous = navItems[index - 1];
            const showDivider = !compact && item.section === "research" && previous?.section === "platform";

            return (
              <li key={item.id}>
                {showDivider ? <div className="shell-nav-divider my-3" aria-hidden /> : null}
                <a
                  href={item.href}
                  title={t(`nav.${item.id}.description`)}
                  className={`shell-nav-item group relative flex items-center rounded-[10px] py-2 ${shellMotion} ${
                    compact ? "justify-center px-1" : "gap-3 px-2.5"
                  } ${active ? "shell-nav-item-active" : ""}`}
                  aria-current={active ? "page" : undefined}
                >
                  <IconChip active={active}>
                    <NavSymbol id={item.icon} className={`h-[16px] w-[16px] ${shellMotion}`} />
                  </IconChip>
                  {!compact ? (
                    <span
                      className={`shell-nav-label block text-[13px] leading-snug ${shellMotion} ${active ? "font-semibold" : "font-medium"}`}
                    >
                      {t(`nav.${item.id}.label`)}
                    </span>
                  ) : null}
                </a>
              </li>
            );
          })}
        </ul>
      </nav>

      {focusMode ? (
        <div className="shrink-0 border-t border-ds-border/50 p-2">
          <button
            type="button"
            onClick={onToggleExpanded}
            className="flex w-full items-center justify-center rounded-lg border border-ds-border bg-ds-surface py-2 text-[11px] font-medium text-ds-text-secondary transition-colors hover:bg-ds-surface-secondary hover:text-ds-text-primary"
            aria-expanded={expanded}
            title={expanded ? t("shell.collapseNav") : t("shell.expandNav")}
          >
            {expanded ? "‹" : "›"}
          </button>
        </div>
      ) : null}
    </aside>
  );
}
