"""Normalizer for Claude.ai `conversations.json` data exports.

Claude's export is a flat JSON array of conversation objects, each holding a
`chat_messages` list with `sender: human|assistant` turns. Unlike ChatGPT's
mapping-tree export, there is no branch structure to resolve, so this parser
normalizes directly to the pipeline's `{"conversations": [{"messages": [...]}]}`
schema instead of passing the raw payload through.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .parser_chatgpt_md import ParseFailed

Parsed = Dict[str, Any]

_SENDER_TO_ROLE = {
    "human": "user",
    "assistant": "assistant",
}


def _message_content(message: Dict[str, Any]) -> str:
    """Return the best-effort text content of one Claude chat message."""

    parts: List[str] = []
    content_blocks = message.get("content")
    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
            elif block_type == "thinking":
                text = block.get("thinking")
            else:
                text = None
            if isinstance(text, str) and text.strip():
                parts.append(text)

    if parts:
        return "\n\n".join(parts)

    fallback = message.get("text")
    return fallback if isinstance(fallback, str) else ""


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
                messages.append({"role": role, "content": _message_content(message)})

        conversations.append(
            {
                "title": conv.get("name") or "",
                "uuid": conv.get("uuid"),
                "created_at": conv.get("created_at"),
                "updated_at": conv.get("updated_at"),
                "messages": messages,
            }
        )

    return {
        "conversations": conversations,
        "notes": "claude_json_normalized",
    }
