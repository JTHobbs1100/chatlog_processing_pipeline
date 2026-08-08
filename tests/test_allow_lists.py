"""Tests for file-backed anonymization allow lists."""

import json

import pytest

from chatlog_processing_pipeline.allow_lists import (
    load_allow_list_file,
    merge_allow_lists,
)


def test_load_subsets_viewer_json_shape(tmp_path):
    """Load the original_keys shape emitted by the subsets viewer pipeline."""
    source = tmp_path / "pairs.json"
    source.write_text(
        json.dumps({"original_keys": ["or", "on", "or"]}), encoding="utf-8"
    )

    assert load_allow_list_file(source) == ["or", "on"]


def test_load_text_ignores_comments_and_blank_lines(tmp_path):
    """Ignore text-file comments and empty lines while preserving order."""
    source = tmp_path / "allow.txt"
    source.write_text("# reviewed\nor\n\n on \n", encoding="utf-8")

    assert load_allow_list_file(source) == ["or", "on"]


def test_merge_allow_lists_preserves_direct_entries_first(tmp_path):
    """Merge repeated files with direct entries and remove duplicates."""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(["on", "then"]), encoding="utf-8")
    second.write_text(json.dumps({"allow_list": ["or", "on"]}), encoding="utf-8")

    assert merge_allow_lists(["and", "on"], [str(first), str(second)]) == [
        "and",
        "on",
        "then",
        "or",
    ]


def test_load_json_rejects_non_string_entries(tmp_path):
    """Reject malformed JSON allow lists instead of silently coercing values."""
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps({"original_keys": ["or", 2]}), encoding="utf-8")

    with pytest.raises(ValueError, match="original_keys/allow_list"):
        load_allow_list_file(source)
