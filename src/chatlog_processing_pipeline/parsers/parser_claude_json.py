"""Normalizer for Claude.ai `conversations.json` data exports.

Claude's export is a flat JSON array of conversation objects, each holding a
`chat_messages` list with `sender: human|assistant` turns. Unlike ChatGPT's
mapping-tree export, there is no branch structure to resolve, so this parser
normalizes directly to the pipeline's `{"conversations": [{"messages": [...]}]}`
schema instead of passing the raw payload through.
"""

from __future__ import annotations

import mimetypes
from typing import Any, Dict, List

from .parser_chatgpt_md import ParseFailed

Parsed = Dict[str, Any]

_SENDER_TO_ROLE = {
    "human": "user",
    "assistant": "assistant",
}


def _file_placeholder(file_name: Any = None, mime: Any = None) -> str:
    """Placeholder for an uploaded file; names are never recorded."""

    mime_type = mime.strip().lower() if isinstance(mime, str) else ""
    if not mime_type and isinstance(file_name, str):
        mime_type = (mimetypes.guess_type(file_name)[0] or "").lower()
    if mime_type.startswith("image/"):
        return "[image]"
    if mime_type.startswith("video/"):
        return "[video]"
    if mime_type.startswith("audio/"):
        return "[audio]"
    return f"[file: {mime_type}]" if mime_type else "[file]"


def _message_content(message: Dict[str, Any]) -> str:
    """Return the text of one Claude chat message, with file placeholders.

    Thinking and tool blocks are not conversation text and are dropped.
    Uploaded files and attachments become placeholders such as ``[image]`` or
    ``[file: application/pdf]``; their names and extracted text are not kept.
    """

    parts: List[str] = []
    content_blocks = message.get("content")
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)

    if not parts:
        fallback = message.get("text")
        if isinstance(fallback, str) and fallback.strip():
            parts.append(fallback)

    for uploaded in message.get("files") or []:
        if isinstance(uploaded, dict):
            parts.append(_file_placeholder(uploaded.get("file_name")))
    for attachment in message.get("attachments") or []:
        if isinstance(attachment, dict):
            parts.append(
                _file_placeholder(attachment.get("file_name"), attachment.get("file_type"))
            )
    return "\n\n".join(parts)


def _has_claude_chat_messages(conversation: Any) -> bool:
    """Return True if `conversation` looks like a Claude conversation object."""

    if not isinstance(conversation, dict):
        return False
    chat_messages = conversation.get("chat_messages")
    if not isinstance(chat_messages, list) or not chat_messages:
        return False
    return any(
        isinstance(message, dict) and message.get("sender") in _SENDER_TO_ROLE
        for message in chat_messages
    )


def looks_like_claude_export(data: Any) -> bool:
    """Return True if `data` matches the shape of a Claude `conversations.json`."""

    if not isinstance(data, list) or not data:
        return False
    return any(_has_claude_chat_messages(conv) for conv in data)


def parse(data: Any) -> Parsed:
    """Normalize a loaded Claude `conversations.json` payload.

    Parameters
    ----------
    data:
        The already-JSON-decoded top-level list from a Claude export.

    Returns
    -------
    Parsed
        ``{"conversations": [{"title": str, "messages": [...]}], "notes": str}``
    """

    if not looks_like_claude_export(data):
        raise ParseFailed("claude json: no chat_messages with human/assistant sender")

    conversations: List[Dict[str, Any]] = []
    empty_messages = 0
    empty_conversations = 0
    for conv in data:
        if not isinstance(conv, dict):
            continue
        chat_messages = conv.get("chat_messages")
        messages: List[Dict[str, str]] = []
        if isinstance(chat_messages, list):
            for message in chat_messages:
                if not isinstance(message, dict):
                    continue
                role = _SENDER_TO_ROLE.get(message.get("sender"))
                if role is None:
                    continue
                content = _message_content(message)
                if not content:
                    empty_messages += 1
                    continue
                messages.append({"role": role, "content": content})

        if not messages:
            empty_conversations += 1
            continue
        conversations.append(
            {
                "title": conv.get("name") or "",
                "uuid": conv.get("uuid"),
                "created_at": conv.get("created_at"),
                "updated_at": conv.get("updated_at"),
                "messages": messages,
            }
        )

    notes = "claude_json_normalized"
    if empty_messages or empty_conversations:
        notes += (
            f"; dropped {empty_messages} empty messages and "
            f"{empty_conversations} conversations with no content"
        )
    return {
        "conversations": conversations,
        "notes": notes,
        "dropped_conversations": empty_conversations,
        "dropped_messages": empty_messages,
    }
