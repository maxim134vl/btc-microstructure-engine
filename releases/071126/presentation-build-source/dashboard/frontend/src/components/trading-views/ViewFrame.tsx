import type { ReactNode } from "react";

export function ViewFrame({
  fillWindow = false,
  children,
}: {
  fillWindow?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="ops-surface min-h-full">
      <div className={`mx-auto space-y-5 p-5 ${fillWindow ? "w-full max-w-none" : "max-w-[1120px]"}`}>
        {children}
      </div>
    </div>
  );
}
