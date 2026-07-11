/** Apple-style design tokens — foundation only; screens opt in during later phases. */

export const fontFamily = {
  display:
    '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", system-ui, sans-serif',
  text: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", system-ui, sans-serif',
  mono: 'ui-monospace, "SF Mono", Menlo, monospace',
} as const;

export const fontSize = {
  pageTitle: "26px",
  panelTitle: "15px",
  body: "13px",
  caption: "11px",
} as const;

export const lineHeight = {
  tight: 1.2,
  normal: 1.45,
  relaxed: 1.6,
} as const;

export const fontWeight = {
  regular: 400,
  medium: 500,
  semibold: 600,
} as const;

export const radius = {
  card: "20px",
  button: "12px",
  input: "10px",
  pill: "9999px",
} as const;

export const shadow = {
  sm: "0 1px 2px rgba(0, 0, 0, 0.04), 0 0 0 0.5px rgba(0, 0, 0, 0.03)",
  md: "0 1px 2px rgba(0, 0, 0, 0.03), 0 2px 8px rgba(0, 0, 0, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.65)",
  lg: "0 2px 4px rgba(0, 0, 0, 0.04), 0 8px 20px rgba(0, 0, 0, 0.07), inset 0 1px 0 rgba(255, 255, 255, 0.75)",
  glass: "0 4px 16px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.7)",
  neu: "0 1px 2px rgba(0, 0, 0, 0.03), 0 2px 8px rgba(0, 0, 0, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.65)",
} as const;

export const motion = {
  duration: "200ms",
  easing: "cubic-bezier(0.25, 0.1, 0.25, 1)",
} as const;

export type ColorTokens = {
  background: string;
  surface: string;
  surfaceSecondary: string;
  surfaceElevated: string;
  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  border: string;
  accent: string;
};

export const lightColors: ColorTokens = {
  background: "#f5f5f7",
  surface: "#ffffff",
  surfaceSecondary: "#efeff4",
  surfaceElevated: "#ffffff",
  textPrimary: "#1d1d1f",
  textSecondary: "#3a3a3c",
  textTertiary: "#6e6e73",
  border: "rgba(0, 0, 0, 0.08)",
  accent: "#007aff",
};

/** Premium dark palette — Arc / Linear / Apple Pro Apps */
export const darkColors: ColorTokens = {
  background: "#111315",
  surfaceSecondary: "#151922",
  surface: "#1b2028",
  surfaceElevated: "#232933",
  textPrimary: "#f5f5f7",
  textSecondary: "#a1a6b0",
  textTertiary: "#6e7380",
  border: "rgba(255, 255, 255, 0.06)",
  accent: "#0a84ff",
};

export const darkShadow = {
  sm: "0 1px 2px rgba(0, 0, 0, 0.32), 0 0 0 0.5px rgba(255, 255, 255, 0.04)",
  md: "0 1px 3px rgba(0, 0, 0, 0.28), 0 4px 12px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.04)",
  lg: "0 2px 6px rgba(0, 0, 0, 0.35), 0 8px 20px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.05)",
  glass: "0 8px 28px rgba(0, 0, 0, 0.45)",
  neu: "0 1px 3px rgba(0, 0, 0, 0.28), 0 4px 12px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.04)",
} as const;

/** Apple Health–style status hues — light mode */
export const lightStatus = {
  healthy: "#34c759",
  warning: "#ff9500",
  error: "#ff3b30",
  running: "#007aff",
  idle: "#8e8e93",
} as const;

/** Calm operational, clear warning/critical — dark mode */
export const darkStatus = {
  healthy: "#30d158",
  warning: "#ff9f0a",
  error: "#ff453a",
  running: "#0a84ff",
  idle: "#98989d",
} as const;

export const typography = {
  fontFamily,
  fontSize,
  lineHeight,
  fontWeight,
} as const;

export const tokens = {
  typography,
  radius,
  shadow,
  motion,
  colors: {
    light: lightColors,
    dark: darkColors,
  },
} as const;
