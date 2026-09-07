// Generated from design/tokens.json. Do not edit by hand.
export const designTokens = {
  "$schema": "./tokens.schema.json",
  "breakpoint": {
    "xsMax": "599px",
    "smMin": "600px",
    "smMax": "1023px",
    "mdMin": "1024px",
    "mdMax": "1439px",
    "lgMin": "1440px",
    "lgMax": "1919px",
    "xlMin": "1920px"
  },
  "space": {
    "0": "0",
    "1": "4px",
    "2": "8px",
    "3": "12px",
    "4": "16px",
    "5": "20px",
    "6": "24px",
    "8": "32px",
    "10": "40px",
    "12": "48px",
    "16": "64px"
  },
  "radius": {
    "sm": "6px",
    "md": "10px",
    "lg": "16px",
    "xl": "24px",
    "round": "999px"
  },
  "font": {
    "family": "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif",
    "sizeXs": "12px",
    "sizeSm": "14px",
    "sizeMd": "16px",
    "sizeLg": "18px",
    "sizeXl": "24px",
    "sizeDisplay": "36px",
    "lineCompact": "1.3",
    "lineNormal": "1.6"
  },
  "motion": {
    "fast": "120ms",
    "normal": "200ms",
    "slow": "320ms",
    "ease": "cubic-bezier(0.2, 0, 0, 1)"
  },
  "zIndex": {
    "base": 0,
    "sticky": 10,
    "header": 20,
    "drawer": 30,
    "dialog": 100,
    "toast": 120
  },
  "theme": {
    "light": {
      "bgCanvas": "#f6f8f7",
      "bgSurface": "#ffffff",
      "bgSubtle": "#f0f6f2",
      "textPrimary": "#172033",
      "textSecondary": "#5f6878",
      "textMuted": "#8a93a3",
      "borderDefault": "#dfe5e2",
      "borderStrong": "#c8d1cc",
      "actionPrimary": "#08a83d",
      "actionPrimaryHover": "#078c35",
      "actionPrimaryText": "#ffffff",
      "success": "#129a46",
      "warning": "#d88918",
      "danger": "#d94444",
      "info": "#2678e3",
      "focus": "#2f80ed",
      "overlay": "rgba(16, 24, 40, 0.56)",
      "shadow": "0 12px 40px rgba(26, 45, 34, 0.12)"
    },
    "dark": {
      "bgCanvas": "#111714",
      "bgSurface": "#18211d",
      "bgSubtle": "#202c26",
      "textPrimary": "#f3f7f5",
      "textSecondary": "#c0cac4",
      "textMuted": "#8e9c94",
      "borderDefault": "#334139",
      "borderStrong": "#45564c",
      "actionPrimary": "#32c765",
      "actionPrimaryHover": "#51d47a",
      "actionPrimaryText": "#07150d",
      "success": "#49cf77",
      "warning": "#efad4c",
      "danger": "#f06a6a",
      "info": "#70a9f4",
      "focus": "#82b5ff",
      "overlay": "rgba(0, 0, 0, 0.7)",
      "shadow": "0 12px 40px rgba(0, 0, 0, 0.38)"
    }
  }
} as const

export type ThemePreference = 'light' | 'dark' | 'system'
