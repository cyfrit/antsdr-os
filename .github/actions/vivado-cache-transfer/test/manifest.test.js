// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import test from "node:test";
import { parseManifest } from "../src/manifest.js";

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);

test("manifest declares an arbitrary number of ordered segments", () => {
  const manifest = parseManifest([
    "schema=2",
    "generation=123",
    "parts=2",
    "part_suffix_length=6",
    `archive_sha256=${HASH_A}`,
    `part_000000_sha256=${HASH_A}`,
    `part_000001_sha256=${HASH_B}`,
    "",
  ].join("\n"));
  assert.equal(manifest.generation, "123");
  assert.deepEqual(manifest.parts.map((part) => part.name), ["part-000000", "part-000001"]);
});

test("legacy fixed-slot manifests are rejected", () => {
  assert.throws(() => parseManifest("schema=1\ngeneration=123\nparts=4\n"), /unsupported/);
});
