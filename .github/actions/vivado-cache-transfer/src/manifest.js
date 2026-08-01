// SPDX-License-Identifier: MIT

const HASH = /^[0-9a-f]{64}$/;
const POSITIVE_INTEGER = /^[1-9][0-9]*$/;

function parseFields(text) {
  const fields = new Map();
  for (const line of text.split(/\r?\n/)) {
    if (!line) continue;
    const separator = line.indexOf("=");
    if (separator <= 0) throw new Error(`invalid manifest line: ${line}`);
    const key = line.slice(0, separator);
    if (fields.has(key)) throw new Error(`duplicate manifest field: ${key}`);
    fields.set(key, line.slice(separator + 1));
  }
  return fields;
}

function required(fields, key) {
  const value = fields.get(key);
  if (value === undefined || value === "") throw new Error(`missing manifest field: ${key}`);
  return value;
}

function parseManifest(text) {
  const fields = parseFields(text);
  if (required(fields, "schema") !== "2") throw new Error("unsupported cache manifest schema");

  const generation = required(fields, "generation");
  const countText = required(fields, "parts");
  const widthText = required(fields, "part_suffix_length");
  const archiveHash = required(fields, "archive_sha256");
  if (!/^[0-9]+$/.test(generation)) throw new Error("invalid cache generation");
  if (!POSITIVE_INTEGER.test(countText)) throw new Error("invalid cache part count");
  if (!POSITIVE_INTEGER.test(widthText)) throw new Error("invalid cache suffix length");
  if (!HASH.test(archiveHash)) throw new Error("invalid archive digest");

  const count = Number(countText);
  const width = Number(widthText);
  if (!Number.isSafeInteger(count) || !Number.isSafeInteger(width) || width > 12) {
    throw new Error("cache manifest numeric value is out of range");
  }
  if (countText.length > width) throw new Error("cache part count exceeds its filename namespace");

  const parts = [];
  for (let index = 0; index < count; index += 1) {
    const suffix = String(index).padStart(width, "0");
    const digest = required(fields, `part_${suffix}_sha256`);
    if (!HASH.test(digest)) throw new Error(`invalid digest for cache part ${suffix}`);
    parts.push({ name: `part-${suffix}`, digest });
  }
  return { generation, archiveHash, parts };
}

export { parseManifest };
