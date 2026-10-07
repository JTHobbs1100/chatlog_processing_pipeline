"""Tests for the --only-conversations filter."""

import zipfile

from chatlog_processing_pipeline.processor import _process_one_file
from chatlog_processing_pipeline.util import is_conversations_json

from pathlib import Path


def test_is_conversations_json_matches_plain_and_sharded_names():
    assert is_conversations_json(Path("conversations.json"))
    assert is_conversations_json(Path("a/b/conversations-001.json"))
    assert is_conversations_json(Path("Conversations-014.JSON"))
    assert not is_conversations_json(Path("user.json"))
    assert not is_conversations_json(Path("shared_conversations.json"))
    assert not is_conversations_json(Path("conversations-abc.json"))
    assert not is_conversations_json(Path("chat.html"))


def test_zip_members_are_filtered(tmp_path):
    in_root = tmp_path / "in"
    out_root = tmp_path / "out"
    in_root.mkdir()
    out_root.mkdir()
    with zipfile.ZipFile(in_root / "export.zip", "w") as z:
        z.writestr("conversations-000.json", "[]")
        z.writestr("conversations-001.json", "[]")
        z.writestr("user.json", '{"email": "a@b.com"}')
        z.writestr("chat.html", "<html></html>")
        z.writestr("file_0001.dat", b"\x00\x01")

    _process_one_file(
        in_root / "export.zip",
        in_root,
        out_root,
        False,
        False,
        only_conversations=True,
    )

    written = sorted(p.name for p in out_root.rglob("*") if p.is_file())
    assert written == ["conversations-000.json", "conversations-001.json"]
