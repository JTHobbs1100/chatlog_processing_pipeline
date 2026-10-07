"""Tests for the per-file anonymization detection CSVs."""

import csv
import json

from chatlog_processing_pipeline.redactor import run_redaction


def _write_parsed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": {}, "messages": [{"role": "user", "content": text}]}),
        encoding="utf-8",
    )


def _run(in_dir, out_dir, jobs, **overrides):
    params = dict(
        in_dir=in_dir,
        out_dir=out_dir,
        jobs=jobs,
        metadata_csv=None,
        lang="en",
        entities=["PERSON", "EMAIL_ADDRESS"],
        score_threshold=0.35,
        operator="replace",
        replace_with="<REDACTED>",
        mask_char="*",
        mask_chars_to_mask=0,
        mask_from_end=False,
        allow_list=None,
        allow_list_match="exact",
        name_entities=None,
        name_threshold=0.35,
        name_operator="replace",
        name_replace_with="<REDACTED>",
        name_mask_char="_",
        name_mask_chars_to_mask=0,
        name_mask_from_end=False,
        name_allow_list=None,
        name_allow_list_match="exact",
        chunk_size=100000,
        chunk_break_window=500,
        spacy_max_length=None,
        include_all=False,
        skip_nontext=False,
        overwrite=True,
        names_only=False,
        content_only=True,
        generic_json_strings=False,
        dry_run=False,
        no_progress=True,
        verbose=False,
    )
    params.update(overrides)
    return run_redaction(**params)


def test_detection_csvs_list_removed_text(tmp_path):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    _write_parsed(
        in_dir / "a" / "conv1.json",
        "Hi, I am Maria Gonzalez, write me at maria.g@example.com. Maria Gonzalez!",
    )
    _write_parsed(in_dir / "b" / "conv2.json", "Reach maria.g@example.com today.")

    _run(in_dir, out_dir, jobs=1)

    report_dir = tmp_path / "out_detections_SENSITIVE"
    per_file = report_dir / "a" / "conv1.json.detections.csv"
    rows = list(csv.DictReader(per_file.open(encoding="utf-8")))
    by_text = {(r["entity_type"], r["original_text"]): r for r in rows}
    assert ("EMAIL_ADDRESS", "maria.g@example.com") in by_text
    assert any(r["entity_type"] == "PERSON" for r in rows)
    assert set(rows[0]) == {"scope", "entity_type", "original_text", "count", "avg_score"}

    summary = list(csv.DictReader((report_dir / "_summary.csv").open(encoding="utf-8")))
    email = next(r for r in summary if r["original_text"] == "maria.g@example.com")
    assert email["files"] == "2"
    assert email["total_count"] == "2"
    # Original PII must not leak into the anonymized output.
    assert "maria.g@example.com" not in (out_dir / "a" / "conv1.json").read_text()
