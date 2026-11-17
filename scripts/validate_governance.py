#!/usr/bin/env python3
"""Fail-closed governance validator for AI Infrastructure Standard v1.2."""

import re
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

TODAY = date.today()
REQUIRED_IGNORE_PATTERNS = {
    ".env*",
    ".git/",
    ".ssh/",
    ".aws/",
    ".kube/",
    ".npmrc",
    ".pypirc",
    "*.pem",
    "*.key",
    "id_*",
}


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def check_required_files() -> None:
    required = [
        "AGENTS.md",
        "kilo.jsonc",
        ".env.example",
        ".github/CODEOWNERS",
        ".kilo/agent-ignore.txt",
        ".kilo/network-allowlist.txt",
        ".kilo/approved_models.yaml",
        ".kilo/MCP_REGISTRY.md",
        ".kilo/EXCEPTIONS.md",
    ]
    for rel in required:
        if not Path(rel).is_file():
            fail(f"Missing mandatory governance file: {rel}")


def check_agent_ignore() -> None:
    lines = {
        line.strip()
        for line in Path(".kilo/agent-ignore.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = REQUIRED_IGNORE_PATTERNS - lines
    if missing:
        fail(f".kilo/agent-ignore.txt missing required patterns: {sorted(missing)}")


def check_forbidden_patterns() -> None:
    targets = ["AGENTS.md", "kilo.jsonc", ".kilo/approved_models.yaml", ".kilo/MCP_REGISTRY.md"]
    abs_path_re = re.compile(r"(/Users/|/home/[a-zA-Z0-9_-]+/|[A-Za-z]:\\)")
    latest_re = re.compile(r"(@latest|:latest|[\"']latest[\"'])")
    for path_str in targets:
        content = Path(path_str).read_text(encoding="utf-8")
        if abs_path_re.search(content):
            fail(f"Absolute path detected in {path_str}")
        if latest_re.search(content):
            fail(f"Forbidden 'latest' tag detected in {path_str}")


def check_dates_in_markdown_table(file_path: str, date_col_idx: int, label: str) -> None:
    lines = Path(file_path).read_text(encoding="utf-8").splitlines()
    data_rows = [
        line for line in lines if line.strip().startswith("|") and not set(line.strip()) <= {"|", "-", ":", " "}
    ]
    if len(data_rows) <= 1:
        return
    for row in data_rows[1:]:
        cols = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cols) <= date_col_idx:
            fail(f"Malformed table row in {file_path}: {row}")
        raw_date = cols[date_col_idx]
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            fail(f"Invalid YYYY-MM-DD date '{raw_date}' in {file_path} ({label})")
        if parsed < TODAY:
            fail(f"Expired {label} date '{raw_date}' in {file_path} (today is {TODAY.isoformat()})")


def check_approved_models() -> None:
    if yaml is None:
        fail("PyYAML is required to validate .kilo/approved_models.yaml (pip install pyyaml)")
    data = yaml.safe_load(Path(".kilo/approved_models.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("models"):
        fail(".kilo/approved_models.yaml must define a non-empty 'models' list")
    for entry in data["models"]:
        for key in ("provider", "model_id", "dpa_status", "zdr_status", "max_data_classification", "review_by_date"):
            if key not in entry:
                fail(f"Missing field '{key}' in approved_models.yaml entry: {entry}")
        if entry["dpa_status"] != "signed" or entry["zdr_status"] != "enabled":
            fail(f"Model {entry['model_id']} must have dpa_status=signed and zdr_status=enabled")
        review_date = date.fromisoformat(str(entry["review_by_date"]))
        if review_date < TODAY:
            fail(f"Model {entry['model_id']} review_by_date expired: {review_date}")


def main() -> None:
    check_required_files()
    check_agent_ignore()
    check_forbidden_patterns()
    check_approved_models()
    check_dates_in_markdown_table(".kilo/MCP_REGISTRY.md", 5, "MCP Next Review Due")
    check_dates_in_markdown_table(".kilo/EXCEPTIONS.md", 5, "Exception Expires On")
    print("[OK] AI Infrastructure Governance validation passed.")


if __name__ == "__main__":
    main()
