import { defineConfig } from "vite";

// A static site with two pages: `pnpm build` (run in site/) writes dist/, which Vercel serves as-is.
export default defineConfig({
  base: "./",
  build: {
    target: "es2022",
    rollupOptions: { input: { main: "index.html", how: "how.html" } },
  },
});
