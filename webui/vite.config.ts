import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import {
  mountWebuiPath,
  normalizeWebuiBasePath,
  toViteBasePath,
} from "./base-path";

export function webuiManualChunk(id: string): string | undefined {
  if (id.includes("node_modules/refractor/lang/")) {
    return;
  }
  // Streamdown lazy-loads diagrams and highlighted code. Keep those modules
  // outside the core markdown chunk so ordinary replies do not download them.
  if (
    id.includes("node_modules/streamdown/dist/mermaid-")
    || id.includes("node_modules/streamdown/dist/highlighted-body-")
  ) {
    return;
  }
  // Refractor reaches this HAST helper through hastscript. Keeping it with
  // Refractor prevents syntax-highlight <-> markdown-vendor circular chunks.
  if (
    id.includes("node_modules/react-syntax-highlighter")
    || id.includes("node_modules/refractor/core")
    || id.includes("node_modules/hast-util-parse-selector")
  ) {
    return "syntax-highlight";
  }
  if (
    id.includes("node_modules/streamdown")
    || id.includes("node_modules/remend")
    || id.includes("node_modules/remark-")
    || id.includes("node_modules/rehype-")
    || id.includes("node_modules/unified")
    || id.includes("node_modules/mdast-")
    || id.includes("node_modules/hast-")
    || id.includes("node_modules/micromark")
    || id.includes("node_modules/unist-")
  ) {
    return "markdown-vendor";
  }
  if (id.includes("node_modules/katex")) {
    return "katex";
  }
}

export function resolveWebuiVitePaths(baseValue?: string | null) {
  const runtimeBase = normalizeWebuiBasePath(baseValue);
  return {
    runtimeBase,
    viteBase: toViteBasePath(runtimeBase),
    hmrPath: mountWebuiPath(runtimeBase, "/__nanobot_vite_hmr"),
    apiPath: mountWebuiPath(runtimeBase, "/api"),
    authPath: mountWebuiPath(runtimeBase, "/auth"),
    bootstrapPath: mountWebuiPath(runtimeBase, "/webui"),
  };
}

function webuiBuildMetadataPlugin(runtimeBase: string): Plugin {
  return {
    name: "nanobot-webui-build-metadata",
    generateBundle() {
      this.emitFile({
        type: "asset" as const,
        fileName: ".nanobot-webui-build.json",
        source: `${JSON.stringify({ base: runtimeBase })}\n`,
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.NANOBOT_API_URL ?? "http://127.0.0.1:8765";
  const paths = resolveWebuiVitePaths(env.VITE_BASE_PATH);

  return {
    base: paths.viteBase,
    plugins: [react(), webuiBuildMetadataPlugin(paths.runtimeBase)],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
      // Channel-owned UI lives beside the Python package, outside webui/.
      // Resolve its shared frontend dependencies from this app's root.
      dedupe: ["react", "react-dom", "lucide-react", "react-i18next", "qrcode"],
    },
    optimizeDeps: {
      // Radix Dialog can rewrite its optimized chunk while a dev tab is open.
      // Syntax highlighting must remain pre-bundled because Refractor's core
      // still uses CommonJS internally.
      exclude: ["@radix-ui/react-dialog"],
    },
    build: {
      outDir: path.resolve(__dirname, "../nanobot/web/dist"),
      emptyOutDir: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks: webuiManualChunk,
        },
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      fs: {
        allow: [path.resolve(__dirname, "..")],
      },
      // Keep Vite's HMR socket on a dedicated path. Nanobot's app WebSocket is
      // opened directly from the browser to the gateway, so the dev server
      // should never proxy WebSocket upgrades.
      hmr: {
        host: "127.0.0.1",
        path: paths.hmrPath,
      },
      proxy: {
        [paths.bootstrapPath]: { target, changeOrigin: true },
        [paths.apiPath]: { target, changeOrigin: true },
        [paths.authPath]: { target, changeOrigin: true },
      },
    },
    test: {
      environment: "happy-dom",
      globals: true,
      setupFiles: ["./src/tests/setup.ts"],
    },
  };
});
