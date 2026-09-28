import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Served by FastAPI at /app, so assets must resolve under that base.
var API = "http://localhost:8100";
var proxy = Object.fromEntries(["/chat", "/docs", "/tasks", "/reminders", "/voice", "/health", "/mcp", "/skills", "/tools"].map(function (p) { return [p, { target: API, changeOrigin: true }]; }));
export default defineConfig({
    base: "/app/",
    plugins: [react()],
    server: { port: 5173, proxy: proxy },
});
