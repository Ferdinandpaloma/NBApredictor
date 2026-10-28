import { resolve } from "node:path";
import { defineConfig } from "vite";

// web/   the two pages and their JS (built by Vite)
// site/  data written by the Python builds, copied into the output as-is
export default defineConfig({
  root: "web",
  publicDir: resolve(import.meta.dirname, "site"),
  envDir: import.meta.dirname,
  base: "./",  // relative URLs, so the build works on Vercel and GitHub Pages alike
  build: {
    outDir: resolve(import.meta.dirname, "dist"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 700,  // the Firebase SDK chunk; it loads after the page
    rollupOptions: {
      input: {
        index: resolve(import.meta.dirname, "web/index.html"),
        props: resolve(import.meta.dirname, "web/props.html"),
      },
    },
  },
});
