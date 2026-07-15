# Chatlog Processing Pipeline

A standalone package for parsing, anonymizing, and reviewing exported chat
transcripts.

## Install

This repo is set up for `uv`.

```bash
make init
```

That will:
- create `.venv`
- sync runtime and dev dependencies
- install the local sibling repo `../llm-delusions-annotations` as an editable
  dependency via `tool.uv.sources`

The reviewer UI assets are checked into
`src/chatlog_processing_pipeline/assets/`.

## Commands

- `process_chats --parse --input <INPUT_DIR> --output-dir <PARSED_OUT>`
- `process_chats --anon --input <PARSED_DIR> --anon-output <ANON_OUT>`
- `process_chats_plan --input <INPUT_DIR> --generate-plan <PLAN.csv>`
- `process_chats_plan --input <INPUT_DIR> --plan <PLAN.csv> --output-dir <PARSED_OUT>`
- `format_chats_html <PARSED_DIR> <OUT_DIR>`
- `format_chats_html <PARSED_DIR> <OUT_FILE> --mode aggregate`
- `find_duplicate_contents --root <DIR_A> --root <DIR_B>`

## Parsing

`process_chats --parse` converts raw transcript exports into normalized JSON.
Supported source formats include ChatGPT HTML and JSON exports, PDFs, DOCX,
RTF, ODT, TXT, and ZIP containers.

Basic example:

```bash
process_chats \
  --parse \
  --input raw_transcripts \
  --output-dir parsed_transcripts
```

You can force one method for a full run:

```bash
process_chats \
  --parse \
  --input raw_transcripts \
  --output-dir parsed_transcripts \
  --method pdf_text
```

If a raw file contains multiple conversations in one text stream, pass
`--conv-separator` with either a literal string or a regex.

If turns are written inline as labeled text such as `Person: ...` and
`Assistant: ...`, pass `--role-labels` with pipe-separated labels. The first
label maps to `user` and the remaining labels map to `assistant`.

## ChatGPT Branch Selection

ChatGPT exports often store a conversation as a `mapping` tree rather than a
single linear thread. The parser preserves the raw structure in JSON. When
loading or rendering a conversation as one visible transcript, the pipeline
chooses a branch.

The default path-selection behavior prefers the strongest visible
user/assistant thread rather than simply following the currently active node.
In practice this is meant to avoid short side branches, hidden automation
messages, and regenerate artifacts dominating the visible transcript.

For reviewer-facing HTML, hidden conversation nodes are omitted. This is why
the HTML export can differ from the raw JSON payload: the JSON may contain
multiple branches and hidden tool or system nodes, while the HTML shows one
main visible thread.

## Plan-Based Parsing

Use `process_chats_plan` when a batch needs explicit parser selection, custom
role labels, or file-level skip rules.

Generate a starter plan:

```bash
process_chats_plan \
  --input raw_transcripts \
  --generate-plan plan.csv
```

Run a completed plan:

```bash
process_chats_plan \
  --input raw_transcripts \
  --plan plan.csv \
  --output-dir parsed_transcripts
```

### Plan Columns

- `rel_path` is the path relative to the input root.
- `method` selects the parser. Use `auto` for the default behavior.
- `role_labels` is an optional pipe-separated list of inline turn labels.
- `conv_separator` is an optional conversation split marker or regex.
- `skip` marks a row to ignore.

### Supported Methods

- `auto` runs the default best-effort parser choice.
- `pdf_highlight` uses alternating PDF highlight colors to infer roles.
- `pdf_boxes` segments PDFs using horizontal rule boxes.
- `pdf_text` extracts PDF text and parses it heuristically.
- `docx_titles` uses DOCX title and heading cues.
- `docx_text` uses plain DOCX text extraction and heuristics.
- `chatgpt_html` parses ChatGPT export HTML.
- `chatgpt_json` treats ChatGPT export JSON as pass-through structured input.

Notes:

- JSON files handled as ChatGPT exports are copied through as structured
  pass-through inputs.
- When `conv_separator` is set, text sources are split before parsing each
  segment.

## Anonymization

`process_chats --anon` runs parsed JSON or raw text through Microsoft Presidio
and can redact, replace, mask, hash, or fake identifiers.

Basic example:

```bash
process_chats \
  --anon \
  --input parsed_transcripts \
  --anon-output anonymized_transcripts
```

The anonymizer has separate options for content and file or directory names.
For example, `--operator` controls message-content replacement behavior, while
`--name-operator` controls path-component replacement behavior.

If you pass `--metadata-csv <PATH>`, columns whose names contain `contact` or
`identifier` are used to seed the anonymization blocklist. Full phrases,
individual tokens, and discovered email addresses are added.

## Duplicate Checking

`find_duplicate_contents` scans parsed JSON trees for exact duplicated
`content` strings across one or more roots. This is useful for spotting re-sent
exports or overlap between a new drop and an existing corpus.

Example:

```bash
find_duplicate_contents \
  --root parsed_transcripts \
  --root parsed_transcripts_candidate \
  --min-overlap-percent 90 \
  --min-shared-lines 100
```

The overlap score is computed relative to the smaller file's content count.

## HTML Formatting

`format_chats_html` renders parsed JSON as reviewer-friendly HTML or plain
text.

Directory-to-directory example:

```bash
format_chats_html parsed_transcripts html_exports
```

Aggregate example:

```bash
format_chats_html parsed_transcripts combined.html --mode aggregate
```

The formatter depends on `llm-delusions-annotations` for chat loading helpers.

## Development

```bash
make pyfmt
make pylint
make smoke
```
