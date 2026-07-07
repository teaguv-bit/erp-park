import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/tiny": { target: "http://localhost:8080", changeOrigin: true },
      "/quotes": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});