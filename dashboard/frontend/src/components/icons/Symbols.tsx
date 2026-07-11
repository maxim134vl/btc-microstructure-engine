import type { SVGProps, ReactElement } from "react";

type SymbolProps = SVGProps<SVGSVGElement> & { className?: string };

function Base({ className = "", children, ...props }: SymbolProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden
      {...props}
    >
      {children}
    </svg>
  );
}

export function SymbolPulse({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M3 10h2.5l1.5-4 2.5 8 2-5.5L13 10H17" />
    </Base>
  );
}

export function SymbolTerminal({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="14" height="12" rx="2" />
      <path d="M6.5 9.5 8.5 11.5 6.5 13.5M10.5 13.5H13" />
    </Base>
  );
}

export function SymbolCheckShield({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 3.5 15 5.5V10c0 3-2.2 5.2-5 6.5-2.8-1.3-5-3.5-5-6.5V5.5L10 3.5Z" />
      <path d="m7.5 10 1.75 1.75L12.5 8.5" />
    </Base>
  );
}

export function SymbolEyeChart({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3.5 10s2.5-4 6.5-4 6.5 4 6.5 4-2.5 4-6.5 4-6.5-4-6.5-4Z" />
      <circle cx="10" cy="10" r="2" />
      <path d="M14.5 5.5 16 4M16 4v2" />
    </Base>
  );
}

export function SymbolListDoc({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M6.5 4.5h7a1.5 1.5 0 0 1 1.5 1.5v9a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 5 15V6a1.5 1.5 0 0 1 1.5-1.5Z" />
      <path d="M7.5 8.5h5M7.5 11h5M7.5 13.5h3" />
    </Base>
  );
}

export function SymbolBrain({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7.5 5.5a2.5 2.5 0 0 1 4.5 1.5 2.8 2.8 0 0 1 1.8 4.8A3 3 0 0 1 10 15.5 3 3 0 0 1 6.2 11.8 2.8 2.8 0 0 1 7.5 5.5Z" />
      <path d="M10 8v3.5M8.5 9.75h3" />
    </Base>
  );
}

export function SymbolHeart({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 16.5S4 12.5 4 8.75A3.25 3.25 0 0 1 10 6.5a3.25 3.25 0 0 1 6 2.25C16 12.5 10 16.5 10 16.5Z" />
    </Base>
  );
}

export function SymbolMemory({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <rect x="4" y="4" width="12" height="12" rx="2" />
      <path d="M7 4v12M10 4v12M13 4v12M4 7h12M4 10h12M4 13h12" />
    </Base>
  );
}

export function SymbolPipeline({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5" cy="10" r="2" />
      <circle cx="10" cy="10" r="2" />
      <circle cx="15" cy="10" r="2" />
      <path d="M7 10h1M11 10h1" />
    </Base>
  );
}

export function SymbolBell({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 4a3.5 3.5 0 0 1 3.5 3.5v2.5l1.5 2.5H5l1.5-2.5V7.5A3.5 3.5 0 0 1 10 4Z" />
      <path d="M8.5 15a1.5 1.5 0 0 0 3 0" />
    </Base>
  );
}

export function SymbolCpu({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <rect x="6" y="6" width="8" height="8" rx="1.5" />
      <path d="M8 6V4M10 6V4M12 6V4M8 16v2M10 16v2M12 16v2M6 8H4M6 10H4M6 12H4M16 8h2M16 10h2M16 12h2" />
    </Base>
  );
}

export function SymbolEngine({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="10" cy="10" r="3" />
      <path d="M10 3v2M10 15v2M3 10h2M15 10h2M5.05 5.05l1.42 1.42M13.53 13.53l1.42 1.42M5.05 14.95l1.42-1.42M13.53 6.47l1.42-1.42" />
    </Base>
  );
}

export function SymbolAntenna({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M10 16V8M10 8 7.5 10.5M10 8l2.5 2.5" />
      <path d="M6 12.5a4 4 0 0 1 8 0M4 10a7 7 0 0 1 12 0" />
    </Base>
  );
}

export function SymbolDatabase({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <ellipse cx="10" cy="5.5" rx="5.5" ry="2" />
      <path d="M4.5 5.5V14c0 1.1 2.46 2 5.5 2s5.5-.9 5.5-2V5.5" />
      <path d="M4.5 10c0 1.1 2.46 2 5.5 2s5.5-.9 5.5-2" />
    </Base>
  );
}

export function SymbolClock({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <circle cx="10" cy="10" r="6.5" />
      <path d="M10 6.5V10l2.5 2" />
    </Base>
  );
}

export function SymbolWifi({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M4 8.5a8.5 8.5 0 0 1 12 0M6.5 11a5.5 5.5 0 0 1 7 0M10 14.5h.01" />
      <circle cx="10" cy="14.5" r="0.75" fill="currentColor" stroke="none" />
    </Base>
  );
}

export function SymbolWaveform({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M3 10h1.5l1-3 1.5 6 1.5-4 1 2.5H11l1-2.5 1.5 4 1-3H17" />
    </Base>
  );
}

export function SymbolLayers({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 4 4.5 7 10 10l5.5-3L10 4Z" />
      <path d="m4.5 10.5 5.5 3 5.5-3M4.5 14 10 17l5.5-3" />
    </Base>
  );
}

/** Product logo mark — used in sidebar identity block. */
export function ProductLogoMark({ className = "h-9 w-9" }: SymbolProps) {
  return (
    <svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" className={className} aria-hidden>
      <defs>
        <linearGradient id="btcml-mark-gradient" x1="4" y1="4" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#007AFF" />
          <stop offset="1" stopColor="#5856D6" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="34" height="34" rx="10" fill="url(#btcml-mark-gradient)" />
      <rect x="1" y="1" width="34" height="34" rx="10" stroke="rgba(255,255,255,0.18)" strokeWidth="0.5" />
      <circle cx="12" cy="14" r="2.5" stroke="white" strokeWidth="1.5" />
      <circle cx="24" cy="12" r="2.5" stroke="white" strokeWidth="1.5" />
      <circle cx="18" cy="24" r="2.5" stroke="white" strokeWidth="1.5" />
      <path d="M14 14.5 21.5 12M14.5 16 16.5 22M21.5 14.5 16.5 22" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function SymbolOperations({ className = "h-[18px] w-[18px]" }: SymbolProps) {
  return (
    <Base className={className} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3.5" y="3.5" width="5.5" height="5.5" rx="1.25" />
      <rect x="11" y="3.5" width="5.5" height="5.5" rx="1.25" />
      <rect x="3.5" y="11" width="5.5" height="5.5" rx="1.25" />
      <rect x="11" y="11" width="5.5" height="5.5" rx="1.25" />
    </Base>
  );
}

export type NavSymbolId =
  | "operations"
  | "pulse"
  | "terminal"
  | "check-shield"
  | "eye-chart"
  | "list-doc"
  | "brain";

const NAV_SYMBOLS: Record<NavSymbolId, (props: SymbolProps) => ReactElement> = {
  operations: SymbolOperations,
  pulse: SymbolPulse,
  terminal: SymbolTerminal,
  "check-shield": SymbolCheckShield,
  "eye-chart": SymbolEyeChart,
  "list-doc": SymbolListDoc,
  brain: SymbolBrain,
};

export function NavSymbol({ id, className }: { id: NavSymbolId; className?: string }) {
  const Icon = NAV_SYMBOLS[id];
  return <Icon className={className ?? "h-[18px] w-[18px]"} />;
}
