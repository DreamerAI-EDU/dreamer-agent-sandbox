import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { inspectAttr } from 'kimi-plugin-inspect-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  base: '/', // runbook §6 鐵律 1：絕對路徑 assets，深層路由（/teacher）先唔會白屏
  plugins: [mode === 'development' ? inspectAttr() : null, react()].filter(Boolean),
  server: {
    port: 3000,
    // W2 PR#6 — dev proxy to the real aiohttp backend on localhost:8001.
    // /legal/* is proxied too so embedded legal pages render in dev.
    proxy: {
      '/api': 'http://localhost:8001',
      '/legal': 'http://localhost:8001',
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
