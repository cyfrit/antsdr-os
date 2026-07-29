#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate repository Actions policy without contacting GitHub."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from board_data import REPOSITORY_ROOT


SHA_ACTION = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*@[0-9a-f]{40}$"
)
FORBIDDEN_EVENTS = {"pull_request_target", "workflow_run"}
HARDWARE_WRITE_WORDS = ("dfu", "reboot", "flash", "fw_setenv", "iio_attr", "dd ")


class WorkflowPolicyError(RuntimeError):
    pass


def workflow_files(root: Path = REPOSITORY_ROOT) -> list[Path]:
    directory = root / ".github" / "workflows"
    return sorted((*directory.glob("*.yml"), *directory.glob("*.yaml")))


def load_workflow(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise WorkflowPolicyError(f"{path}: invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise WorkflowPolicyError(f"{path}: workflow must be a mapping")
    # PyYAML's YAML 1.1 loader interprets the unquoted key `on` as boolean.
    if True in data and "on" not in data:
        data["on"] = data.pop(True)
    if not isinstance(data.get("name"), str) or not data["name"]:
        raise WorkflowPolicyError(f"{path}: name is required")
    if "on" not in data:
        raise WorkflowPolicyError(f"{path}: on is required")
    return data


def event_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    if isinstance(value, dict):
        return set(value)
    return set()


def walk_values(value: Any):
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)
    elif isinstance(value, str):
        yield value


def uses_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                found.append(child)
            found.extend(uses_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(uses_values(child))
    return found


def validate_workflow(path: Path) -> None:
    data = load_workflow(path)
    events = event_names(data["on"])
    if events & FORBIDDEN_EVENTS:
        raise WorkflowPolicyError(f"{path}: forbidden event: {sorted(events & FORBIDDEN_EVENTS)}")
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        raise WorkflowPolicyError(f"{path}: top-level permissions are required")
    if permissions.get("contents") not in {"read", "write", "none"}:
        raise WorkflowPolicyError(f"{path}: contents permission must be explicit")

    for action in uses_values(data):
        if action.startswith("./"):
            continue
        if not SHA_ACTION.fullmatch(action):
            raise WorkflowPolicyError(f"{path}: action is not pinned to a full commit SHA: {action}")

    jobs = data.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise WorkflowPolicyError(f"{path}: jobs are required")
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            raise WorkflowPolicyError(f"{path}: job {job_id} must be a mapping")
        runs_on = job.get("runs-on")
        runs_on_text = " ".join(runs_on) if isinstance(runs_on, list) else str(runs_on)
        if "self-hosted" in runs_on_text and "pull_request" in events:
            raise WorkflowPolicyError(f"{path}: self-hosted job cannot run on pull_request")

    if "hardware" in path.stem:
        text = "\n".join(walk_values(data)).lower()
        found = [word for word in HARDWARE_WRITE_WORDS if word in text]
        if found:
            raise WorkflowPolicyError(f"{path}: hardware workflow contains write operation: {found}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()
    try:
        paths = workflow_files(args.root)
        if not paths:
            raise WorkflowPolicyError("no workflow files found")
        for path in paths:
            validate_workflow(path)
            print(f"validated {path.relative_to(args.root).as_posix()}")
        return 0
    except (OSError, WorkflowPolicyError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
