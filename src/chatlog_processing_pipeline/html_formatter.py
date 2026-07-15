"""Render parsed chat logs as reviewer-friendly HTML or plain text.

This module formats parsed transcript JSON files into reviewer-oriented HTML or
plain text exports for local inspection.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import List

from chatlog_processing_pipeline.chat_loader import (
    Chat,
    iter_chat_json_files,
    load_chats_for_file,
    load_chats_from_directory,
    parse_date_label,
)

_DEFAULT_GDOCS_CSS = (
    "body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, "
    "Helvetica, Arial, sans-serif; line-height: 1.45; color: #111; }\n"
)
_ASSET_DIR = Path(__file__).with_name("assets")
_CHAT_SECTION_SEPARATOR = '<hr class="chat-sep">\n<div class="page-break"></div>\n'

# -------------------------- Data structures ---------------------------


@lru_cache(maxsize=1)
def _load_order_toggle_js() -> str:
    """Load and cache the JavaScript used for toggling chat order."""

    js_path = _ASSET_DIR / "gdocs_order_toggle.js"
    try:
        return js_path.read_text(encoding="utf-8")
    except OSError as err:
        sys.stderr.write(
            "[WARN] Failed to read order toggle script " f"{js_path}: {err}\n"
        )
        return ""


@lru_cache(maxsize=1)
def _load_gdocs_css() -> str:
    """Load and cache the shared CSS used for Google Docs exports."""

    css_path = _ASSET_DIR / "gdocs_styles.css"
    try:
        return css_path.read_text(encoding="utf-8")
    except OSError as err:
        sys.stderr.write(
            "[WARN] Failed to read gdocs style sheet " f"{css_path}: {err}\n"
        )
        return _DEFAULT_GDOCS_CSS


# --------------------------- Render: HTML ------------------------------


def _escape_text_to_html(text: str) -> str:
    """Escape text for safe HTML rendering and preserve newlines as <br>.

    Args:
        text: Raw text to escape.

    Returns:
        Escaped HTML string with newline breaks.
    """

    return html.escape(text).replace("\n", "<br>\n")


def _render_role_filter_controls() -> str:
    """Return HTML controls for toggling message visibility by role."""

    role_rows: List[str] = []
    for role_slug, label in (
        ("user", "User"),
        ("assistant", "Assistant"),
        ("tool", "Tool"),
    ):
        role_rows.append(
            '<div class="role-filter-row">'
            + '<span class="role-filter-role">'
            + label
            + "</span>"
            + '<label><input type="radio" name="role-'
            + role_slug
            + '" value="show" checked> Show</label>'
            + '<label><input type="radio" name="role-'
            + role_slug
            + '" value="hide"> Hide</label>'
            + "</div>"
        )
    return (
        '<fieldset class="role-filter-group">'
        '<legend class="role-filter-legend">Roles</legend>'
        + "".join(role_rows)
        + "</fieldset>\n"
    )


def _format_message_count_label(count: int) -> str:
    """Return a short label for a message count.

    Args:
        count: Total number of messages.

    Returns:
        Label such as "1 message" or "3 messages".
    """

    noun = "msg" if count == 1 else "msgs"
    return f"{count} {noun}"


def _sort_chats_by_date(chats: List[Chat]) -> List[Chat]:
    """Return chats sorted by parsed date (newest first).

    If no chats have a usable date label, preserve the original ordering
    provided by the loader instead of falling back to alphabetical keys.
    """

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    # Detect whether all chats have a parsed date. If any are missing dates,
    # keep the input order to avoid reordering based on titles or keys.
    has_all_dates = all(parse_date_label(c.date_label) is not None for c in chats)
    if not has_all_dates:
        return list(chats)

    def sort_key(chat: Chat) -> tuple[bool, float, str]:
        dt_val = parse_date_label(chat.date_label)
        if dt_val is None:
            return (False, epoch.timestamp(), chat.key.lower())
        timestamp = dt_val.timestamp()
        return (True, timestamp, chat.key.lower())

    return sorted(chats, key=sort_key, reverse=True)


def _render_message_html(idx: int, role: str, content: str) -> str:
    """Render a single message block in HTML.

    Args:
        idx: Message index (0-based).
        role: Message role (user, assistant, or other).
        content: Message content.

    Returns:
        HTML snippet for the message.
    """

    normalized_role = (role or "").strip().lower()
    role_label = {
        "user": "User",
        "assistant": "Assistant",
        "tool": "Tool",
    }.get(normalized_role, role.title() if role else "Unknown")
    role_class = {
        "user": "msg-user",
        "assistant": "msg-assistant",
        "tool": "msg-tool",
    }.get(normalized_role, "msg-other")
    role_slug = re.sub(r"[^a-z0-9]+", "-", normalized_role) or "unknown"
    body = _escape_text_to_html(content)
    return (
        '<div class="message '
        + role_class
        + " msg-role-"
        + role_slug
        + '" data-role="'
        + role_slug
        + '" data-manual-state="visible">\n      <div class="meta">'
        + str(idx + 1)
        + ". "
        + role_label
        + '</div>\n      <div class="message-controls">'
        + '<button type="button" class="message-toggle" data-state="visible">'
        + "Hide message"
        + "</button>"
        + '<span class="filter-indicator" hidden></span>'
        + '</div>\n      <div class="content">'
        + body
        + "</div>\n    </div>\n"
    )


def _render_document_head(title: str) -> str:
    """Return the HTML head block for an aggregate transcript document.

    Parameters
    ----------
    title:
        Document title.

    Returns
    -------
    str
        HTML opening markup including the style block.
    """

    css = _load_gdocs_css()
    style_block = "<style>\n" + css + "\n</style>\n" if css else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        '<head>\n  <meta charset="utf-8">\n  '
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n  '
        + "<title>"
        + html.escape(title)
        + "</title>\n"
        + style_block
        + "</head>\n<body>\n"
    )


def _render_document_header(title: str) -> str:
    """Return the aggregate document header block.

    Parameters
    ----------
    title:
        Document title.

    Returns
    -------
    str
        Rendered document heading and subtitle block.
    """

    return (
        '<div class="doc-title">'
        + html.escape(title)
        + "</div>\n"
        + '<div class="subtitle">'
        + "Each chat is a section with a page break following it."
        + "</div>\n"
    )


def _render_order_controls(has_multiple: bool) -> str:
    """Return the order-control toolbar for aggregate HTML output.

    Parameters
    ----------
    has_multiple:
        Whether the document contains more than one chat.

    Returns
    -------
    str
        HTML block containing ordering and filtering controls.
    """

    order_button = (
        '<button id="order-toggle" type="button" class="order-toggle">'
        "Show Oldest First"
        "</button>"
        if has_multiple
        else ""
    )
    expand_all_button = (
        '<button id="expand-collapse-all" type="button" class="order-toggle">'
        "Expand All Chats"
        "</button>"
    )
    order_note = (
        '<div class="order-note">'
        + "Chat ## labels follow the current newest-first ordering. "
        + "Use the controls above each chat to change order or navigate quickly."
        + "</div>"
    )
    return (
        '<div class="order-controls">'
        + order_button
        + expand_all_button
        + _render_role_filter_controls()
        + order_note
        + "</div>\n"
    )


def _render_toc_item(index: int, chat: Chat) -> str:
    """Return one table-of-contents item for an aggregate transcript export.

    Parameters
    ----------
    index:
        Zero-based chat index in the rendered order.
    chat:
        Chat object to describe.

    Returns
    -------
    str
        Rendered HTML for one TOC row.
    """

    anchor = "chat-" + str(index + 1)
    label = str(index + 1).zfill(2)
    msg_label = _format_message_count_label(len(chat.messages))
    return (
        '<li class="toc-item" data-index="'
        + str(index)
        + '"><a href="#'
        + anchor
        + '"><span class="chat-label">Chat '
        + label
        + "</span> ("
        + msg_label
        + "): "
        + html.escape(chat.key)
        + "</a></li>"
    )


def _render_chat_actions(index: int, total_chats: int) -> str:
    """Return the navigation/action row for one rendered chat section.

    Parameters
    ----------
    index:
        Zero-based chat index in the rendered order.
    total_chats:
        Total number of chats in the document.

    Returns
    -------
    str
        HTML action row for the chat section.
    """

    prev_disabled = ' disabled="disabled"' if index == 0 else ""
    next_disabled = ' disabled="disabled"' if index == total_chats - 1 else ""
    return (
        '<div class="chat-actions">'
        '<button type="button" class="chat-nav chat-nav-prev" data-dir="-1"'
        + prev_disabled
        + ">Previous</button>"
        '<button type="button" class="chat-toggle" data-state="expanded">'
        "Hide Chat"
        "</button>"
        '<button type="button" class="chat-nav chat-nav-next" data-dir="1"'
        + next_disabled
        + ">Next</button>"
        "</div>\n"
    )


def _render_chat_section(
    index: int,
    total_chats: int,
    chat: Chat,
    include_notes: bool,
) -> str:
    """Return one rendered chat section for aggregate HTML output.

    Parameters
    ----------
    index:
        Zero-based chat index in the rendered order.
    total_chats:
        Total number of chats being rendered.
    chat:
        Chat object to render.
    include_notes:
        Whether to include parser notes for the chat.

    Returns
    -------
    str
        Rendered HTML for one chat section.
    """

    anchor = "chat-" + str(index + 1)
    label = str(index + 1).zfill(2)
    msg_label = _format_message_count_label(len(chat.messages))
    heading = (
        '<h2 id="'
        + anchor
        + '" class="chat-heading" tabindex="-1" data-title="'
        + html.escape(chat.key)
        + '"><span class="chat-label">Chat '
        + label
        + "</span> ("
        + msg_label
        + "): "
        + html.escape(chat.key)
        + "</h2>\n"
    )
    date_line = (
        '<div class="meta-line">Date: ' + html.escape(chat.date_label) + "</div>\n"
        if chat.date_label
        else ""
    )
    notes = (
        '<div class="notes">Notes: ' + html.escape(chat.notes) + "</div>\n"
        if include_notes and chat.notes
        else ""
    )
    messages = "\n".join(
        _render_message_html(msg_index, msg.get("role", ""), msg.get("content", ""))
        for msg_index, msg in enumerate(chat.messages)
    )
    body = (
        '<div class="chat-body" data-collapsed="false">'
        + date_line
        + notes
        + messages
        + _CHAT_SECTION_SEPARATOR
        + "</div>\n"
    )
    return (
        '<section class="chat" data-index="'
        + str(index)
        + '">'
        + heading
        + _render_chat_actions(index, total_chats)
        + body
        + "</section>\n"
    )


# ------------------------ Render: Aggregate ---------------------------


def render_html_aggregate(chats: List[Chat], title: str, include_notes: bool) -> str:
    """Render many chats in a single HTML document with a TOC and headings.

    Args:
        chats: List of Chat objects.
        title: Document title for the aggregate export.
        include_notes: Whether to include parser notes under each chat header.

    Returns:
        A complete HTML document string containing all chats.
    """

    ordered_chats = _sort_chats_by_date(chats)
    toc_html = "\n".join(
        _render_toc_item(index, chat) for index, chat in enumerate(ordered_chats)
    )

    parts: List[str] = [
        _render_document_head(title),
        _render_document_header(title),
        _render_order_controls(len(ordered_chats) > 1),
        (
            '<div class="toc"><h2>Contents</h2><ol id="toc-list">'
            + toc_html
            + "</ol></div>\n"
        ),
        '<div id="chat-container">\n',
    ]

    for index, chat in enumerate(ordered_chats):
        parts.append(
            _render_chat_section(index, len(ordered_chats), chat, include_notes)
        )

    parts.append("</div>\n")
    parts.append(
        '<button type="button" id="scroll-to-chat-start" '
        'class="floating-scroll-button" hidden>Jump to chat start</button>\n'
    )
    js_code = _load_order_toggle_js().rstrip("\n")
    if js_code:
        parts.append("<script>\n")
        parts.append(js_code)
        parts.append("\n</script>\n")

    parts.append("</body></html>\n")
    return "".join(parts)


def render_txt_aggregate(chats: List[Chat], include_notes: bool) -> str:
    """Render many chats in a single plain text document.

    Args:
        chats: List of Chat objects.
        include_notes: Whether to include parser notes under each chat header.

    Returns:
        A plain text document string containing all chats.
    """

    sorted_chats = _sort_chats_by_date(chats)

    out: List[str] = []
    for i, c in enumerate(sorted_chats):
        out.append("===== Chat " + str(i + 1) + ": " + c.key + " =====")
        if c.date_label:
            out.append("[date] " + c.date_label)
        if include_notes and c.notes:
            out.append("[notes] " + c.notes)
        for mi, m in enumerate(c.messages):
            out.append("")
            role = m.get("role", "").upper() or "UNKNOWN"
            out.append("(" + str(mi + 1) + ") " + role + ":")
            out.append(m.get("content", ""))
        out.append("")
        out.append("----- END OF CHAT -----")
        out.append("")
    return "\n".join(out)


# ------------------------------- Main ---------------------------------


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the exporter.

    Args:
        argv: Optional list of arguments to parse.

    Returns:
        Parsed arguments namespace.
    """

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", help="Directory containing parsed chat JSONs")
    parser.add_argument(
        "output",
        help="Output directory (per-file mode) or output file (aggregate mode)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["html", "txt"],
        default="html",
        help="Output format",
    )
    parser.add_argument(
        "--mode",
        choices=["per-file", "aggregate"],
        default="per-file",
        help="Export mode: per-file (default) or single aggregate file",
    )
    parser.add_argument(
        "--include-notes",
        action="store_true",
        help="Include parser notes in output",
    )
    parser.add_argument(
        "--title-prefix",
        default="Chat",
        help="Title prefix for HTML documents",
    )
    parser.add_argument(
        "--max-chats",
        type=int,
        default=None,
        help="Limit number of chats processed",
    )
    parser.add_argument(
        "--follow-links",
        action="store_true",
        help="Follow symlinked directories when scanning input",
    )
    return parser.parse_args(argv)


