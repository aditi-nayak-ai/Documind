export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#f5f3ff",
          100: "#ede9fe",
          400: "#a78bfa",
          500: "#7c3aed",
          600: "#6d28d9",
          700: "#5b21b6",
          800: "#4c1d95",
        },
        surface: {
          900: "#0d0f1a",
          800: "#12151f",
          700: "#181c2a",
          600: "#1e2235",
        }
      },
      animation: {
        "spin-slow": "spin 3s linear infinite",
        "pulse-slow": "pulse 3s ease-in-out infinite",
      }
    },
  },
  plugins: [],
};
