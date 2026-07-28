#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Audit and maintain repository license metadata without network access."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "license-policy.yaml"
COMMENT_PREFIX = r"(?:(?://+|#+|/\*+|\*+|<!--)\s*)?"
SPDX_RE = re.compile(
    rf"^[ \t]*{COMMENT_PREFIX}SPDX-License-Identifier:[ \t]*"
    r"([A-Za-z0-9().+\- \t]+?)[ \t]*(?:\*/|-->)?[ \t]*$",
    re.MULTILINE,
)
LEGACY_RE = re.compile(
    rf"^[ \t]*{COMMENT_PREFIX}SPDX\s+short\s+identifier:\s*([A-Za-z0-9.+-]+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
COPYRIGHT_RE = re.compile(r"^.*(?:Copyright|SPDX-FileCopyrightText:).*$", re.MULTILINE | re.IGNORECASE)
TOKEN_RE = re.compile(r"\s*(\(|\)|AND\b|OR\b|WITH\b|[A-Za-z0-9][A-Za-z0-9.+-]*)")


class AuditError(RuntimeError):
    pass


class ExpressionError(ValueError):
    pass


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class FileRecord:
    path: str
    kind: str
    expression: str
    source: str
    license_ids: list[str]
    contains_non_osi: bool
    copyrights: list[str]
    sha256: str | None
    size: int | None


@dataclass
class AuditResult:
    records: list[FileRecord]
    diagnostics: list[Diagnostic]

    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]

    def warnings(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "warning"]


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as error:
        raise AuditError(f"cannot load policy {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"{path}: expected a YAML mapping")
    return value


def path_matches(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
            return True
    return False


def normalized_sha256(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


class ExpressionParser:
    def __init__(self, value: str):
        self.value = value.strip()
        self.tokens = self._tokenize(self.value)
        self.index = 0
        self.license_ids: list[str] = []
        self.exception_ids: list[str] = []

    @staticmethod
    def _tokenize(value: str) -> list[str]:
        if not value:
            raise ExpressionError("empty SPDX expression")
        tokens: list[str] = []
        offset = 0
        while offset < len(value):
            match = TOKEN_RE.match(value, offset)
            if not match:
                raise ExpressionError(f"unexpected token at column {offset + 1}")
            tokens.append(match.group(1))
            offset = match.end()
        return tokens

    def parse(self) -> tuple[list[str], list[str]]:
        self._parse_or()
        if self.index != len(self.tokens):
            raise ExpressionError(f"unexpected token: {self.tokens[self.index]}")
        return list(dict.fromkeys(self.license_ids)), list(dict.fromkeys(self.exception_ids))

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None:
            raise ExpressionError("unexpected end of expression")
        if expected is not None and token != expected:
            raise ExpressionError(f"expected {expected}, got {token}")
        self.index += 1
        return token

    def _parse_or(self) -> None:
        self._parse_and()
        while self._peek() == "OR":
            self._take("OR")
            self._parse_and()

    def _parse_and(self) -> None:
        self._parse_with()
        while self._peek() == "AND":
            self._take("AND")
            self._parse_with()

    def _parse_with(self) -> None:
        simple_license = self._parse_primary()
        if self._peek() == "WITH":
            if not simple_license:
                raise ExpressionError("WITH can only follow a single license identifier")
            self._take("WITH")
            exception = self._take()
            if exception in {"AND", "OR", "WITH", "(", ")"}:
                raise ExpressionError(f"invalid exception identifier: {exception}")
            self.exception_ids.append(exception)

    def _parse_primary(self) -> bool:
        token = self._take()
        if token == "(":
            self._parse_or()
            self._take(")")
            return False
        if token in {"AND", "OR", "WITH", ")"}:
            raise ExpressionError(f"expected license identifier, got {token}")
        self.license_ids.append(token)
        return True


def parse_expression(value: str) -> tuple[list[str], list[str]]:
    return ExpressionParser(value).parse()


class LicensePolicy:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.root = self.path.parent
        data = load_yaml(self.path)
        if data.get("schema_version") != 1:
            raise AuditError(f"{self.path}: unsupported schema_version")

        self.license_list_version = str(data.get("spdx_license_list_version", "unknown"))
        self.default_expression = self._required_string(data.get("default_license"), "default_license")
        self.licenses = self._mapping(data.get("licenses"), "licenses")
        self.legacy_identifiers = self._string_mapping(
            data.get("legacy_identifiers", {}), "legacy_identifiers"
        )
        self.allowed_exceptions = set(self._string_list(data.get("allowed_exceptions", []), "allowed_exceptions"))
        self.header_required = self._string_list(data.get("header_required", []), "header_required")
        self.rules = data.get("rules", [])
        if not isinstance(self.rules, list) or any(not isinstance(rule, dict) for rule in self.rules):
            raise AuditError(f"{self.path}: rules must be a list of mappings")

        for identifier, metadata in self.licenses.items():
            if not isinstance(metadata, dict):
                raise AuditError(f"{self.path}: license {identifier} must be a mapping")
            if "osi_approved" not in metadata:
                raise AuditError(f"{self.path}: license {identifier} lacks osi_approved")
            if identifier != "NOASSERTION" and not metadata.get("text"):
                raise AuditError(f"{self.path}: license {identifier} lacks text")

        self.validate_expression(self.default_expression)
        for alias, expression in self.legacy_identifiers.items():
            try:
                self.validate_expression(expression)
            except ExpressionError as error:
                raise AuditError(f"{self.path}: invalid legacy mapping {alias}: {error}") from error

    @staticmethod
    def _required_string(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value:
            raise AuditError(f"policy {label} must be a non-empty string")
        return value

    @staticmethod
    def _mapping(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AuditError(f"policy {label} must be a mapping")
        return value

    @staticmethod
    def _string_mapping(value: Any, label: str) -> dict[str, str]:
        if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
            raise AuditError(f"policy {label} must map strings to strings")
        return value

    @staticmethod
    def _string_list(value: Any, label: str) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise AuditError(f"policy {label} must be a list of strings")
        return value

    def validate_expression(self, expression: str) -> tuple[list[str], list[str]]:
        if expression == "NOASSERTION":
            return [], []
        license_ids, exception_ids = parse_expression(expression)
        unknown = [identifier for identifier in license_ids if identifier not in self.licenses]
        if unknown:
            raise ExpressionError(f"unknown or disallowed license identifier(s): {', '.join(unknown)}")
        unknown_exceptions = [identifier for identifier in exception_ids if identifier not in self.allowed_exceptions]
        if unknown_exceptions:
            raise ExpressionError(f"unknown or disallowed exception(s): {', '.join(unknown_exceptions)}")
        return license_ids, exception_ids

    def settings_for(self, path: str, mode: str) -> dict[str, Any]:
        settings: dict[str, Any] = {
            "expression": self.default_expression,
            "source": "repository-default",
            "kind": "file",
            "require_spdx": path_matches(path, self.header_required),
        }
        for rule in self.rules:
            patterns = rule.get("paths")
            if not isinstance(patterns, list) or any(not isinstance(item, str) for item in patterns):
                raise AuditError(f"{self.path}: rule paths must be a list of strings")
            if path_matches(path, patterns):
                for key in ("expression", "source", "kind", "require_spdx"):
                    if key in rule:
                        settings[key] = rule[key]
        if mode == "160000":
            settings["kind"] = "submodule"
        return settings

    def non_osi(self, license_ids: list[str]) -> bool:
        return any(not bool(self.licenses[identifier]["osi_approved"]) for identifier in license_ids)


def git_entries(root: Path) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise AuditError(result.stderr.decode("utf-8", "replace").strip() or "git ls-files failed")
    entries: list[tuple[str, str]] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        metadata, separator, encoded_path = raw.partition(b"\t")
        if not separator:
            raise AuditError("unexpected git ls-files output")
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        path = encoded_path.decode("utf-8", "surrogateescape").replace("\\", "/")
        entries.append((mode, path))
    return sorted(entries, key=lambda item: item[1])


def clean_notice(line: str) -> str:
    value = line.strip().strip("/*# ").rstrip("*/ ").strip()
    return value


class LicenseAuditor:
    def __init__(self, root: Path, policy: LicensePolicy):
        self.root = root.resolve()
        self.policy = policy

    def scan(self) -> AuditResult:
        diagnostics: list[Diagnostic] = []
        records: list[FileRecord] = []
        for mode, path in git_entries(self.root):
            record, item_diagnostics = self._scan_entry(mode, path)
            records.append(record)
            diagnostics.extend(item_diagnostics)
        diagnostics.extend(self._check_license_texts(records))
        diagnostics.sort(key=lambda item: (item.path, item.severity, item.code, item.message))
        return AuditResult(records=records, diagnostics=diagnostics)

    def _scan_entry(self, mode: str, path: str) -> tuple[FileRecord, list[Diagnostic]]:
        diagnostics: list[Diagnostic] = []
        settings = self.policy.settings_for(path, mode)
        expression = str(settings["expression"])
        source = str(settings["source"])
        kind = str(settings["kind"])

        if mode == "160000":
            return self._record(path, kind, expression, source, [], None, None, diagnostics)

        absolute = self.root / Path(*PurePosixPath(path).parts)
        try:
            data = absolute.read_bytes()
        except OSError as error:
            diagnostics.append(Diagnostic("error", "E001", path, f"cannot read tracked file: {error}"))
            return self._record(path, kind, expression, source, [], None, None, diagnostics)

        if b"\0" in data[:8192]:
            diagnostics.append(Diagnostic("error", "E002", path, "tracked binary lacks an explicit policy rule"))
            return self._record(path, "binary", expression, source, [], data, len(data), diagnostics)

        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            diagnostics.append(Diagnostic("error", "E003", path, f"text file is not UTF-8: {error}"))
            return self._record(path, kind, expression, source, [], data, len(data), diagnostics)

        if kind == "license-text":
            return self._record(path, kind, expression, source, [], data, len(data), diagnostics)

        expressions = list(dict.fromkeys(match.group(1).strip() for match in SPDX_RE.finditer(text[:32768])))
        legacy = list(dict.fromkeys(match.group(1) for match in LEGACY_RE.finditer(text[:32768])))
        if len(expressions) > 1:
            diagnostics.append(
                Diagnostic("error", "E004", path, f"conflicting SPDX expressions: {', '.join(expressions)}")
            )
        if expressions:
            expression = expressions[0]
            source = "spdx-header"
        elif legacy:
            mapped = [self.policy.legacy_identifiers.get(identifier) for identifier in legacy]
            unknown = [identifier for identifier, value in zip(legacy, mapped) if value is None]
            if unknown:
                diagnostics.append(
                    Diagnostic("error", "E005", path, f"unknown legacy identifier(s): {', '.join(unknown)}")
                )
            known = list(dict.fromkeys(value for value in mapped if value is not None))
            if len(known) > 1:
                diagnostics.append(
                    Diagnostic("error", "E006", path, f"conflicting legacy license mappings: {', '.join(known)}")
                )
            if known:
                expression = known[0]
                source = "legacy-spdx-header"
                diagnostics.append(
                    Diagnostic("warning", "W001", path, "legacy SPDX short identifier should be modernized")
                )

        if bool(settings["require_spdx"]) and source not in {"spdx-header", "legacy-spdx-header"}:
            diagnostics.append(Diagnostic("error", "E007", path, "policy requires an SPDX license header"))

        copyrights = list(
            dict.fromkeys(
                cleaned
                for match in COPYRIGHT_RE.finditer(text[:32768])
                if (cleaned := clean_notice(match.group(0)))
            )
        )
        return self._record(path, kind, expression, source, copyrights, data, len(data), diagnostics)

    def _record(
        self,
        path: str,
        kind: str,
        expression: str,
        source: str,
        copyrights: list[str],
        data: bytes | None,
        size: int | None,
        diagnostics: list[Diagnostic],
    ) -> tuple[FileRecord, list[Diagnostic]]:
        license_ids: list[str] = []
        try:
            license_ids, _ = self.policy.validate_expression(expression)
        except ExpressionError as error:
            diagnostics.append(Diagnostic("error", "E008", path, f"invalid SPDX expression: {error}"))
        contains_non_osi = self.policy.non_osi(license_ids) if license_ids else False
        if contains_non_osi and kind != "license-text":
            diagnostics.append(
                Diagnostic("warning", "W002", path, "expression includes a non-OSI or source-available license option")
            )
        return (
            FileRecord(
                path=path,
                kind=kind,
                expression=expression,
                source=source,
                license_ids=license_ids,
                contains_non_osi=contains_non_osi,
                copyrights=copyrights,
                sha256=normalized_sha256(data) if data is not None else None,
                size=size,
            ),
            diagnostics,
        )

    def _check_license_texts(self, records: list[FileRecord]) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        used = sorted({identifier for record in records for identifier in record.license_ids})
        tracked_paths = {record.path for record in records}
        for identifier in used:
            metadata = self.policy.licenses[identifier]
            relative = metadata.get("text")
            if not relative:
                diagnostics.append(Diagnostic("error", "E009", identifier, "license has no configured text"))
                continue
            path = self.root / Path(*PurePosixPath(str(relative)).parts)
            if not path.is_file():
                diagnostics.append(Diagnostic("error", "E010", str(relative), f"missing text for {identifier}"))
                continue
            if str(relative) not in tracked_paths:
                diagnostics.append(
                    Diagnostic("error", "E013", str(relative), f"{identifier} text exists but is not tracked")
                )
            data = path.read_bytes()
            if not data.strip():
                diagnostics.append(Diagnostic("error", "E011", str(relative), f"empty text for {identifier}"))
                continue
            expected = metadata.get("sha256")
            actual = normalized_sha256(data)
            if not expected:
                diagnostics.append(Diagnostic("warning", "W003", str(relative), f"{identifier} text has no pinned hash"))
            elif expected != actual:
                diagnostics.append(
                    Diagnostic("error", "E012", str(relative), f"{identifier} text hash mismatch: {actual}")
                )
        return diagnostics


def result_payload(result: AuditResult, policy: LicensePolicy) -> dict[str, Any]:
    expressions: dict[str, int] = {}
    for record in result.records:
        expressions[record.expression] = expressions.get(record.expression, 0) + 1
    return {
        "schema_version": 1,
        "spdx_license_list_version": policy.license_list_version,
        "summary": {
            "files": len(result.records),
            "errors": len(result.errors()),
            "warnings": len(result.warnings()),
            "non_osi_files": sum(
                record.contains_non_osi and record.kind == "file" for record in result.records
            ),
            "expressions": dict(sorted(expressions.items())),
        },
        "files": [asdict(record) for record in result.records],
        "diagnostics": [asdict(item) for item in result.diagnostics],
    }


def print_diagnostics(result: AuditResult) -> None:
    for item in result.diagnostics:
        print(f"{item.severity.upper()} {item.code} {item.path}: {item.message}")


def print_summary(result: AuditResult) -> None:
    print(
        f"license audit: {len(result.records)} tracked entries, "
        f"{len(result.errors())} error(s), {len(result.warnings())} warning(s)"
    )


def write_output(value: str, output: Path | None) -> None:
    if output is None:
        print(value)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        if not value.endswith("\n"):
            stream.write("\n")


def header_lines(path: Path, expression: str, copyright_text: str | None) -> list[str]:
    suffix = path.suffix.lower()
    if (
        path.name == "Makefile"
        or path.name.endswith("defconfig")
        or suffix in {".py", ".yaml", ".yml", ".tcl", ".xdc", ".conf", ".config"}
    ):
        prefix, suffix_text = "# ", ""
    elif suffix in {".c", ".h", ".v", ".sv", ".dts", ".dtsi"}:
        prefix, suffix_text = "// ", ""
    elif suffix == ".md":
        prefix, suffix_text = "<!-- ", " -->"
    elif suffix == ".patch":
        prefix, suffix_text = "", ""
    else:
        raise AuditError(f"no safe SPDX header style for {path}")
    lines = [f"{prefix}SPDX-License-Identifier: {expression}{suffix_text}"]
    if copyright_text:
        lines.append(f"{prefix}SPDX-FileCopyrightText: {copyright_text}{suffix_text}")
    return lines


def add_header(path: Path, expression: str, copyright_text: str | None, apply: bool) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise AuditError(f"cannot read {path}: {error}") from error
    if SPDX_RE.search(text[:32768]) or LEGACY_RE.search(text[:32768]):
        raise AuditError(f"{path}: license header already exists")
    lines = text.splitlines(keepends=True)
    if path.suffix.lower() == ".patch":
        insertion = next((index for index, line in enumerate(lines) if not line.strip()), -1)
        if insertion < 0:
            raise AuditError(f"{path}: patch has no RFC 822 header separator")
        new_lines = [line + "\n" for line in header_lines(path, expression, copyright_text)]
    else:
        insertion = 1 if lines and lines[0].startswith("#!") else 0
        new_lines = [line + "\n" for line in header_lines(path, expression, copyright_text)] + ["\n"]
    updated = "".join(lines[:insertion] + new_lines + lines[insertion:])
    if apply:
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(updated)
    return updated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY, help="license policy YAML")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate all tracked files and license texts")
    check.add_argument("--strict", action="store_true", help="treat warnings as failures")

    scan = subparsers.add_parser("scan", help="print or write the complete license inventory")
    scan.add_argument("--format", choices=("text", "json"), default="text")
    scan.add_argument("--output", type=Path)

    explain = subparsers.add_parser("explain", help="show how one tracked path was classified")
    explain.add_argument("path")
    explain.add_argument("--format", choices=("text", "json"), default="text")

    header = subparsers.add_parser("header", help="preview or add an SPDX header to one file")
    header.add_argument("path", type=Path)
    header.add_argument("--license", required=True, dest="expression")
    header.add_argument("--copyright")
    header.add_argument("--apply", action="store_true", help="write the header; default is preview only")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        policy_path = args.policy if args.policy.is_absolute() else root / args.policy
        policy = LicensePolicy(policy_path)

        if args.command == "header":
            policy.validate_expression(args.expression)
            path = (args.path if args.path.is_absolute() else root / args.path).resolve()
            try:
                path.relative_to(root)
            except ValueError as error:
                raise AuditError(f"header target is outside repository: {path}") from error
            updated = add_header(path, args.expression, args.copyright, args.apply)
            if args.apply:
                print(f"updated {path.relative_to(root)}")
            else:
                print(updated, end="")
            return 0

        result = LicenseAuditor(root, policy).scan()
        if args.command == "check":
            print_diagnostics(result)
            print_summary(result)
            return 1 if result.errors() or (args.strict and result.warnings()) else 0

        if args.command == "scan":
            if args.format == "json":
                rendered = json.dumps(result_payload(result, policy), indent=2, sort_keys=True)
            else:
                lines = [f"{record.expression:<52} {record.source:<22} {record.path}" for record in result.records]
                lines.append("")
                lines.extend(
                    f"{item.severity.upper()} {item.code} {item.path}: {item.message}"
                    for item in result.diagnostics
                )
                lines.append("")
                lines.append(
                    f"{len(result.records)} tracked entries; {len(result.errors())} error(s); "
                    f"{len(result.warnings())} warning(s)"
                )
                rendered = "\n".join(lines)
            write_output(rendered, args.output)
            return 1 if result.errors() else 0

        record = next((item for item in result.records if item.path == args.path.replace("\\", "/")), None)
        if record is None:
            raise AuditError(f"not a tracked path: {args.path}")
        related = [item for item in result.diagnostics if item.path in {record.path, *record.license_ids}]
        if args.format == "json":
            print(json.dumps({"file": asdict(record), "diagnostics": [asdict(item) for item in related]}, indent=2))
        else:
            for key, value in asdict(record).items():
                print(f"{key}: {value}")
            for item in related:
                print(f"{item.severity.upper()} {item.code}: {item.message}")
        return 1 if any(item.severity == "error" for item in related) else 0
    except (AuditError, ExpressionError, KeyError, OSError) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
