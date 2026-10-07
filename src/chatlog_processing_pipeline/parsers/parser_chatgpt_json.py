"""Normalizer for ChatGPT `conversations.json` exports.

ChatGPT exports each conversation as a branching tree (`mapping`) rather than
a single thread. Branches come from regenerated responses, edited-and-resent
turns, and tool or retrieval steps. This module linearizes each tree into the
same schema the Claude normalizer produces:
``{"conversations": [{"title", "uuid", "created_at", "updated_at",
"messages": [{"role", "content"}]}]}``.

Linearization policy:

* If the export names a ``current_node``, follow its parent chain to the root.
  Otherwise pick the deepest leaf by parent-depth and walk its ancestors.
* Omit nodes flagged ``is_visually_hidden_from_conversation`` (typically
  system, tool, or context messages). They never appear in the user-facing
  conversation, although they can influence the visible reply.
* Keep only user and assistant turns. Non-text parts and attachments become
  placeholders such as ``[image]``, ``[audio]``, ``[audio/video]`` and
  ``[file: application/pdf]`` so turn order and context survive. Reasoning
  nodes (``thoughts``, ``reasoning_recap``), turns with nothing at all, and
  visible system/tool nodes are dropped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .parser_chatgpt_md import ParseFailed

Parsed = Dict[str, Any]

_KEPT_ROLES = {"user", "assistant"}


def _is_conversation(conv: Any) -> bool:
    return isinstance(conv, dict) and isinstance(conv.get("mapping"), dict)


def _conversations_from(data: Any) -> Optional[list]:
    if isinstance(data, dict):
        data = data.get("conversations")
    if isinstance(data, list):
        return data
    return None


def looks_like_chatgpt_export(data: Any) -> bool:
    """Return True if ``data`` is a list of ChatGPT mapping-tree conversations."""

    convs = _conversations_from(data)
    if not convs:
        return False
    return any(_is_conversation(conv) for conv in convs)


def _part_placeholder(content_type: str) -> str:
    """Placeholder for a non-text message part, based on its content type."""

    kind = content_type.lower()
    if "image" in kind:
        return "[image]"
    if "audio" in kind and "video" in kind:
        return "[audio/video]"
    if "audio" in kind:
        return "[audio]"
    if "video" in kind:
        return "[video]"
    return f"[{content_type or 'non-text content'}]"


def _attachment_placeholder(mime: Any, has_image_part: bool) -> Optional[str]:
    """Placeholder for a metadata attachment, or None if already represented."""

    mime_type = mime.strip().lower() if isinstance(mime, str) else ""
    if mime_type.startswith("image/"):
        return None if has_image_part else "[image]"
    if mime_type.startswith("video/"):
        return "[video]"
    if mime_type.startswith("audio/"):
        return "[audio]"
    return f"[file: {mime_type}]" if mime_type else "[file]"


def _node_text(message: Dict[str, Any]) -> str:
    """Message text with placeholders for non-text parts and attachments.

    Reasoning nodes (``thoughts``, ``reasoning_recap``) carry no ``parts`` or
    ``text`` and are intentionally left empty so they are dropped.
    """

    content = message.get("content")
    if not isinstance(content, dict):
        return ""
    fragments: List[str] = []
    has_image_part = False
    parts = content.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, str):
                fragments.append(part)
            elif isinstance(part, dict):
                value = part.get("text") or part.get("content")
                if isinstance(value, str) and value.strip():
                    fragments.append(value)
                elif part.get("content_type"):
                    placeholder = _part_placeholder(str(part["content_type"]))
                    has_image_part = has_image_part or placeholder == "[image]"
                    fragments.append(placeholder)
    if not fragments and isinstance(content.get("text"), str):
        fragments.append(content["text"])
    metadata = message.get("metadata")
    attachments = metadata.get("attachments") if isinstance(metadata, dict) else None
    if isinstance(attachments, list) and (
        fragments or content.get("content_type") in ("text", "multimodal_text")
    ):
        for attachment in attachments:
            if isinstance(attachment, dict):
                placeholder = _attachment_placeholder(
                    attachment.get("mime_type"), has_image_part
                )
                if placeholder:
                    fragments.append(placeholder)
    return "\n".join(fragment for fragment in fragments if fragment.strip()).strip()


def _is_hidden(message: Dict[str, Any]) -> bool:
    metadata = message.get("metadata")
    return bool(
        isinstance(metadata, dict) and metadata.get("is_visually_hidden_from_conversation")
    )


def _depth(mapping: Dict[str, Any], node_id: str) -> int:
    depth = 0
    seen = {node_id}
    parent = (mapping.get(node_id) or {}).get("parent")
    while isinstance(parent, str) and parent in mapping and parent not in seen:
        seen.add(parent)
        depth += 1
        parent = (mapping.get(parent) or {}).get("parent")
    return depth


def _leaf_ids(mapping: Dict[str, Any]) -> List[str]:
    """Nodes that no other node names as its parent or child."""

    has_child: set = set()
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        parent = node.get("parent")
        if isinstance(parent, str):
            has_child.add(parent)
        children = node.get("children")
        if isinstance(children, list) and children:
            has_child.add(node_id)
    return [node_id for node_id in mapping if node_id not in has_child]


def _chain_to_root(mapping: Dict[str, Any], leaf_id: str) -> List[str]:
    chain: List[str] = []
    seen: set = set()
    node_id: Any = leaf_id
    while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        chain.append(node_id)
        node_id = (mapping.get(node_id) or {}).get("parent")
    chain.reverse()
    return chain


def _choose_path(conv: Dict[str, Any]) -> List[str]:
    mapping = conv["mapping"]
    current = conv.get("current_node")
    if isinstance(current, str) and current in mapping:
        return _chain_to_root(mapping, current)
    leaves = _leaf_ids(mapping) or list(mapping)
    if not leaves:
        return []
    deepest = max(leaves, key=lambda nid: _depth(mapping, nid))
    return _chain_to_root(mapping, deepest)


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        stamp = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_conversation(conv: Dict[str, Any]) -> Dict[str, Any]:
    mapping = conv["mapping"]
    messages: List[Dict[str, str]] = []
    for node_id in _choose_path(conv):
        node = mapping.get(node_id)
        message = node.get("message") if isinstance(node, dict) else None
        if not isinstance(message, dict) or _is_hidden(message):
            continue
        author = message.get("author")
        role = str(author.get("role") if isinstance(author, dict) else "").strip().lower()
        if role not in _KEPT_ROLES:
            continue
        text = _node_text(message)
        if text:
            messages.append({"role": role, "content": text})
    title = conv.get("title")
    return {
        "title": title if isinstance(title, str) else "",
        "uuid": conv.get("conversation_id") or conv.get("id"),
        "created_at": _iso(conv.get("create_time")),
        "updated_at": _iso(conv.get("update_time")),
        "messages": messages,
    }


def normalize_conversations(convs: list) -> List[Dict[str, Any]]:
    """Normalize each mapping-tree conversation; other entries are skipped.

    Conversations with no remaining messages are dropped.
    """

    normalized = (_normalize_conversation(c) for c in convs if _is_conversation(c))
    return [conv for conv in normalized if conv["messages"]]


def parse(data: Any) -> Parsed:
    """Normalize a loaded ChatGPT `conversations.json` payload."""

    if not looks_like_chatgpt_export(data):
        raise ParseFailed("chatgpt json: no mapping-tree conversations found")
    source = [c for c in _conversations_from(data) if _is_conversation(c)]
    conversations = normalize_conversations(source)
    notes = "chatgpt_json_normalized: current_node chain, hidden nodes omitted"
    dropped = len(source) - len(conversations)
    if dropped:
        notes += f"; dropped {dropped} conversations with no content"
    return {
        "conversations": conversations,
        "notes": notes,
        "dropped_conversations": dropped,
        "dropped_messages": None,
    }
