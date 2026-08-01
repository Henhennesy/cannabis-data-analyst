import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Same-origin in dev, so the browser sees one host and there is no CORS
      // preflight on the streaming POST. Caddy plays this role in deployment,
      // which keeps dev and prod the same shape.
      "/api": {
        // Override with VITE_API_TARGET when 8000 is taken -- Windows will
        // occasionally keep a listening socket alive after its process dies,
        // and that should not block development.
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        // SSE must not be buffered by the proxy or the stream arrives as one
        // blob at the end -- the whole point of streaming would be lost.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              delete proxyRes.headers["content-length"];
            }
          });
        },
      },
    },
  },
});
