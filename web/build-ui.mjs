import { build } from "esbuild";
import { fileURLToPath } from "node:url";

await build({
  entryPoints: [fileURLToPath(new URL("./ui/app.js", import.meta.url))],
  outfile: fileURLToPath(new URL("../webapp/static/app.js", import.meta.url)),
  bundle: true,
  platform: "browser",
  format: "iife",
  target: ["es2022"],
  minify: true,
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "inline",
  banner: { js: "// Generated from web/ui/app.js. Run npm run build --prefix web." },
});
