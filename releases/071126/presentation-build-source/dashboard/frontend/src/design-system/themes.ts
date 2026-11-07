import {
  darkColors,
  darkShadow,
  darkStatus,
  fontFamily,
  lightColors,
  lightStatus,
  motion,
  radius,
  shadow,
  type ColorTokens,
} from "./tokens";

export type ThemeMode = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export type ThemeDefinition = {
  colors: ColorTokens;
  cssVars: Record<string, string>;
};

type ShadowTokens = {
  sm: string;
  md: string;
  lg: string;
  glass: string;
  neu: string;
};

type StatusTokens = {
  healthy: string;
  warning: string;
  error: string;
  running: string;
  idle: string;
};

function toCssVars(
  colors: ColorTokens,
  shadows: ShadowTokens,
  status: StatusTokens,
): Record<string, string> {
  const vars: Record<string, string> = {
    "--ds-color-background": colors.background,
    "--ds-color-surface": colors.surface,
    "--ds-color-surface-secondary": colors.surfaceSecondary,
    "--ds-color-surface-elevated": colors.surfaceElevated,
    "--ds-color-text-primary": colors.textPrimary,
    "--ds-color-text-secondary": colors.textSecondary,
    "--ds-color-text-tertiary": colors.textTertiary,
    "--ds-color-border": colors.border,
    "--ds-color-accent": colors.accent,
    "--ds-font-display": fontFamily.display,
    "--ds-font-text": fontFamily.text,
    "--ds-font-mono": fontFamily.mono,
    "--ds-radius-card": radius.card,
    "--ds-radius-button": radius.button,
    "--ds-radius-input": radius.input,
    "--ds-radius-pill": radius.pill,
    "--ds-shadow-sm": shadows.sm,
    "--ds-shadow-md": shadows.md,
    "--ds-shadow-lg": shadows.lg,
    "--ds-shadow-glass": shadows.glass,
    "--ds-shadow-neu": shadows.neu,
    "--ds-motion-duration": motion.duration,
    "--ds-motion-easing": motion.easing,
    "--ds-status-healthy": status.healthy,
    "--ds-status-warning": status.warning,
    "--ds-status-error": status.error,
    "--ds-status-running": status.running,
    "--ds-status-idle": status.idle,
  };

  return vars;
}

export const themes: Record<ResolvedTheme, ThemeDefinition> = {
  light: {
    colors: lightColors,
    cssVars: toCssVars(lightColors, shadow, lightStatus),
  },
  dark: {
    colors: darkColors,
    cssVars: toCssVars(darkColors, darkShadow, darkStatus),
  },
};

export const THEME_STORAGE_KEY = "btc-ml.theme-mode";
