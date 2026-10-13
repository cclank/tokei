// Count every script needed for the cards screen, including its dynamic app/config imports.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const manifest = JSON.parse(fs.readFileSync(path.join(dist, ".vite/manifest.json"), "utf8"));
function graph(roots) {
  const seen = new Set();
  const visit = (key) => {
    if (seen.has(key)) return;
    if (!manifest[key]) throw new Error(`Missing startup module: ${key}`);
    seen.add(key);
    for (const dependency of manifest[key].imports ?? []) visit(dependency);
  };
  roots.forEach(visit);
  return seen;
}
const roots = ["index.html", "src/App.tsx", "src/pages/settings/collectorConfig.ts"];
const initial = graph(roots);
for (const key of ["src/pages/Settings.tsx", "src/pages/Dashboard.tsx", "src/pages/Projects.tsx", "src/pages/QuotaHistory.tsx", "src/lib/share.tsx"]) {
  if (initial.has(key)) throw new Error(`Startup eagerly loads ${key}`);
}
const dictionary = (lang) => {
  const key = Object.keys(manifest).find((key) => key.includes(`/${lang}.lproj/`));
  if (!key) throw new Error(`Missing ${lang} language asset`);
  return key;
};
for (const lang of ["zh", "en", "fr", "ja", "ko"]) {
  const languages = lang === "zh" ? [] : lang === "en" ? [dictionary("en")] : [dictionary(lang), dictionary("en")];
  const scripts = graph([...roots, ...languages]);
  const files = [...new Set([...scripts].map((key) => manifest[key].file))];
  const bytes = files.reduce((total, file) => total + fs.statSync(path.join(dist, file)).size, 0);
  const budget = (lang === "zh" ? 400 : lang === "en" ? 450 : 500) * 1024;
  console.log(`startup ${lang}: ${(bytes / 1024).toFixed(1)} KiB / ${budget / 1024} KiB`);
  if (bytes > budget) throw new Error(`${lang} startup JavaScript exceeds its budget`);
}
