"""Secret redaction for logs, dry-run output, and errors."""

import re

REDACTED = "***REDACTED***"

# Fields that must be masked in any output
SENSITIVE_FIELDS = {
    "PrivateKey",
    "PresharedKey",
    "HeaderProtectionKey",
    "PrivateKeyBase64",
    "PresharedKeyBase64",
    "HeaderProtectionKeyBase64",
}


def redact_text(text: str) -> str:
    """Mask sensitive values in arbitrary text."""
    for field in SENSITIVE_FIELDS:
        # Match `field = value` or `field: value` patterns
        text = re.sub(
            rf"({re.escape(field)}\s*[=:]\s*)([^\s,;}}\]]+)",
            rf"\1{REDACTED}",
            text,
            flags=re.IGNORECASE,
        )
    return text


def redact_dict(data: dict) -> dict:
    """Return a copy of the dict with sensitive fields masked."""
    redacted = {}
    for key, value in data.items():
        if key in SENSITIVE_FIELDS or key.lower() in {
            f.lower() for f in SENSITIVE_FIELDS
        }:
            redacted[key] = REDACTED
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value)
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value
    return redacted
