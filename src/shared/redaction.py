"""Centralized redaction helpers for secret-safe logs and PR-facing output."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_REDACTED = "<redacted>"
_REDACTED_URL = "<redacted-url>"
_USERINFO_REDACTED = "<redacted-userinfo>"

_SECRET_KEYWORDS = (
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "credential",
    "password",
    "private_key",
    "not-a-real-key-material",
    "secret",
    "token",
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?P<key>[A-Za-z0-9_.-]*"
    r"(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)[A-Za-z0-9_.-]*)\b"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^'\"\s,;]+)"
    r"(?P=quote)"
)
_QUOTED_SECRET_FIELD_PATTERN = re.compile(
    r"(?i)(?P<keyquote>['\"])(?P<key>[A-Za-z0-9_.-]*"
    r"(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)[A-Za-z0-9_.-]*)"
    r"(?P=keyquote)"
    r"(?P<sep>\s*:\s*)"
    r"(?P<valuequote>['\"])(?P<value>.*?)(?P=valuequote)"
)
_BEARER_PATTERN = re.compile(r"(?i)\b(Bearer)\s+([^\s,;]+)")
_AUTHORIZATION_HEADER_PATTERN = re.compile(
    r"(?i)\b(Authorization\s*:\s*)(?:(?:Bearer|Basic|Token|ApiKey|Api-Key)\s+)?([^\s,;]+)"
)
_AUTHORIZATION_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?P<key>authorization)(?P<sep>\s*=\s*)"
    r"(?P<quote>['\"]?)(?:(?:Bearer|Basic|Token|ApiKey|Api-Key)\s+)?(?P<value>[^'\"\s,;]+)(?P=quote)"
)
_URL_PATTERN = re.compile(r"https?://[^\s,;)]+")
_URL_USERINFO_PASSWORD_PATTERN = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://(?:[^\s/@:]+)?:)(?P<password>[^\s/@]+)(?=@)"
)
_PEM_BLOCK_PATTERN = re.compile(
    r"-----BEGIN [^-]+PRIVATE KEY-----.*?-----END [^-]+PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class SecretRedactor:
    """Redact secret-shaped strings at output boundaries.

    The redactor is intentionally centralized so callsites do not accumulate
    one-off ``if 'token' in ...`` style checks. Callers can add runtime-known
    secret values while the generic patterns cover common credential shapes in
    provider errors, logs, and validation details.
    """

    explicit_secrets: tuple[str, ...] = ()
    redact_urls: bool = False

    def redact_text(self, value: str) -> str:
        redacted = value
        for secret in sorted((item for item in self.explicit_secrets if item), key=len, reverse=True):
            redacted = redacted.replace(secret, _REDACTED)
        redacted = _PEM_BLOCK_PATTERN.sub(_REDACTED, redacted)
        redacted = _AUTHORIZATION_HEADER_PATTERN.sub(lambda match: f"{match.group(1)}{_REDACTED}", redacted)
        redacted = _AUTHORIZATION_ASSIGNMENT_PATTERN.sub(_redacted_assignment, redacted)
        redacted = _BEARER_PATTERN.sub(lambda match: f"{match.group(1)} {_REDACTED}", redacted)
        redacted = _URL_USERINFO_PASSWORD_PATTERN.sub(_redacted_url_userinfo, redacted)
        redacted = _QUOTED_SECRET_FIELD_PATTERN.sub(_redacted_quoted_field, redacted)
        redacted = _SECRET_ASSIGNMENT_PATTERN.sub(_redacted_assignment, redacted)
        if self.redact_urls:
            redacted = _URL_PATTERN.sub(_REDACTED_URL, redacted)
        return redacted

    def redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {
                key: self.redact_secret_value(item) if _is_secret_key(str(key)) else self.redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, set):
            return {self.redact_value(item) for item in value}
        return value

    def redact_secret_value(self, value: object) -> object:
        if isinstance(value, str):
            return _REDACTED
        if isinstance(value, Mapping):
            return {key: self.redact_secret_value(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return tuple(self.redact_secret_value(item) for item in value)
        if isinstance(value, list):
            return [self.redact_secret_value(item) for item in value]
        if isinstance(value, set):
            return {self.redact_secret_value(item) for item in value}
        return _REDACTED


def redact_text(value: str, *, explicit_secrets: Sequence[str] = (), redact_urls: bool = False) -> str:
    """Redact secret-shaped text with optional runtime-known secret values."""

    return SecretRedactor(tuple(explicit_secrets), redact_urls=redact_urls).redact_text(value)


def redact_value(value: object, *, explicit_secrets: Sequence[str] = (), redact_urls: bool = False) -> object:
    """Redact nested JSON-serializable values at logging/output boundaries."""

    return SecretRedactor(tuple(explicit_secrets), redact_urls=redact_urls).redact_value(value)


def _redacted_assignment(match: re.Match[str]) -> str:
    key = match.group("key")
    sep = match.group("sep")
    quote = match.group("quote")
    return f"{key}{sep}{quote}{_REDACTED}{quote}"


def _redacted_quoted_field(match: re.Match[str]) -> str:
    keyquote = match.group("keyquote")
    key = match.group("key")
    sep = match.group("sep")
    valuequote = match.group("valuequote")
    return f"{keyquote}{key}{keyquote}{sep}{valuequote}{_REDACTED}{valuequote}"


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(".", "_")
    return any(
        keyword.replace("-", "_") in normalized or normalized.endswith(keyword.replace("-", "_") + "_key")
        for keyword in _SECRET_KEYWORDS
    )


def _redacted_url_userinfo(match: re.Match[str]) -> str:
    prefix = match.group("scheme")
    protocol = prefix.split("://", 1)[0] + "://"
    if prefix == f"{protocol}:":
        return f"{protocol}:{_REDACTED}"
    return f"{protocol}{_USERINFO_REDACTED}"
