import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// The build ships inside the Python package so readers never need Node.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { outDir: "../src/plugai_trade/web_dist", emptyOutDir: true, chunkSizeWarningLimit: 1600 },
  server: { port: 5173, proxy: { "/api": "http://localhost:8501" } },
});
