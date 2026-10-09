import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const host = process.env.TAURI_DEV_HOST;
const repoRoot = path.resolve(__dirname, "..");

/**
 * 单独用浏览器开 vite 调界面时（不经过 Tauri），让 /__tokei/collect 跑一遍仓库里的
 * usage.30s.py，前端照常拿到真实数据。只在 dev server 里生效，不进打包产物。
 */
function devCollector(): Plugin {
  return {
    name: "tokei-dev-collector",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/__tokei/collect", (req, res) => {
        const url = new URL(req.url ?? "", "http://localhost");
        const args = url.searchParams.getAll("arg");
        const python = process.env.TOKEI_PYTHON || (process.platform === "win32" ? "python" : "python3");
        const child = spawn(python, [path.join(repoRoot, "usage.30s.py"), ...args], {
          env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
        });
        const out: Buffer[] = [];
        const err: Buffer[] = [];
        child.stdout.on("data", (chunk: Buffer) => out.push(chunk));
        child.stderr.on("data", (chunk: Buffer) => err.push(chunk));
        child.on("close", (code) => {
          res.statusCode = code === 0 ? 200 : 500;
          res.setHeader("Content-Type", "text/plain; charset=utf-8");
          res.end(Buffer.concat(code === 0 ? out : err));
        });
      });
    },
  };
}

// https://vite.dev/config/
export default defineConfig(() => ({
  plugins: [react(), devCollector()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
    // 词表直接读 Mac 版的 Tokei/Localization，在仓库根目录下。
    fs: { allow: [repoRoot] },
  },
}));
