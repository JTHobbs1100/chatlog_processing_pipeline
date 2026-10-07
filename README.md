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
- install the local sibling repo `../llm-general-annotations` as an editable
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
Supported source formats include ChatGPT HTML and JSON exports, Claude.ai JSON
exports, PDFs, DOCX, RTF, ODT, TXT, and ZIP containers.

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

Pass `--only-conversations` to process only `conversations.json` and sharded
`conversations-NNN.json` files, including inside zips.

If a raw file contains multiple conversations in one text stream, pass
`--conv-separator` with either a literal string or a regex.

If turns are written inline as labeled text such as `Person: ...` and
`Assistant: ...`, pass `--role-labels` with pipe-separated labels. The first
label maps to `user` and the remaining labels map to `assistant`.

## ChatGPT Branch Selection

ChatGPT exports store a conversation as a `mapping` tree rather than a single
thread. Branches come from regenerated responses, edited-and-resent turns, and
tool or retrieval steps. `--parse` linearizes each tree into one thread:

- If the export names a `current_node`, follow its parent chain to the root.
  Otherwise take the deepest leaf by parent-depth and walk its ancestors.
- Omit nodes flagged `is_visually_hidden_from_conversation` (typically
  system, tool, or context messages). They are not shown in the UI, although
  they can influence the visible reply.
- Keep only `user` and `assistant` turns. Non-text parts and attachments
  become placeholders so turn order and context survive: `[image]`,
  `[audio]`, `[video]`, `[audio/video]`, and `[file: <mime type>]` for
  attachments such as PDFs (file names are not recorded). A turn with text and
  an attachment keeps the text and appends the placeholder.
- Drop model reasoning nodes (`thoughts`, `reasoning_recap`), turns with
  nothing in them, visible system or tool nodes, and all other branches.

Conversation `id`, `create_time` and `update_time` are kept as `uuid`,
`created_at` and `updated_at`. ChatGPT HTML exports (`chat.html`) are
normalized the same way.

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
- `chatgpt_json` normalizes ChatGPT `conversations.json` exports (mapping
  trees) into the standard linear `messages` schema.
- `claude_json` normalizes Claude.ai `conversations.json` exports into the
  standard `messages` schema.

Notes:

- Claude.ai and ChatGPT `conversations.json` exports are auto-detected and
  normalized to one linear schema: `conversations: [{title, uuid, created_at,
  updated_at, messages: [{role, content}]}]`. Force `claude_json` or
  `chatgpt_json` to require that normalization and fail loudly if a file
  doesn't match.
- Both normalizers keep only conversation text. Claude `thinking`, `tool_use`
  and `tool_result` blocks are dropped. Uploaded files and attachments become
  placeholders (`[image]`, `[file: application/pdf]`, ...) with names and
  extracted contents left out. Messages with nothing in them, and
  conversations left with no messages, are dropped and counted in the output's
  `notes`.
- Other JSON files are copied through as structured pass-through inputs.
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

Use `--allow-list-file <PATH>` to keep reviewed false positives unchanged in
message content. The option can be repeated and merged with `--allow-list`.
Files may be newline-delimited text, a JSON string list, or a JSON object with
an `original_keys` or `allow_list` string list. `--name-allow-list-file` applies
the same behavior to file and directory names. Exact matching remains the
default; select `--allow-list-match regex` only for intentionally written
regular expressions.

### Presidio Tuning

Content anonymization uses settings tuned for chat transcripts
(`src/chatlog_processing_pipeline/presidio_config.py`):

- Default entities: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`,
  `URL`, `IP_ADDRESS`, `CREDIT_CARD`, `IBAN_CODE`, `US_SSN`, `US_PASSPORT`,
  `US_DRIVER_LICENSE`, `US_BANK_NUMBER`, `CRYPTO`, `MEDICAL_LICENSE`. Names
  and paths use the same list unless `--name-entities` is given.
- Off by default: `DATE_TIME` (fires on "last week"), `NRP`, `ORGANIZATION`
  (noisy on informal text; add it with `--organizations`).
- Default `--threshold` is 0.4.
- Built-in allow-list of AI and tool names (ChatGPT, Claude, Gemini, Copilot,
  ...). A span is kept if it is such a name, or such a name plus only
  lowercase filler words.
- Overlapping detections are resolved by keeping the longest span, then the
  highest score.

No street-address or postcode recognizers are included.

### Detection Reports

Every `--anon` run also writes CSVs listing what was removed, so you can spot
false positives to add to an allow-list. They go to a sibling folder named
`<anon-output>_detections_SENSITIVE/`:

- one `<file>.detections.csv` per anonymized file, with columns `scope`
  (`content` or `name_or_path`), `entity_type`, `original_text`, `count`,
  `avg_score`
- `_summary.csv` across all files, sorted by how many files each term appears
  in. Terms that are not PII (for example `Claude` flagged as `PERSON`) are the
  ones to put in `--allow-list-file`.

Files with no detections get no CSV, and `--dry-run` writes none. Terms matched
from `--metadata-csv` appear as entity type `BLOCKLIST`. These CSVs contain the
original PII and must not be published or committed.

For a private review of every Faker replacement, pass
`--mapping-audit-dir <DIR>`. The directory receives one sidecar per processed
file with the entity type, original span, replacement, and occurrence count.
These sidecars contain original PII and must not be published or committed.

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
