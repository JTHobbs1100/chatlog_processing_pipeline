"""Load reusable anonymization allow lists from text or JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional


def _deduplicate(values: Iterable[str]) -> List[str]:
    """Return nonempty values in input order without duplicates."""
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        entry = value.strip()
        if entry and entry not in seen:
            result.append(entry)
            seen.add(entry)
    return result


def load_allow_list_file(path: Path) -> List[str]:
    """Load anonymization exclusions from a newline-delimited or JSON file.

    JSON files may contain either a list of strings or an object with an
    ``original_keys`` or ``allow_list`` string list. Plain-text files contain
    one entry per line; blank lines and lines beginning with ``#`` are ignored.

    Parameters:
        path: File containing allow-list entries.

    Returns:
        Deduplicated entries in their original order.
    """
    source = Path(path).expanduser()
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() != ".json":
        return _deduplicate(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )

    data = json.loads(text)
    values: object
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = data.get("original_keys", data.get("allow_list"))
    else:
        values = None

    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise ValueError(
            f"{source} must be a JSON string list or contain "
            "an original_keys/allow_list string list"
        )
    return _deduplicate(values)


def merge_allow_lists(
    direct_entries: Optional[List[str]], file_paths: Optional[List[str]]
) -> Optional[List[str]]:
    """Merge direct and file-backed allow-list entries.

    Parameters:
        direct_entries: Entries supplied directly on the command line.
        file_paths: Paths supplied with a repeated allow-list-file option.

    Returns:
        Deduplicated entries, or ``None`` when no entries were provided.
    """
    combined = list(direct_entries or [])
    for file_path in file_paths or []:
        combined.extend(load_allow_list_file(Path(file_path)))
    merged = _deduplicate(combined)
    return merged or None
