import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Design token system – single source of truth for the dark theme
        surface: {
          DEFAULT: "#0d0d0f",
          raised: "#141418",
          overlay: "#1c1c22",
          border: "#2a2a35",
        },
        brand: {
          DEFAULT: "#6366f1",
          dim: "#4f46e5",
          glow: "rgba(99,102,241,0.15)",
        },
        severity: {
          critical: "#ef4444",
          high: "#f97316",
          medium: "#eab308",
          low: "#3b82f6",
          info: "#6b7280",
        },
        agent: {
          idle: "#2a2a35",
          active: "#6366f1",
          done: "#22c55e",
          error: "#ef4444",
          waiting: "#eab308",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "glow-in": "glowIn 0.4s ease-out forwards",
        "fade-up": "fadeUp 0.3s ease-out forwards",
      },
      keyframes: {
        glowIn: {
          "0%": { boxShadow: "0 0 0px rgba(99,102,241,0)" },
          "100%": { boxShadow: "0 0 20px rgba(99,102,241,0.4)" },
        },
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
