# Chatlog Processing Pipeline

A standalone package for parsing, anonymizing, and reviewing exported chat transcripts.

## Install

This repo is set up for `uv`.

```bash
make init
```

That will:
- use `uv` to create `.venv`
- sync runtime and dev dependencies
- install the local sibling repo `../llm-delusions-annotations` as an editable dependency via `tool.uv.sources`

The reviewer UI assets are checked into `src/chatlog_processing_pipeline/assets/`.

## Commands

- `process_chats --parse --input <INPUT_DIR> --output-dir <PARSED_OUT>` parses raw transcript exports into normalized JSON.
- `process_chats --anon --input <PARSED_DIR> --anon-output <ANON_OUT>` anonymizes parsed JSON or raw text exports.
- `process_chats_plan --input <INPUT_DIR> --generate-plan <PLAN.csv>` generates a plan CSV for tricky files.
- `process_chats_plan --input <INPUT_DIR> --plan <PLAN.csv> --output-dir <PARSED_OUT>` runs a plan-based parse.
- `format_chats_html <PARSED_DIR> <OUT_DIR>` renders parsed JSON as reviewer-friendly HTML.
- `format_chats_html <PARSED_DIR> <OUT_FILE> --mode aggregate` renders one aggregate HTML or text export.
- `find_duplicate_contents --root <DIR_A> --root <DIR_B>` scans parsed JSON directories for duplicated content overlap.

## Notes

- `process_chats --anon` accepts `--metadata-csv <PATH>` to seed the anonymization blocklist from contact or identifier columns.
- ChatGPT HTML and JSON exports, PDFs, DOCX, RTF, ODT, TXT, and ZIP containers are supported.
- The reviewer HTML formatter depends on `llm-delusions-annotations` for chat loading helpers.

## Development

```bash
make pyfmt
make pylint
```
