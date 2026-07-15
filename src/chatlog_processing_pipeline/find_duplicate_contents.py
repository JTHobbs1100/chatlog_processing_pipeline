"""Find duplicated content strings across JSON transcript files.

This module scans parsed transcript JSON files and reports exact duplicated
content spans across one or more directory roots.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def iter_content_values(node: Any) -> Iterable[str]:
    """Yield all string values associated with a key named ``content``.

    Parameters
    ----------
    node:
        Parsed JSON value to traverse recursively.

    Yields
    ------
    str
        Content strings discovered anywhere in the JSON payload.
    """

    if isinstance(node, dict):
        for key, value in node.items():
            if key == "content" and isinstance(value, str):
                yield value
            else:
                yield from iter_content_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_content_values(item)


def build_content_index(
    roots: Iterable[Path],
) -> Tuple[Dict[str, List[Tuple[Path, int]]], Dict[Path, int]]:
    """Build an index of content strings to the files where they appear.

    Parameters
    ----------
    roots:
        Directories to recurse into looking for JSON files.

    Returns
    -------
    Tuple[Dict[str, List[Tuple[Path, int]]], Dict[Path, int]]
        Mapping from content string to occurrences plus file-level content
        counts.
    """

    index: Dict[str, List[Tuple[Path, int]]] = defaultdict(list)
    file_line_counts: Dict[Path, int] = defaultdict(int)

    for root in roots:
        for path in sorted(root.rglob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError) as error:
                print(f"Warning: failed to read {path}: {error}", file=sys.stderr)
                continue

            counts_in_file: Dict[str, int] = defaultdict(int)
            total_lines = 0
            for content in iter_content_values(data):
                total_lines += 1
                counts_in_file[content] += 1

            file_line_counts[path] += total_lines

            for content, count in counts_in_file.items():
                index[content].append((path, count))

    return index, file_line_counts


def print_duplicates(index: Dict[str, List[Tuple[Path, int]]]) -> None:
    """Print groups of identical content strings that span multiple files.

    Parameters
    ----------
    index:
        Mapping from content string to file occurrences.
    """

    group_index = 0

    for content, occurrences in index.items():
        if len(occurrences) < 2:
            continue

        group_index += 1
        preview = content.replace("\n", "\\n")
        if len(preview) > 120:
            preview = preview[:117] + "..."

        print("=" * 80)
        print(f"GROUP {group_index}")
        print(f"content_length={len(content)}")
        print(f"preview={preview}")
        print("FILES:")
        for path, count in occurrences:
            print(f"- {path} (count_in_file={count})")


def _iter_pair_overlap_records(
    index: Dict[str, List[Tuple[Path, int]]],
) -> Iterable[Tuple[Path, Path, int]]:
    """Yield pairwise shared-line counts derived from duplicate content groups.

    Parameters
    ----------
    index:
        Mapping from content string to file occurrences.

    Yields
    ------
    Tuple[Path, Path, int]
        ``(path_a, path_b, shared_lines)`` tuples for each file pair.
    """

    pair_overlap: Dict[Tuple[Path, Path], int] = defaultdict(int)
    for occurrences in index.values():
        if len(occurrences) < 2:
            continue
        for index_i, (path_i, count_i) in enumerate(occurrences):
            for path_j, count_j in occurrences[index_i + 1 :]:
                shared_count = min(count_i, count_j)
                if shared_count <= 0:
                    continue
                pair_key = (
                    (path_i, path_j) if str(path_i) <= str(path_j) else (path_j, path_i)
                )
                pair_overlap[pair_key] += shared_count
    for (path_a, path_b), shared_lines in sorted(
        pair_overlap.items(),
        key=lambda item: (-item[1], str(item[0][0]), str(item[0][1])),
    ):
        yield path_a, path_b, shared_lines


def _compute_overlap_percent(shared_lines: int, total_a: int, total_b: int) -> float:
    """Return overlap as a percent of the smaller file's content count.

    Parameters
    ----------
    shared_lines:
        Number of shared content entries between the two files.
    total_a:
        Total content-entry count for file A.
    total_b:
        Total content-entry count for file B.

    Returns
    -------
    float
        Overlap percentage relative to the smaller file, or ``0.0`` when the
        denominator would be zero.
    """

    smaller_total = min(total_a, total_b)
    if smaller_total <= 0:
        return 0.0
    return 100.0 * float(shared_lines) / float(smaller_total)


def print_pairwise_overlap(
    index: Dict[str, List[Tuple[Path, int]]],
    file_line_counts: Dict[Path, int],
    *,
    min_overlap_percent: float,
    min_shared_lines: int,
) -> None:
    """Print pairwise overlap statistics between files.

    Parameters
    ----------
    index:
        Mapping from content string to file occurrences.
    file_line_counts:
        Mapping from file path to total number of content entries.
    min_overlap_percent:
        Minimum overlap percentage required for reporting.
    min_shared_lines:
        Minimum shared content entries required for reporting.
    """

    pair_records = list(_iter_pair_overlap_records(index))
    if not pair_records:
        return

    print("=" * 80)
    print("PAIRWISE_OVERLAP_SUMMARY")
    for path_a, path_b, shared_lines in pair_records:
        if shared_lines < min_shared_lines:
            continue

        total_a = file_line_counts.get(path_a, 0)
        total_b = file_line_counts.get(path_b, 0)
        percent = _compute_overlap_percent(shared_lines, total_a, total_b)

        if percent < min_overlap_percent:
            continue

        print(f"- FILE_A={path_a}")
        print(f"  FILE_B={path_b}")
        print(f"  total_lines_A={total_a}")
        print(f"  total_lines_B={total_b}")
        print(f"  shared_lines={shared_lines}")
        print(f"  percent_overlap_of_smaller={percent:.2f}")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Parameters
    ----------
    argv:
        Optional argument vector. When omitted, ``sys.argv`` is used.

    Returns
    -------
    argparse.Namespace
        Parsed arguments namespace.
    """

    parser = argparse.ArgumentParser(
        description="Find duplicated 'content' values across JSON files."
    )
    parser.add_argument(
        "--root",
        type=str,
        action="append",
        required=True,
        help="Root directory to scan for JSON files. Repeatable.",
    )
    parser.add_argument(
        "--min-overlap-percent",
        type=float,
        default=50.0,
        help=(
            "Minimum percent overlap (of the smaller file) to report a pair "
            "in the overlap summary (default: 50)."
        ),
    )
    parser.add_argument(
        "--min-shared-lines",
        type=int,
        default=1,
        help=(
            "Minimum shared content entries required to report a pair " "(default: 1)."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Entry point for the duplicate content finder.

    Parameters
    ----------
    argv:
        Optional argument vector. When omitted, ``sys.argv`` is used.

    Returns
    -------
    int
        Exit code: 0 on success, non-zero on error.
    """

    args = parse_args(argv)
    roots = [Path(root).expanduser().resolve() for root in args.root]

    missing = [root for root in roots if not root.exists() or not root.is_dir()]
    if missing:
        for root in missing:
            print(f"Error: root is not a directory: {root}", file=sys.stderr)
        return 2

    index, file_line_counts = build_content_index(roots)
    print_duplicates(index)
    print_pairwise_overlap(
        index,
        file_line_counts,
        min_overlap_percent=args.min_overlap_percent,
        min_shared_lines=args.min_shared_lines,
    )
    return 0
