"""Tests for the Claude.ai conversations.json normalizer."""

import json

import pytest

from chatlog_processing_pipeline.parsers.parser_claude_json import (
    looks_like_claude_export,
    parse,
)
from chatlog_processing_pipeline.parsers.parser_chatgpt_md import ParseFailed
from chatlog_processing_pipeline.processor import _process_one_file
from chatlog_processing_pipeline.util import looks_like_parsed_chat_json

SAMPLE_EXPORT = [
    {
        "uuid": "conv-1",
        "name": "Trip planning",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:05:00Z",
        "chat_messages": [
            {
                "sender": "human",
                "text": "Where should I go in June?",
                "content": [{"type": "text", "text": "Where should I go in June?"}],
            },
            {
                "sender": "assistant",
                "text": "",
                "content": [
                    {"type": "thinking", "thinking": "weigh a few options"},
                    {"type": "text", "text": "Consider Portugal."},
                ],
            },
        ],
    },
    {
        "uuid": "conv-2",
        "name": "",
        "chat_messages": [],
    },
]


def test_looks_like_claude_export_detects_sample():
    assert looks_like_claude_export(SAMPLE_EXPORT)


CHATGPT_EXPORT = [
    {
        "title": "Python help",
        "create_time": 1700000000.0,
        "mapping": {
            "root": {"id": "root", "message": None, "children": ["a"]},
            "a": {
                "id": "a",
                "message": {
                    "id": "a",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hi there"]},
                },
                "children": [],
            },
        },
    }
]


def test_looks_like_claude_export_rejects_chatgpt_shape():
    assert not looks_like_claude_export(CHATGPT_EXPORT)
    assert not looks_like_claude_export([])
    assert not looks_like_claude_export({"not": "a list"})


def test_parse_normalizes_roles_and_content():
    parsed = parse(SAMPLE_EXPORT)
    convs = parsed["conversations"]
    assert len(convs) == 2

    first = convs[0]
    assert first["title"] == "Trip planning"
    assert first["messages"] == [
        {"role": "user", "content": "Where should I go in June?"},
        {"role": "assistant", "content": "weigh a few options\n\nConsider Portugal."},
    ]

    second = convs[1]
    assert second["messages"] == []


def test_parse_raises_on_non_claude_shape():
    with pytest.raises(ParseFailed):
        parse([{"title": "x"}])


def test_normalized_output_matches_parsed_chat_json_schema():
    parsed = parse(SAMPLE_EXPORT)
    assert looks_like_parsed_chat_json(parsed)


def test_process_one_file_normalizes_claude_export(tmp_path):
    in_root = tmp_path / "in"
    out_root = tmp_path / "out"
    in_root.mkdir()
    out_root.mkdir()
    src = in_root / "conversations.json"
    src.write_text(json.dumps(SAMPLE_EXPORT), encoding="utf-8")

    meta, out = _process_one_file(
        src=src,
        in_root=in_root,
        out_root=out_root,
        verbose=False,
        strict_parsing=False,
    )

    assert meta.ok
    assert meta.source_guess == "claude-json"
    assert out is not None
    assert out["conversations"][0]["messages"][0]["role"] == "user"


def test_process_one_file_passes_through_chatgpt_export(tmp_path):
    """A real ChatGPT mapping-tree export still passes through untouched."""
    in_root = tmp_path / "in"
    out_root = tmp_path / "out"
    in_root.mkdir()
    out_root.mkdir()
    src = in_root / "conversations.json"
    src.write_text(json.dumps(CHATGPT_EXPORT), encoding="utf-8")

    meta, out = _process_one_file(
        src=src,
        in_root=in_root,
        out_root=out_root,
        verbose=False,
        strict_parsing=False,
    )

    assert meta.ok
    assert meta.source_guess == "json-pass-through"
    assert out is None
    assert (out_root / "conversations.json").exists()


def test_cli_parse_writes_normalized_claude_export(tmp_path, monkeypatch):
    """Regression: Claude output must be written by `process_chats --parse`."""
    from chatlog_processing_pipeline.commands import main

    in_root = tmp_path / "in" / "export_a"
    in_root.mkdir(parents=True)
    (in_root / "conversations.json").write_text(
        json.dumps(SAMPLE_EXPORT), encoding="utf-8"
    )
    out_root = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "process_chats",
            "--parse",
            "--single-thread",
            "--input",
            str(tmp_path / "in"),
            "--output-dir",
            str(out_root),
        ],
    )
    main()

    written = json.loads((out_root / "export_a" / "conversations.json").read_text())
    assert written["conversations"][0]["messages"][0]["role"] == "user"
