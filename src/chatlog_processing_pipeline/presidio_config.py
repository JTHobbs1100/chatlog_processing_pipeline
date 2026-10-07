"""Presidio tuning for chat transcripts: entity set, allow-list, overlaps.

Ported from the survey de-identification tool. Street-address and postcode
recognizers are intentionally not included.
"""

from __future__ import annotations

import string
from typing import Iterable, List

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

# Entities redacted by default. Comment a line out to stop redacting it.
# Deliberately off by default:
#   DATE_TIME     fires on "last week", "every morning"
#   NRP           nationality / religious / political group
#   ORGANIZATION  noisy on informal text; enable with --organizations
#   MAC_ADDRESS, US_ITIN, UK_NHS
DEFAULT_ENTITIES: List[str] = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
    "URL",
    "IP_ADDRESS",
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_SSN",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
    "US_BANK_NUMBER",
    "CRYPTO",
    "MEDICAL_LICENSE",
]

# Presidio scores spaCy NER hits at 0.85 and a bare US phone number at 0.40.
DEFAULT_SCORE_THRESHOLD = 0.4

# Terms Presidio mistakes for PII but that carry the meaning of the chats.
DEFAULT_ALLOWLIST = {
    "ai", "genai", "llm", "llms", "chatbot", "chatbots", "bot",
    "chatgpt", "chat gpt", "gpt", "gpt-3", "gpt-4", "gpt-4o", "gpt-5", "openai",
    "claude", "anthropic", "sonnet", "opus", "haiku",
    "gemini", "bard", "google", "google ai",
    "copilot", "github copilot", "microsoft", "bing", "microsoft copilot",
    "llama", "meta ai", "grok", "xai", "perplexity", "deepseek", "mistral",
    "siri", "alexa", "cortana", "apple", "amazon",
    "midjourney", "dall-e", "dalle", "stable diffusion", "notebooklm",
    "google docs", "google drive", "gmail", "outlook", "excel", "word",
    "slack", "zoom", "teams", "canvas", "reddit", "youtube",
}  # fmt: skip

_PUNCT = string.punctuation + string.whitespace


def normalize_term(text: str) -> str:
    """Lowercase ``text`` and strip surrounding punctuation and whitespace."""
    return text.strip(_PUNCT).lower()


def is_allowlisted(span: str) -> bool:
    """True for AI/tool names, or such a name plus only lowercase filler."""
    if normalize_term(span) in DEFAULT_ALLOWLIST:
        return True
    tokens = span.split()
    kept = [t for t in tokens if normalize_term(t) not in DEFAULT_ALLOWLIST]
    return len(kept) < len(tokens) and not any(t[:1].isupper() for t in kept)


def resolve_overlaps(results: Iterable) -> list:
    """Keep the longest span among overlaps, breaking ties by score."""
    kept: list = []
    for res in sorted(results, key=lambda r: (r.start - r.end, -r.score)):
        if not any(res.start < k.end and k.start < res.end for k in kept):
            kept.append(res)
    return sorted(kept, key=lambda r: r.start)


def enable_organization_detection(analyzer: AnalyzerEngine) -> None:
    """Let spaCy ORG hits through; only used when ORGANIZATION is requested.

    ORGANIZATION ships in ``labels_to_ignore``; drop it in place so the rest of
    the default label mapping (notably FAC -> LOCATION) is preserved.
    """
    try:
        config = analyzer.nlp_engine.ner_model_configuration
    except AttributeError:
        return
    config.labels_to_ignore = [
        label for label in config.labels_to_ignore if label != "ORGANIZATION"
    ]
    name = "OrgSpacyRecognizer"
    if not any(r.name == name for r in analyzer.registry.recognizers):
        analyzer.registry.add_recognizer(
            SpacyRecognizer(supported_entities=["ORGANIZATION"], name=name)
        )
