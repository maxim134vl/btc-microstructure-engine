export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        command: {
          bg: "var(--command-bg)",
          panel: "var(--command-panel)",
          border: "var(--command-border)",
          muted: "var(--command-muted)",
          text: "var(--command-text)",
          accent: "var(--command-accent)",
          green: "var(--command-green)",
          yellow: "var(--command-yellow)",
          red: "var(--command-red)",
        },
        ds: {
          background: "var(--ds-color-background)",
          surface: "var(--ds-color-surface)",
          "surface-secondary": "var(--ds-color-surface-secondary)",
          "surface-elevated": "var(--ds-color-surface-elevated)",
          "text-primary": "var(--ds-color-text-primary)",
          "text-secondary": "var(--ds-color-text-secondary)",
          "text-tertiary": "var(--ds-color-text-tertiary)",
          border: "var(--ds-color-border)",
          accent: "var(--ds-color-accent)",
        },
        "ds-status": {
          healthy: "var(--ds-status-healthy)",
          warning: "var(--ds-status-warning)",
          error: "var(--ds-status-error)",
          running: "var(--ds-status-running)",
          idle: "var(--ds-status-idle)",
        },
      },
      fontFamily: {
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        "ds-display": ["var(--ds-font-display)"],
        "ds-text": ["var(--ds-font-text)"],
        "ds-mono": ["var(--ds-font-mono)"],
      },
      borderRadius: {
        "ds-card": "var(--ds-radius-card)",
        "ds-button": "var(--ds-radius-button)",
        "ds-input": "var(--ds-radius-input)",
        "ds-pill": "var(--ds-radius-pill)",
      },
      boxShadow: {
        "ds-sm": "var(--ds-shadow-sm)",
        "ds-md": "var(--ds-shadow-md)",
        "ds-lg": "var(--ds-shadow-lg)",
        "ds-glass": "var(--ds-shadow-glass)",
        "ds-neu": "var(--ds-shadow-neu)",
      },
      transitionDuration: {
        ds: "var(--ds-motion-duration)",
      },
      transitionTimingFunction: {
        ds: "var(--ds-motion-easing)",
      },
    },
  },
  plugins: [],
};