def _ensure_output_dir(out_dir: Path) -> bool:
    """Create an output directory and report errors to stderr.

    Parameters
    ----------
    out_dir:
        Directory to create.

    Returns
    -------
    bool
        True when the directory exists or was created successfully.
    """

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        sys.stderr.write(f"Failed to create output directory {out_dir}: {err}\n")
        return False
    return True


def _write_aggregate_output(args: argparse.Namespace, in_dir: Path) -> int:
    """Render all chats under ``in_dir`` into a single output file.

    Parameters
    ----------
    args:
        Parsed formatter arguments.
    in_dir:
        Input directory containing parsed JSON files.

    Returns
    -------
    int
        Exit status code.
    """

    chats = load_chats_from_directory(
        in_dir, followlinks=args.follow_links, limit=args.max_chats
    )
    if not chats:
        sys.stderr.write("No chats found (no .json files with messages).\n")
        return 1

    out_file = Path(args.output).expanduser().resolve()
    if not _ensure_output_dir(out_file.parent):
        return 2

    rendered = (
        render_html_aggregate(chats, args.title_prefix, args.include_notes)
        if args.format == "html"
        else render_txt_aggregate(chats, args.include_notes)
    )
    try:
        out_file.write_text(rendered, encoding="utf-8")
    except OSError as err:
        sys.stderr.write(f"Failed to write output file {out_file}: {err}\n")
        return 2
    print("Wrote aggregate:", str(out_file))
    return 0


