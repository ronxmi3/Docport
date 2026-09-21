import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#09111f",
        panel: "#101c2d",
        raised: "#142238",
        line: "#253752",
        ink: "#edf5ff",
        muted: "#91a4bf",
        cyan: "#4cc9f0",
        success: "#46d8a3",
        warning: "#f5b84b",
        danger: "#ff7070",
      },
      boxShadow: {
        panel: "0 16px 40px rgba(0, 0, 0, 0.18)",
      },
    },
  },
  plugins: [],
};

export default config;
