"""Tests for the ChatGPT mapping-tree normalizer."""

import json

from chatlog_processing_pipeline.parsers.parser_chatgpt_json import (
    looks_like_chatgpt_export,
    parse,
)
from chatlog_processing_pipeline.processor import _process_one_file


def _node(node_id, parent, role=None, text=None, hidden=False, children=None):
    message = None
    if role:
        message = {
            "author": {"role": role},
            "content": {"content_type": "text", "parts": [text]},
            "metadata": {"is_visually_hidden_from_conversation": True} if hidden else {},
        }
    return {
        "id": node_id,
        "parent": parent,
        "children": children or [],
        "message": message,
    }


def _branching_conversation(**overrides):
    """root -> sys(hidden) -> u1 -> a1_old (regenerated) / a1_new -> u2 -> a2."""
    mapping = {
        "root": _node("root", None),
        "sys": _node("sys", "root", "system", "hidden context", hidden=True),
        "u1": _node("u1", "sys", "user", "hello"),
        "a1_old": _node("a1_old", "u1", "assistant", "first try"),
        "a1_new": _node("a1_new", "u1", "assistant", "second try"),
        "u2": _node("u2", "a1_new", "user", "thanks"),
        "a2": _node("a2", "u2", "assistant", "you are welcome"),
    }
    conv = {
        "title": "Greeting",
        "conversation_id": "conv-1",
        "create_time": 1700000000.0,
        "update_time": 1700000100.0,
        "mapping": mapping,
        "current_node": "a2",
    }
    conv.update(overrides)
    return conv


def _contents(parsed):
    return [(m["role"], m["content"]) for m in parsed["conversations"][0]["messages"]]


def test_follows_current_node_and_skips_other_branches_and_hidden_nodes():
    parsed = parse([_branching_conversation()])
    assert _contents(parsed) == [
        ("user", "hello"),
        ("assistant", "second try"),
        ("user", "thanks"),
        ("assistant", "you are welcome"),
    ]
    conv = parsed["conversations"][0]
    assert conv["title"] == "Greeting"
    assert conv["uuid"] == "conv-1"
    assert conv["created_at"] == "2023-11-14T22:13:20Z"
    assert conv["updated_at"] == "2023-11-14T22:15:00Z"


def test_without_current_node_uses_deepest_leaf_even_with_empty_children():
    parsed = parse([_branching_conversation(current_node=None)])
    assert _contents(parsed)[-1] == ("assistant", "you are welcome")
    assert ("assistant", "first try") not in _contents(parsed)


def test_drops_non_chat_roles_and_reasoning_nodes():
    conv = _branching_conversation()
    conv["mapping"]["tool"] = _node("tool", "a2", "tool", "tool output")
    conv["mapping"]["a3"] = _node("a3", "tool", "assistant", "")
    conv["mapping"]["think"] = _node("think", "a3", "assistant", None)
    conv["mapping"]["think"]["message"]["content"] = {
        "content_type": "thoughts",
        "thoughts": [{"summary": "pondering"}],
    }
    conv["current_node"] = "think"
    contents = _contents(parse([conv]))
    assert {role for role, _ in contents} == {"user", "assistant"}
    assert len(contents) == 4  # empty assistant turn and reasoning node dropped


def test_non_text_parts_and_attachments_become_placeholders():
    conv = _branching_conversation()
    conv["mapping"]["img"] = _node("img", "a2", "user", None)
    conv["mapping"]["img"]["message"]["content"] = {
        "content_type": "multimodal_text",
        "parts": [{"content_type": "image_asset_pointer", "asset_pointer": "x"}, ""],
    }
    conv["mapping"]["img"]["message"]["metadata"] = {
        "attachments": [{"mime_type": "image/png"}]
    }
    conv["mapping"]["mix"] = _node("mix", "img", "user", "summarize this")
    conv["mapping"]["mix"]["message"]["metadata"] = {
        "attachments": [{"mime_type": "application/pdf"}, {"mime_type": "image/jpeg"}]
    }
    conv["mapping"]["aud"] = _node("aud", "mix", "user", None)
    conv["mapping"]["aud"]["message"]["content"] = {
        "content_type": "multimodal_text",
        "parts": [{"content_type": "audio_transcription", "text": ""}],
    }
    conv["current_node"] = "aud"
    contents = [c for _, c in _contents(parse([conv]))][-3:]
    assert contents == [
        "[image]",
        "summarize this\n[file: application/pdf]\n[image]",
        "[audio]",
    ]


def test_detection_ignores_normalized_and_claude_shapes():
    assert looks_like_chatgpt_export([_branching_conversation()])
    assert not looks_like_chatgpt_export(
        {"conversations": [{"messages": [{"role": "user", "content": "x"}]}]}
    )
    assert not looks_like_chatgpt_export([{"chat_messages": []}])


def test_process_one_file_writes_standard_schema(tmp_path):
    in_root, out_root = tmp_path / "in", tmp_path / "out"
    in_root.mkdir()
    out_root.mkdir()
    src = in_root / "conversations-000.json"
    src.write_text(json.dumps([_branching_conversation()]), encoding="utf-8")

    meta, out = _process_one_file(
        src=src, in_root=in_root, out_root=out_root, verbose=False, strict_parsing=False
    )

    assert meta.ok and meta.source_guess == "chatgpt-json" and meta.message_count == 4
    assert set(out) == {"meta", "conversations", "notes", "stats"}
    assert set(out["conversations"][0]) == {
        "title",
        "uuid",
        "created_at",
        "updated_at",
        "messages",
    }


def test_conversations_with_no_content_are_dropped_and_counted():
    empty = _branching_conversation(title="Empty")
    empty["mapping"] = {"root": _node("root", None)}
    empty["current_node"] = "root"
    parsed = parse([empty, _branching_conversation()])
    assert [c["title"] for c in parsed["conversations"]] == ["Greeting"]
    assert "dropped 1 conversations" in parsed["notes"]
