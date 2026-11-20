/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f3f7f6",
          100: "#e2ece9",
          200: "#c3d5d0",
          300: "#9bb5ae",
          500: "#4d6f67",
          700: "#2a463f",
          900: "#0f1f1b",
        },
        accent: {
          DEFAULT: "#0e8f78",
          soft: "#d7f3eb",
          deep: "#0a6b5a",
        },
        coral: {
          DEFAULT: "#d94b3d",
          soft: "#fde8e5",
        },
        sand: {
          DEFAULT: "#f4f1ea",
          deep: "#e8e2d6",
        },
      },
      fontFamily: {
        sans: ['"Figtree"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Fraunces"', "Georgia", "serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        panel: "0 18px 50px rgba(15, 31, 27, 0.08)",
        soft: "0 8px 24px rgba(15, 31, 27, 0.06)",
        glow: "0 0 0 4px rgba(14, 143, 120, 0.12)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-dot": {
          "0%, 100%": { opacity: "0.35", transform: "scale(0.85)" },
          "50%": { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        wave: {
          "0%, 100%": { transform: "scaleY(0.35)" },
          "50%": { transform: "scaleY(1)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.45s ease-out both",
        "pulse-dot": "pulse-dot 1.2s ease-in-out infinite",
        shimmer: "shimmer 1.8s linear infinite",
        wave: "wave 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
