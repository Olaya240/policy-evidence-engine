import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publicRoot = path.join(frontendRoot, "public");
const distRoot = path.join(frontendRoot, "dist");
const standalonePage = "policy-comparison-demo.html";

async function listFiles(directory, prefix = "") {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const relativePath = path.join(prefix, entry.name);
    if (entry.isDirectory()) files.push(...await listFiles(path.join(directory, entry.name), relativePath));
    else if (entry.isFile()) files.push(relativePath);
  }
  return files;
}

test("production build omits only the standalone local policy page", async () => {
  const sourcePath = path.join(publicRoot, standalonePage);
  const source = await readFile(sourcePath, "utf8");
  const viteConfig = await readFile(path.join(frontendRoot, "vite.config.ts"), "utf8");
  assert.match(viteConfig, /apply:\s*"build"/);
  assert.doesNotMatch(viteConfig, /copyPublicDir\s*:\s*false/);
  assert.match(source, /https?:\/\/127\.0\.0\.1:8082\/policy-comparisons/);
  assert.equal((await stat(sourcePath)).isFile(), true);

  await assert.rejects(stat(path.join(distRoot, standalonePage)), { code: "ENOENT" });

  const indexHtml = await readFile(path.join(distRoot, "index.html"), "utf8");
  const assetPaths = [...indexHtml.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)]
    .map((match) => match[1].replace(/^\//, ""));
  assert.ok(assetPaths.some((asset) => asset.endsWith(".js")), "index.html references a JS bundle");
  assert.ok(assetPaths.some((asset) => asset.endsWith(".css")), "index.html references a CSS bundle");
  for (const asset of assetPaths) {
    assert.equal((await stat(path.join(distRoot, asset))).isFile(), true, `${asset} exists`);
  }

  const otherPublicFiles = (await listFiles(publicRoot)).filter((file) => file !== standalonePage);
  for (const file of otherPublicFiles) {
    const sourceAsset = await readFile(path.join(publicRoot, file));
    const builtAsset = await readFile(path.join(distRoot, file));
    assert.deepEqual(builtAsset, sourceAsset, `${file} is still copied to dist`);
  }
});
