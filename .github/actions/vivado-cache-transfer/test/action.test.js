// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

process.env.ANTSDR_CACHE_ACTION_TEST = "1";
process.env.GITHUB_RUN_ID = "999";
const { restore, save } = await import("../src/index.js");

const HASH = "a".repeat(64);

function manifest(generation, count) {
  const lines = [
    "schema=2",
    `generation=${generation}`,
    `parts=${count}`,
    "part_suffix_length=6",
    `archive_sha256=${HASH}`,
  ];
  for (let index = 0; index < count; index += 1) {
    lines.push(`part_${String(index).padStart(6, "0")}_sha256=${HASH}`);
  }
  return `${lines.join("\n")}\n`;
}

test("restore follows every segment declared by the manifest", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "antsdr-cache-action-"));
  const calls = [];
  const client = {
    async restoreCache(paths, key) {
      calls.push(key);
      if (key.includes("manifest-lookup")) {
        await fs.writeFile(path.join(paths[0], "toolchain.env"), manifest("123", 6));
        return "cache-key-manifest-123";
      }
      await fs.writeFile(paths[0], key);
      return key;
    },
  };
  try {
    assert.equal(await restore(root, "cache-key", client), true);
    assert.equal(calls.length, 7);
    assert.equal(calls.at(-1), "cache-key-part-000005-123");
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("a missing segment becomes a recoverable cache miss", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "antsdr-cache-action-"));
  const client = {
    async restoreCache(paths, key) {
      if (key.includes("manifest-lookup")) {
        await fs.writeFile(path.join(paths[0], "toolchain.env"), manifest("456", 2));
        return "cache-key-manifest-456";
      }
      if (key.endsWith("part-000001-456")) return undefined;
      await fs.writeFile(paths[0], key);
      return key;
    },
  };
  try {
    assert.equal(await restore(root, "cache-key", client), false);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("save publishes the manifest only after every segment", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "antsdr-cache-action-"));
  const manifestRoot = path.join(root, "manifest");
  const partsRoot = path.join(root, "parts");
  await fs.mkdir(manifestRoot, { recursive: true });
  await fs.mkdir(partsRoot, { recursive: true });
  await fs.writeFile(path.join(manifestRoot, "toolchain.env"), manifest("789", 3));
  for (let index = 0; index < 3; index += 1) {
    await fs.writeFile(path.join(partsRoot, `part-${String(index).padStart(6, "0")}`), "part");
  }
  const keys = [];
  const client = {
    async saveCache(_paths, key) {
      keys.push(key);
      return keys.length;
    },
  };
  try {
    await save(root, "cache-key", "789", client);
    assert.deepEqual(keys, [
      "cache-key-part-000000-789",
      "cache-key-part-000001-789",
      "cache-key-part-000002-789",
      "cache-key-manifest-789",
    ]);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
