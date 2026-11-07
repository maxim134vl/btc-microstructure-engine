import { ProductLogoMark, NavSymbol } from "../icons/Symbols";
import { useTranslation } from "../../i18n";
import { EnvironmentStatus, IconChip, shellMotion } from "./ShellPrimitives";
import { getVisibleNavItems, type ViewMode } from "./navConfig";

type AppSidebarProps = {
  view: ViewMode;
  open?: boolean;
};

export function AppSidebar({ view, open = true }: AppSidebarProps) {
  const { t } = useTranslation();
  const navItems = getVisibleNavItems();

  return (
    <aside
      className={`shell-sidebar flex shrink-0 flex-col overflow-hidden border-ds-border/60 transition-[width,border-color] duration-200 ease-out ${
        open ? "w-[248px] border-r" : "w-0 border-r-0"
      }`}
      aria-hidden={!open}
      inert={!open}
    >
      <div className="shrink-0 border-b border-ds-border/50 px-4 py-4">
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
      </div>

      <nav className="panel-scroll flex-1 overflow-y-auto px-2 py-4 sm:px-3" aria-label={t("shell.mainNav")}>
        <ul className="space-y-1">
          {navItems.map((item, index) => {
            const active = view === item.id;
            const previous = navItems[index - 1];
            const showDivider = item.section === "research" && previous?.section === "platform";

            return (
              <li key={item.id}>
                {showDivider ? <div className="shell-nav-divider my-3" aria-hidden /> : null}
                <a
                  href={item.href}
                  title={t(`nav.${item.id}.description`)}
                  className={`shell-nav-item group relative flex items-center gap-3 rounded-[10px] px-2.5 py-2 ${shellMotion} ${
                    active ? "shell-nav-item-active" : ""
                  }`}
                  aria-current={active ? "page" : undefined}
                >
                  <IconChip active={active}>
                    <NavSymbol id={item.icon} className={`h-[16px] w-[16px] ${shellMotion}`} />
                  </IconChip>
                  <span
                    className={`shell-nav-label block whitespace-nowrap text-[13px] leading-snug ${shellMotion} ${active ? "font-semibold" : "font-medium"}`}
                  >
                    {t(`nav.${item.id}.label`)}
                  </span>
                </a>
              </li>
            );
          })}
        </ul>
      </nav>

    </aside>
  );
}
