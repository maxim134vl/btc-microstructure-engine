import type { ReactNode } from "react";

type MainContentProps = {
  children: ReactNode;
  fullBleed?: boolean;
  /** When true, children render directly on ds-background (no command-bg island). */
  nativeSurface?: boolean;
  /** When true, main fills the viewport and children participate in flex height allocation. */
  viewportFill?: boolean;
};

export function MainContent({
  children,
  fullBleed = false,
  nativeSurface = false,
  viewportFill = false,
}: MainContentProps) {
  if (fullBleed) {
    return (
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-ds-background p-4">
        <div className="ds-neu-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-ds-card bg-ds-surface">
          <div className="ds-panel-content flex min-h-0 flex-1 flex-col overflow-hidden p-2">{children}</div>
        </div>
      </main>
    );
  }

  if (nativeSurface && viewportFill) {
    return (
      <main className="panel-scroll flex min-h-0 flex-1 flex-col overflow-y-auto bg-ds-background p-0">
        {children}
      </main>
    );
  }

  if (nativeSurface) {
    return (
      <main className="panel-scroll flex-1 overflow-y-auto bg-ds-background p-0">
        {children}
      </main>
    );
  }

  return (
    <main className="panel-scroll flex-1 overflow-y-auto bg-ds-background px-6 py-6">
      <div className="mx-auto w-full max-w-7xl">
        <div className="ds-neu-card ds-panel-content rounded-ds-card bg-ds-surface p-4">{children}</div>
      </div>
    </main>
  );
}
