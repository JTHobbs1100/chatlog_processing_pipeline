"""Shared chat-loader imports used by pipeline companion tools.

This module centralizes access to the transcript-loading helpers provided by
``llm_delusions_annotations`` so the parsing package has a single import surface
to update when it is extracted into a standalone repository.
"""

from __future__ import annotations

from llm_delusions_annotations.chat import (
    Chat,
    iter_chat_json_files,
    iter_loaded_chats,
    load_chats_for_file,
    load_chats_from_directory,
    parse_date_label,
    resolve_bucket_and_rel_path,
)

__all__ = [
    "Chat",
    "iter_chat_json_files",
    "iter_loaded_chats",
    "load_chats_for_file",
    "load_chats_from_directory",
    "parse_date_label",
    "resolve_bucket_and_rel_path",
]
