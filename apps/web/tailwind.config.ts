import type { Config } from "tailwindcss";
import colors from "tailwindcss/colors";

// Multi Agentic Company brand: white surfaces + shiny orange accents.
// The UI was written with blue/indigo/violet/purple/sky as its "primary"
// accent classes; mapping those palettes to the brand orange re-themes every
// button, link, badge and focus ring consistently in one place. Semantic
// colours (green = success, red = danger, amber = warning) are unchanged.
const brand = {
  50: "#fff7ed",
  100: "#ffedd5",
  200: "#fed7aa",
  300: "#fdba74",
  400: "#fb923c",
  500: "#f97316",
  600: "#ea580c",
  700: "#c2410c",
  800: "#9a3412",
  900: "#7c2d12",
  950: "#431407",
};

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand,
        blue: brand,
        indigo: brand,
        violet: brand,
        purple: brand,
        sky: brand,
        orange: colors.orange,
      },
      fontFamily: {
        arcade: ["var(--font-arcade)", "ui-monospace", "monospace"],
        sans: [
          "var(--font-sans)",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(15,23,42,0.04), 0 8px 24px -12px rgba(15,23,42,0.12)",
        glow: "0 10px 30px -10px rgba(249,115,22,0.55)",
      },
      keyframes: {
        shine: {
          "0%": { transform: "translateX(-120%) skewX(-20deg)" },
          "100%": { transform: "translateX(220%) skewX(-20deg)" },
        },
        floaty: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
        pulseDot: {
          "0%,100%": { opacity: "0.35" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        shine: "shine 2.8s ease-in-out infinite",
        floaty: "floaty 4s ease-in-out infinite",
        pulseDot: "pulseDot 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
