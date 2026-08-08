"""Tests for private anonymization mapping audit output."""

import json
import stat

from chatlog_processing_pipeline.redaction_utils import FakerState
from chatlog_processing_pipeline.redactor import _write_mapping_audit


def test_faker_state_counts_exact_mapping_occurrences():
    """Count repeated replacements without affecting identifier consumption."""
    state = FakerState("en_US")
    replacement = state.replacement("PERSON", "Example Name")
    assert state.replacement("PERSON", "Example Name") == replacement

    state.consume_new_identifiers()
    assert state.consume_mappings() == [
        {
            "entity_type": "PERSON",
            "original": "Example Name",
            "replacement": replacement,
            "count": 2,
        }
    ]
    assert state.consume_mappings() == []


def test_write_mapping_audit_creates_private_sidecar(tmp_path):
    """Write exact mappings to a private JSON sidecar."""
    state = FakerState("en_US")
    replacement = state.replacement("PERSON", "Example Name")
    path = tmp_path / "private" / "example.mappings.json"

    _write_mapping_audit(
        path,
        source_path=tmp_path / "input.json",
        destination_path=tmp_path / "output.json",
        content_faker_state=state,
        name_faker_state=None,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mappings"] == [
        {
            "scope": "content",
            "entity_type": "PERSON",
            "original": "Example Name",
            "replacement": replacement,
            "count": 1,
        }
    ]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
