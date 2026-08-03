from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "data",
    "dist",
    "tmp",
}
EXCLUDED_PREFIXES = ("build", "release")
EXCLUDED_SUFFIXES = {".bin", ".dll", ".exe", ".ico", ".pdf", ".png", ".pyc", ".zip"}
SENSITIVE_NAMES = {
    ".env",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "settings.json",
}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "provider token": re.compile(r"\b(?:sk-|ghp_|github_pat_|AIza)[A-Za-z0-9_.-]{16,}\b"),
    "bearer credential": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    "literal secret assignment": re.compile(
        r"(?i)(?:api[_-]?key|secret|access[_-]?token|password)\s*[\"']?\s*[:=]\s*[\"'][^\"']{12,}[\"']"
    ),
    "private local path": re.compile(r"(?i)\b[A-Z]:\\(?:Users|MyApp|AUniversityStudy)\\"),
}


def excluded(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_DIRS or part.startswith(EXCLUDED_PREFIXES) for part in relative.parts[:-1]):
        return True
    return path.suffix.lower() in EXCLUDED_SUFFIXES


def scan(root: Path) -> list[tuple[str, Path, int]]:
    findings: list[tuple[str, Path, int]] = []
    scanner_path = Path(__file__).resolve()
    for path in root.rglob("*"):
        if not path.is_file() or excluded(path, root):
            continue
        if path.name.lower() in SENSITIVE_NAMES and path.name != ".env.example":
            findings.append(("sensitive filename", path, 0))
        if path.resolve() == scanner_path:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for category, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((category, path, line_number))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail safely when source files appear to contain secrets.")
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    findings = scan(root)
    if findings:
        print("Potentially sensitive content found (values intentionally hidden):")
        for category, path, line in findings:
            location = f":{line}" if line else ""
            print(f"- {path.relative_to(root)}{location} [{category}]")
        return 1
    print("Secret scan passed: no suspicious credentials or private local paths found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
