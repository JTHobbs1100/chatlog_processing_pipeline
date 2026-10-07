"""Tests for the ported Presidio tuning (entities, allow-list, overlaps)."""

import json
from types import SimpleNamespace

from chatlog_processing_pipeline.presidio_config import (
    DEFAULT_ENTITIES,
    is_allowlisted,
    resolve_overlaps,
)
from test_detection_report import _run


def test_default_entities_exclude_noisy_and_address_types():
    for off in ("DATE_TIME", "NRP", "ORGANIZATION", "STREET_ADDRESS", "POSTAL_CODE"):
        assert off not in DEFAULT_ENTITIES
    assert "PERSON" in DEFAULT_ENTITIES and "EMAIL_ADDRESS" in DEFAULT_ENTITIES


def test_allowlist_matches_tool_names_plus_lowercase_filler_only():
    assert is_allowlisted("ChatGPT")
    assert is_allowlisted("Claude.")
    assert is_allowlisted("claude the")  # tool name plus lowercase filler
    assert not is_allowlisted("Claude Smith")  # a capitalised non-tool token
    assert not is_allowlisted("Maria")


def test_resolve_overlaps_prefers_longest_then_score():
    def span(start, end, score):
        return SimpleNamespace(start=start, end=end, score=score)

    short, long_, other = span(0, 5, 0.9), span(0, 12, 0.5), span(20, 25, 0.4)
    assert resolve_overlaps([short, long_, other]) == [long_, other]


def _run_defaults(tmp_path, text, **overrides):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    in_dir.mkdir()
    (in_dir / "c.json").write_text(
        json.dumps({"meta": {}, "messages": [{"role": "user", "content": text}]}),
        encoding="utf-8",
    )
    _run(in_dir, out_dir, jobs=1, **overrides)
    return json.loads((out_dir / "c.json").read_text(encoding="utf-8"))[
        "messages"
    ][0]["content"]


def test_pipeline_keeps_tool_names_and_redacts_people(tmp_path):
    text = "Maria Gonzalez asked ChatGPT. Later Maria Gonzalez thanked Claude."
    out = _run_defaults(tmp_path, text, entities=None, content_only=True)
    assert "ChatGPT" in out and "Claude" in out
    assert out.count("<REDACTED>") == 2
    assert "Maria" not in out


def test_default_entities_leave_dates_alone(tmp_path):
    out = _run_defaults(
        tmp_path, "I use it every morning and last week too.", entities=None
    )
    assert out == "I use it every morning and last week too."