def _write_per_file_output(args: argparse.Namespace, in_dir: Path) -> int:
    """Render one output file per transcript JSON under ``in_dir``.

    Parameters
    ----------
    args:
        Parsed formatter arguments.
    in_dir:
        Input directory containing parsed JSON files.

    Returns
    -------
    int
        Exit status code.
    """

    out_dir = Path(args.output).expanduser().resolve()
    if not _ensure_output_dir(out_dir):
        return 2

    files = list(iter_chat_json_files(in_dir, followlinks=args.follow_links))
    written = 0
    for fp in files:
        rel = fp.relative_to(in_dir)
        chats_for_file = load_chats_for_file(fp)
        if not chats_for_file:
            continue
        out_rel = rel.with_suffix(".html" if args.format == "html" else ".txt")
        out_path = out_dir / out_rel
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            sys.stderr.write(
                f"[WARN] Could not create directory {out_path.parent}: {err}\n"
            )
            continue

        if args.format == "html":
            # Combine all conversations in this file into one doc with sections
            title = f"{args.title_prefix}: {rel}"
            doc = render_html_aggregate(chats_for_file, title, args.include_notes)
        else:
            doc = render_txt_aggregate(chats_for_file, args.include_notes)
        try:
            out_path.write_text(doc, encoding="utf-8")
            written += 1
        except OSError as err:
            sys.stderr.write(f"[WARN] Failed to write {out_path}: {err}\n")

    print(f"Processed files: {written} (from {len(files)} JSON files)")
    print(f"Output directory: {out_dir}")
    return 0


def main(argv: List[str] | None = None) -> int:
    """Render parsed chats to HTML or plain text.

    Parameters
    ----------
    argv:
        Optional list of arguments (useful for testing).

    Returns
    -------
    int
        Exit code: 0 on success; non-zero on errors.
    """

    args = parse_args(argv)
    in_dir = Path(args.input).expanduser().resolve()
    if not in_dir.exists() or not in_dir.is_dir():
        sys.stderr.write(f"Input directory not found: {in_dir}\n")
        return 2
    if args.mode == "aggregate":
        return _write_aggregate_output(args, in_dir)
    return _write_per_file_output(args, in_dir)


if __name__ == "__main__":
    raise SystemExit(main())
