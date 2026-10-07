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
    # The empty second conversation is dropped and counted in the notes.
    assert len(convs) == 1
    assert "1 conversations with no content" in parsed["notes"]

    first = convs[0]
    assert first["title"] == "Trip planning"
    assert first["messages"] == [
        {"role": "user", "content": "Where should I go in June?"},
        # The thinking block is not conversation text and is dropped.
        {"role": "assistant", "content": "Consider Portugal."},
    ]


def test_files_and_attachments_become_placeholders_and_empty_messages_drop():
    export = [
        {
            "uuid": "c",
            "name": "Files",
            "chat_messages": [
                {
                    "sender": "human",
                    "text": "",
                    "content": [],
                    "files": [
                        {"file_uuid": "1", "file_name": "Jane Doe resume.pdf"},
                        {"file_uuid": "2", "file_name": "photo.PNG"},
                        {"file_uuid": "3", "file_name": "notes"},
                    ],
                },
                {"sender": "assistant", "text": "", "content": []},
                {
                    "sender": "human",
                    "text": "see attached",
                    "content": [{"type": "text", "text": "see attached"}],
                    "attachments": [
                        {
                            "file_name": "data.csv",
                            "file_type": "text/csv",
                            "extracted_content": "secret rows",
                        }
                    ],
                },
                {
                    "sender": "assistant",
                    "text": "Done.",
                    "content": [
                        {"type": "thinking", "thinking": "hmm"},
                        {"type": "tool_use", "name": "search"},
                        {"type": "tool_result", "content": "result"},
                    ],
                },
            ],
        }
    ]
    parsed = parse(export)
    messages = parsed["conversations"][0]["messages"]
    assert messages == [
        {"role": "user", "content": "[file: application/pdf]\n\n[image]\n\n[file]"},
        {"role": "user", "content": "see attached\n\n[file: text/csv]"},
        # Top-level text is the fallback when no text block exists.
        {"role": "assistant", "content": "Done."},
    ]
    blob = json.dumps(parsed)
    assert "Jane Doe" not in blob and "secret rows" not in blob
    assert "1 empty messages" in parsed["notes"]


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


def test_process_one_file_normalizes_chatgpt_export(tmp_path):
    """A ChatGPT mapping-tree export is linearized to the standard schema."""
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
    assert meta.source_guess == "chatgpt-json"
    assert out is not None
    assert looks_like_parsed_chat_json(out)


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


def test_cli_prints_dropped_conversation_counts_per_file(
    tmp_path, monkeypatch, capsys
):
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

    captured = capsys.readouterr().out
    assert (
        "[JSON] export_a/conversations.json: kept 1 conversations, "
        "dropped 1 empty conversations"
    ) in captured
    written = json.loads((out_root / "export_a" / "conversations.json").read_text())
    assert "stats" not in written
