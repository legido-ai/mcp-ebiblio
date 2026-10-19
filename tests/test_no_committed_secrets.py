"""Secret audit: no credential material may live in the repository.

The constitution requires an automated secret scan, and a check that every
required environment variable is documented in ``.env.example``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".pytest_cache"}

# Patterns that must never appear in committed files.
PATTERNS = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "aws key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github token": re.compile(r"\b(ghp|ghs|gho|github_pat)_[A-Za-z0-9_]{20,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "oci ocid": re.compile(r"\bocid1\.[a-z]+\.[a-z0-9\-]*\.[a-z0-9]{20,}"),
    "assigned password": re.compile(
        r"(?i)\b(password|passwd|secret|api_key|apikey|token)\b\s*[:=]\s*[\"'](?![A-Z_]{3,}[\"'])"
        r"(?!<|\$\{|%s|\{\{)[^\"'\s]{8,}[\"']"
    ),
    "basic auth url": re.compile(r"https?://[^/\s:@]+:[^/\s:@]+@"),
}

ALLOWED_HITS = {
    # Test doubles and documentation placeholders are not real credentials.
    "tests/test_client.py": {"assigned password"},
    "tests/test_drm.py": {"assigned password"},
    "tests/test_server.py": {"assigned password"},
    ".env.example": {"assigned password", "oci ocid"},
    "README.md": {"assigned password", "basic auth url", "oci ocid"},
    "docs/specs/001-ebiblio-mcp/spec.md": {"assigned password"},
    "docs/specs/001-ebiblio-mcp/plan.md": {"assigned password"},
}

REQUIRED_ENV = {
    "EBIBLIO_USERNAME",
    "EBIBLIO_PASSWORD",
    "EBIBLIO_BASE_URL",
    "EBIBLIO_DATA_DIR",
}


def iter_files() -> list[Path]:
    files = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".epub", ".woff", ".woff2"}:
            continue
        files.append(path)
    return files


def test_no_secret_material_committed() -> None:
    findings: list[str] = []
    for path in iter_files():
        rel = path.relative_to(REPO).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file
            continue
        for label, pattern in PATTERNS.items():
            if label in ALLOWED_HITS.get(rel, set()):
                continue
            for match in pattern.finditer(text):
                findings.append(f"{rel}: {label}: {match.group(0)[:40]}")
    assert not findings, "possible credentials found:\n" + "\n".join(findings)


def test_env_file_is_ignored_and_not_present() -> None:
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert not (REPO / ".env").exists()


def test_env_example_documents_every_required_variable() -> None:
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    documented = {
        line.split("=", 1)[0].strip()
        for line in example.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    missing = REQUIRED_ENV - documented
    assert not missing, f"undocumented environment variables: {sorted(missing)}"


def test_dockerfile_does_not_copy_env_or_data() -> None:
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    for forbidden in ("COPY .env ", "COPY .env\n", "ADD .env"):
        assert forbidden not in dockerfile
