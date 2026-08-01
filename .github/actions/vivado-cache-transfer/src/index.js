// SPDX-License-Identifier: MIT

import * as cache from "@actions/cache";
import * as core from "@actions/core";
import fs from "node:fs/promises";
import path from "node:path";
import { parseManifest } from "./manifest.js";

async function readManifest(cacheRoot) {
  const manifestPath = path.join(cacheRoot, "manifest", "toolchain.env");
  return parseManifest(await fs.readFile(manifestPath, "ascii"));
}

async function clearCacheRoot(cacheRoot) {
  await fs.rm(cacheRoot, { recursive: true, force: true });
  await fs.mkdir(path.join(cacheRoot, "manifest"), { recursive: true });
}

async function restore(cacheRoot, key, cacheClient = cache) {
  await clearCacheRoot(cacheRoot);
  const manifestRoot = path.join(cacheRoot, "manifest");
  const lookupKey = `${key}-manifest-lookup-${process.env.GITHUB_RUN_ID}`;
  const matchedManifest = await cacheClient.restoreCache(
    [manifestRoot],
    lookupKey,
    [`${key}-manifest-`],
  );
  if (!matchedManifest) return false;

  const manifest = await readManifest(cacheRoot);
  if (matchedManifest !== `${key}-manifest-${manifest.generation}`) {
    throw new Error("restored manifest key does not match its generation");
  }

  const partsRoot = path.join(cacheRoot, "parts");
  await fs.mkdir(partsRoot, { recursive: true });
  for (const part of manifest.parts) {
    const partPath = path.join(partsRoot, part.name);
    const partKey = `${key}-${part.name}-${manifest.generation}`;
    const matchedPart = await cacheClient.restoreCache([partPath], partKey);
    if (matchedPart !== partKey) {
      core.warning(`Vivado cache segment is unavailable: ${part.name}`);
      await fs.rm(partsRoot, { recursive: true, force: true });
      return false;
    }
  }
  return true;
}

async function save(cacheRoot, key, generation, cacheClient = cache) {
  const manifest = await readManifest(cacheRoot);
  if (manifest.generation !== generation) {
    throw new Error("cache generation input does not match the manifest");
  }

  const partsRoot = path.join(cacheRoot, "parts");
  for (const part of manifest.parts) {
    const partPath = path.join(partsRoot, part.name);
    await fs.access(partPath);
    await savePath(cacheClient, [partPath], `${key}-${part.name}-${generation}`);
  }
  await savePath(
    cacheClient,
    [path.join(cacheRoot, "manifest")],
    `${key}-manifest-${generation}`,
  );
}

async function savePath(cacheClient, paths, key) {
  try {
    await cacheClient.saveCache(paths, key);
  } catch (error) {
    if (error instanceof cache.ReserveCacheError) {
      core.warning(error.message);
      return;
    }
    throw error;
  }
}

async function run() {
  const mode = core.getInput("mode", { required: true });
  const key = core.getInput("key", { required: true });
  const generation = core.getInput("generation");
  const cacheRoot = path.resolve(core.getInput("cache-root", { required: true }));
  if (!cache.isFeatureAvailable()) throw new Error("GitHub Actions cache service is unavailable");

  if (mode === "restore") {
    let restored = false;
    try {
      restored = await restore(cacheRoot, key);
    } catch (error) {
      core.warning(`Vivado cache restore was rejected: ${error.message}`);
      await clearCacheRoot(cacheRoot);
    }
    core.setOutput("cache-restored", String(restored));
    return;
  }
  if (mode === "save") {
    if (!generation) throw new Error("generation is required when saving cache segments");
    await save(cacheRoot, key, generation);
    return;
  }
  throw new Error(`unsupported cache transfer mode: ${mode}`);
}

if (process.env.ANTSDR_CACHE_ACTION_TEST !== "1") {
  run().catch((error) => core.setFailed(error.message));
}

export { restore, save };
