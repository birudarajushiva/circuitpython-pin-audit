"""Command-line interface. Output is deterministic and firmware is never run."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import sys
import tokenize
from typing import Sequence

from . import __version__
from .analyzer import Diagnostic, Report, analyze

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".tox", "build", "dist"}
MAX_BYTES = 2 * 1024 * 1024


def load_aliases(path: Path | None) -> list[list[str]]:
    if path is None:
        return []
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("alias file exceeds 2 MiB")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"aliases"}:
        raise ValueError('alias file must contain only {"aliases": [["D4", "SDA"], ...]}')
    groups = document["aliases"]
    if not isinstance(groups, list):
        raise ValueError("aliases must be a list of groups")
    for group in groups:
        if (not isinstance(group, list) or len(group) < 2 or
                any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in group)):
            raise ValueError("each alias group must contain at least two board attribute names")
    return groups


def discover(paths: Sequence[str], excludes: Sequence[str]) -> list[Path]:
    selected: dict[str, Path] = {}

    def scan_error(error: OSError) -> None:
        # os.walk otherwise suppresses scandir errors, yielding a partial scan
        # indistinguishable from a complete, conflict-free result.
        raise error

    def excluded(path: Path, root: Path) -> bool:
        relative = path.relative_to(root).as_posix()
        return any(fnmatch.fnmatchcase(relative, p) or fnmatch.fnmatchcase(path.name, p) for p in excludes)

    for name in paths:
        root = Path(name)
        if root.is_symlink():
            raise ValueError(f"refusing symlink input: {root}")
        if root.is_file():
            selected[str(root.resolve())] = root
        elif root.is_dir():
            for directory, folders, files in os.walk(root, followlinks=False, onerror=scan_error):
                parent = Path(directory)
                folders[:] = sorted(f for f in folders if f not in SKIP_DIRS and not
                                     (parent / f).is_symlink() and not excluded(parent / f, root))
                for filename in sorted(files):
                    candidate = parent / filename
                    if filename.endswith(".py") and not candidate.is_symlink() and not excluded(candidate, root):
                        selected[str(candidate.resolve())] = candidate
        else:
            raise ValueError(f"input does not exist or is not a regular file/directory: {root}")
    if not selected:
        raise ValueError("no Python source files selected")
    return sorted(selected.values(), key=lambda p: p.as_posix())


def escape(value: str, *, prop: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value


def render(reports: list[Report], output_format: str) -> str:
    if output_format == "json":
        return json.dumps({"schema_version": 1, "tool_version": __version__,
                           "files": [r.to_dict() for r in reports]}, indent=2, ensure_ascii=True)
    lines: list[str] = []
    for report in reports:
        for d in report.diagnostics:
            if output_format == "github":
                lines.append(f"::{d.severity} file={escape(report.path, prop=True)},line={d.line},"
                             f"col={d.column},title={d.code}::{escape(d.message)}")
            else:
                # repr prevents untrusted filenames/messages injecting terminal lines.
                safe_path = report.path.encode("unicode_escape").decode("ascii")
                safe_message = d.message.encode("unicode_escape").decode("ascii")
                lines.append(f"{safe_path}:{d.line}:{d.column}: {d.code} {safe_message}")
    summary = (f"{len(reports)} file(s), {sum(r.allocations for r in reports)} supported allocation(s), "
               f"{sum(len(r.conflicts) for r in reports)} potential conflict(s), "
               f"{sum(r.incomplete for r in reports)} file(s) with coverage gaps.")
    if output_format != "github":
        lines.extend([summary, "A report with no conflicts does not establish hardware safety or compatibility."])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find potential CircuitPython pin conflicts without running firmware.")
    parser.add_argument("paths", nargs="+", help="files or directories; each file is an independent entrypoint")
    parser.add_argument("--format", choices=("text", "json", "github"), default="text")
    parser.add_argument("--aliases", type=Path, help="JSON groups of pin names sharing the same physical pad")
    parser.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="exclude a directory-relative path or basename (repeatable)")
    parser.add_argument("--strict", action="store_true", help="also exit 1 when coverage gaps are reported")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        aliases = load_aliases(args.aliases)
        paths = discover(args.paths, args.exclude)
    except (OSError, ValueError) as error:
        safe_error = str(error).encode("unicode_escape").decode("ascii")
        print(f"pin-audit: {safe_error}", file=sys.stderr)
        return 2
    reports: list[Report] = []
    for path in paths:
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("source exceeds 2 MiB")
            # Honors Python encoding cookies; does not import the target module.
            with tokenize.open(path) as stream:
                source = stream.read()
            reports.append(analyze(source, path.as_posix(), aliases=aliases))
        except (OSError, UnicodeError, SyntaxError, LookupError, ValueError) as error:
            reports.append(Report(path.as_posix(), [Diagnostic("PA900", "error", 1, 1, f"Cannot read source: {error}")]))
    print(render(reports, args.format))
    if any(r.failed for r in reports):
        return 2
    if any(r.conflicts or (args.strict and r.incomplete) for r in reports):
        return 1
    return 0
