import re


SECRET_PATTERNS = [
    re.compile(
        r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+"
    ),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
]


def redact_sensitive(value):
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(r"\1[REDACTED]", value)
    return value
