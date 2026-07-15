"""Parse files according to a plan CSV, or generate one.

This module provides the plan-driven parsing workflow for files that need
explicit parser selection, custom role labels, or manual skip rules.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

from chatlog_processing_pipeline.processor import _process_one_file
from chatlog_processing_pipeline.util import (
    ensure_dir,
    find_json_snippet,
    html_contains_snippet,
    write_parsed_output,
)

_NUMERIC_PARTICIPANT_RE = re.compile(r"^[123][0-9]{2,}$")
_LEGACY_PARTICIPANT_RE = re.compile(r"^(irb|hl)_([0-9]+)$", re.IGNORECASE)


def normalize_participant_id(participant: str) -> str:
    """Return the canonical participant id used for plan filtering.

    Parameters
    ----------
    participant:
        Participant identifier string to normalize, for example ``"irb_05"``,
        ``"hl_08"``, or ``"105"``.

    Returns
    -------
    str
        Canonical numeric identifier when the value matches known patterns;
        otherwise the stripped input value unchanged.
    """

    if not participant:
        return participant
    cleaned = participant.strip()
    if _NUMERIC_PARTICIPANT_RE.fullmatch(cleaned):
        return cleaned
    match = _LEGACY_PARTICIPANT_RE.fullmatch(cleaned)
    if not match:
        return cleaned
    cohort, digits = match.groups()
    prefix = "1" if cohort.lower() == "irb" else "2"
    return f"{prefix}{digits.zfill(2)}"


def add_participants_argument(
    parser: argparse.ArgumentParser,
    *,
    help_text: Optional[str] = None,
) -> None:
    """Add the shared ``--participant/-p`` filter argument.

    Parameters
    ----------
    parser:
        Target argument parser.
    help_text:
        Optional custom help string for the filter.
    """

    parser.add_argument(
        "--participant",
        "-p",
        action="append",
        dest="participants",
        help=help_text
        or (
            "Restrict processing to these participant ids (repeatable). "
            "Defaults to all participants when omitted."
        ),
    )


def read_plan(plan_path: Path) -> Dict[str, Dict[str, object]]:
    """Read a plan CSV into a lookup table.

    Parameters
    ----------
    plan_path:
        Absolute path to a CSV file with headers
        ``rel_path,method,role_labels,conv_separator,skip``.

    Returns
    -------
    Dict[str, Dict[str, object]]
        Dictionary keyed by ``rel_path`` containing the parsed configuration for
        each file, including the method, role label list, conversation
        separator, and skip flag.
    """

    table: Dict[str, Dict[str, object]] = {}
    with plan_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rel = (row.get("rel_path") or "").strip()
            if not rel:
                continue
            method = (row.get("method") or "").strip().lower() or "auto"
            role_labels_raw = (row.get("role_labels") or "").strip()
            labels = (
                [value.strip() for value in role_labels_raw.split("|") if value.strip()]
                if role_labels_raw
                else []
            )
            skip = (row.get("skip") or "").strip().lower()
            conv_sep = (row.get("conv_separator") or "").strip()
            table[rel] = {
                "method": method,
                "role_labels": labels,
                "skip": skip,
                "conv_separator": conv_sep,
            }
    return table


def _default_method_for(path: Path) -> str:
    """Infer a reasonable default parsing method for a file path.

    Parameters
    ----------
    path:
        File system path to inspect.

    Returns
    -------
    str
        Default method string suitable for inclusion in a generated plan CSV.
    """

    ext = path.suffix.lower()
    name = path.name.lower()
    if ext == ".pdf":
        return "auto"
    if ext == ".docx":
        return "docx_titles"
    if ext in {".html", ".htm"} or name.endswith("chat.html"):
        return "chatgpt_html"
    if ext == ".json" or name.endswith("conversations.json"):
        return "chatgpt_json"
    return "auto"


def _is_image(path: Path) -> bool:
    """Return True if the path looks like an image file by extension."""

    return path.suffix.lower() in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".webp",
        ".heic",
        ".heif",
        ".svg",
    }


def _is_probably_binary(path: Path) -> bool:
    """Return True when a file header looks binary-like."""

    try:
        with path.open("rb") as handle:
            chunk = handle.read(2048)
    except OSError:
        return False
    if not chunk:
        return False
    if b"\x00" in chunk:
        return True
    text_bytes = sum(1 for byte in chunk if 9 <= byte <= 13 or 32 <= byte <= 126)
    ratio = text_bytes / max(1, len(chunk))
    return ratio < 0.7


def _is_ignored(path: Path) -> bool:
    """Return True if a file should be omitted from plan generation."""

    name = path.name
    if name == ".DS_Store":
        return True
    if path.suffix.lower() in {".wav", ".mp4"}:
        return True
    if _is_image(path):
        return True
    if path.suffix == "" and _is_probably_binary(path):
        return True
    return False


def _compute_skip_html_rels(
    plan: Dict[str, Dict[str, object]], in_root: Path
) -> set[str]:
    """Return plan rows whose ``chat.html`` files should be skipped.

    Parameters
    ----------
    plan:
        Parsed plan mapping keyed by ``rel_path``.
    in_root:
        Input root used to resolve plan rows.

    Returns
    -------
    set[str]
        Relative paths for redundant ``chat.html`` files that can be skipped in
        favor of sibling ``conversations.json`` files.
    """

    by_dir: Dict[Path, Dict[str, str]] = {}
    for rel in plan:
        path = in_root / rel
        name = path.name.lower()
        if name in {"chat.html", "conversations.json"}:
            bucket = by_dir.setdefault(path.parent, {})
            bucket[name] = rel

    skip_html_rels: set[str] = set()
    for names in by_dir.values():
        chat_rel = names.get("chat.html")
        conv_rel = names.get("conversations.json")
        if not chat_rel or not conv_rel:
            continue
        chat_path = in_root / chat_rel
        conv_path = in_root / conv_rel
        snippet = find_json_snippet(conv_path)
        same = False
        if snippet:
            same = html_contains_snippet(chat_path, snippet)
        else:
            try:
                same = chat_path.stat().st_size > 0 and conv_path.stat().st_size > 0
            except OSError:
                same = False
        if same:
            skip_html_rels.add(chat_rel)
            print(
                f"[SKIP-HTML-DUPLICATE] {chat_rel} "
                "(using conversations.json in same folder)"
            )
    return skip_html_rels


def _rel_matches_any_participant(rel: str, participants: Iterable[str]) -> bool:
    """Return True if ``rel`` contains any participant id as a path component.

    Parameters
    ----------
    rel:
        Relative path from the plan CSV.
    participants:
        Iterable of participant identifiers to match.

    Returns
    -------
    bool
        True when any participant identifier appears as a normalized path
        component in ``rel``.
    """

    wanted = {
        normalize_participant_id(participant.strip()).casefold()
        for participant in participants
        if participant.strip()
    }
    if not wanted:
        return False
    parts = [
        normalize_participant_id(part.strip()).casefold()
        for part in Path(rel).parts
        if part.strip()
    ]
    return any(part in wanted for part in parts)


def generate_plan(in_root: Path, out_csv: Path) -> None:
    """Walk an input tree and write a starter plan CSV.

    Parameters
    ----------
    in_root:
        Root directory to scan for candidate files.
    out_csv:
        Output CSV path to write.
    """

    rows: list[dict[str, str]] = []
    for dirpath, _dirs, filenames in os.walk(in_root):
        for filename in filenames:
            path = Path(dirpath) / filename
            if _is_ignored(path):
                continue
            rows.append(
                {
                    "rel_path": str(path.relative_to(in_root)),
                    "method": _default_method_for(path),
                    "role_labels": "",
                    "conv_separator": "",
                    "skip": "",
                }
            )
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "rel_path",
                "method",
                "role_labels",
                "conv_separator",
                "skip",
            ],
        )
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["rel_path"].lower()):
            writer.writerow(row)
    print(f"Plan written: {out_csv}")


def _run_plan_row(
    *,
    src: Path,
    cfg: Dict[str, object],
    in_root: Path,
    out_root: Path,
    strict: bool,
) -> tuple[bool, str]:
    """Process one plan row and return its success flag and status line.

    Parameters
    ----------
    src:
        Source file resolved from the plan row.
    cfg:
        Plan-row configuration dictionary.
    in_root:
        Input root directory.
    out_root:
        Output root directory.
    strict:
        Whether to enable stricter parsing behavior.

    Returns
    -------
    tuple[bool, str]
        ``(success, status_line)`` where ``success`` indicates whether the row
        should count toward the success total.
    """

    rel = str(src.relative_to(in_root))
    method = cfg.get("method") or "auto"
    roles: Optional[Iterable[str]] = cfg.get("role_labels")
    conv_sep = (cfg.get("conv_separator") or "").strip() or None
    try:
        meta, out = _process_one_file(
            src=src,
            in_root=in_root,
            out_root=out_root,
            verbose=True,
            strict_parsing=bool(strict),
            forced_method=str(method) if method else None,
            role_labels=roles,
            conv_separator=conv_sep,
        )
    except (OSError, RuntimeError, ValueError) as err:
        return False, f"[CRASH] {rel}: {err}"

    if meta.ok and out is not None:
        out_path = write_parsed_output(out_root, meta, out)
        return True, f"[OK] {rel} -> {out_path}"
    if meta.ok and out is None:
        return (
            True,
            "[OK] "
            f"{rel} (pass-through: {meta.source_guess}, count={meta.message_count})",
        )
    if meta.source_guess:
        return False, f"[FAIL] {rel}: method={meta.source_guess}; error={meta.error}"
    return False, f"[FAIL] {rel}: {meta.error}"


def process_plan(
    *,
    in_root: Path,
    out_root: Path,
    plan: Dict[str, Dict[str, object]],
    strict: bool,
    participants: Optional[Iterable[str]] = None,
) -> None:
    """Process files listed in a plan while honoring duplicate skip rules.

    Parameters
    ----------
    in_root:
        Input root directory corresponding to plan ``rel_path`` entries.
    out_root:
        Destination directory for parsed JSON outputs.
    plan:
        Parsed plan table keyed by ``rel_path``.
    strict:
        Whether to enable stricter parsing behavior.
    participants:
        Optional iterable of participant identifiers to restrict processing.
    """

    ok = 0
    fail = 0
    participants_list = list(participants or [])
    skip_html_rels = _compute_skip_html_rels(plan, in_root)
    for rel, cfg in plan.items():
        if participants_list and not _rel_matches_any_participant(
            rel, participants_list
        ):
            continue
        if rel in skip_html_rels:
            continue
        src = in_root / rel
        if not src.exists():
            print(f"[MISSING] {rel}")
            fail += 1
            continue
        if (cfg.get("skip") or "").lower() in {"1", "y", "yes", "true"}:
            print(f"[SKIP] {rel}")
            continue
        success, status_line = _run_plan_row(
            src=src,
            cfg=cfg,
            in_root=in_root,
            out_root=out_root,
            strict=strict,
        )
        print(status_line)
        if success:
            ok += 1
        else:
            fail += 1
    print(f"Done. Plan processed. ok={ok}, fail={fail}, total={ok + fail}")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Return parsed command-line arguments for the plan tool.

    Parameters
    ----------
    argv:
        Optional argument vector. When omitted, ``sys.argv`` is used.

    Returns
    -------
    argparse.Namespace
        Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--output-dir")
    parser.add_argument("--generate-plan")
    parser.add_argument("--strict", action="store_true")
    add_participants_argument(
        parser,
        help_text=(
            "Restrict processing to plan rows whose rel_path contains one of "
            "these participant identifiers as a path component, for example "
            "201 or 102. Repeatable."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Generate a plan or process one while skipping duplicated chat HTML.

    Parameters
    ----------
    argv:
        Optional argument vector. When omitted, ``sys.argv`` is used.

    Returns
    -------
    int
        Exit status code.
    """

    args = parse_args(argv)
    in_root = Path(args.input).expanduser().resolve()

    if args.generate_plan:
        generate_plan(in_root, Path(args.generate_plan).expanduser().resolve())
        return 0

    if not args.plan or not args.output_dir:
        raise SystemExit("Provide --plan and --output-dir or use --generate-plan")

    out_root = Path(args.output_dir).expanduser().resolve()
    ensure_dir(out_root)
    plan = read_plan(Path(args.plan).expanduser().resolve())
    process_plan(
        in_root=in_root,
        out_root=out_root,
        plan=plan,
        strict=args.strict,
        participants=args.participants,
    )
    return 0
