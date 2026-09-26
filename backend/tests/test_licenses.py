"""License guardrails.

Only MIT / Apache-2.0 / BSD code may be vendored or ported into this
repository. Two upstreams in the integration map are explicitly *concepts
only*: CozyClay (AGPL-3.0) and Compositor (MIT, but Swift/macOS — nothing
portable). This test fails the build on any AGPL header, any import of a
CozyClay package, and on any Swift source file.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".txt", ".yml", ".yaml", ".toml"}
# `python-embed` and `Wan2GP` are local build/runtime checkouts, not vendored source:
# they are gitignored and carry their own third-party licences (cv2, ultralytics and
# friends legitimately ship AGPL-adjacent notices). This guard is about code *vendored
# into this repository*, so build artefacts must not be scanned.
SKIP_DIRS = {
    "node_modules",
    ".venv",
    ".git",
    "dist",
    "dist-electron",
    "dist-ui",
    "release",
    "ui-preview",
    "__pycache__",
    ".cache",
    "test-results",
    "playwright-report",
    "python-embed",
    "Wan2GP",
}

AGPL_PATTERNS = (
    re.compile(r"GNU\s+AFFERO\s+GENERAL\s+PUBLIC\s+LICENSE", re.IGNORECASE),
    re.compile(r"\bAGPL(?:-|\s)?(?:3|v3)", re.IGNORECASE),
    re.compile(r"SPDX-License-Identifier:\s*AGPL", re.IGNORECASE),
)
COZYCLAY_PATTERNS = (
    re.compile(r"^\s*(?:from|import)\s+cozyclay\b", re.MULTILINE),
    re.compile(r"""(?:from|import|require\()\s*['"]@earendil-works/""", re.MULTILINE),
    re.compile(r"""(?:from|import|require\()\s*['"]cozyclay""", re.MULTILINE),
)
# Files that *talk about* the rule (this test, the docs that record "concepts only").
ALLOWLIST = {
    "backend/tests/test_licenses.py",
    "docs/INTEGRATED_UPSTREAMS.md",
    "NOTICES.md",
    "session-notes.md",
}


def _scan_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in SCANNED_SUFFIXES:
            files.append(path)
    return files


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_no_agpl_licensed_code_is_vendored() -> None:
    offenders: list[str] = []
    for path in _scan_files():
        rel = _rel(path)
        if rel in ALLOWLIST or rel.startswith("docs/adr/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(p.search(text) for p in AGPL_PATTERNS):
            offenders.append(rel)
    assert offenders == [], f"AGPL license text found (CozyClay is concepts-only): {offenders}"


def test_no_cozyclay_imports() -> None:
    offenders: list[str] = []
    for path in _scan_files():
        if path.suffix not in {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs"}:
            continue
        rel = _rel(path)
        if rel in ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(p.search(text) for p in COZYCLAY_PATTERNS):
            offenders.append(rel)
    assert offenders == [], f"CozyClay (AGPL-3.0) must never be imported: {offenders}"


def test_no_swift_sources() -> None:
    swift = [_rel(p) for p in REPO_ROOT.rglob("*.swift") if not any(part in SKIP_DIRS for part in p.parts)]
    assert swift == [], f"Compositor is Swift/macOS and concepts-only; no Swift sources belong here: {swift}"


def test_vendored_upstreams_are_recorded() -> None:
    """Every vendored/adapted upstream directory must be listed in docs/INTEGRATED_UPSTREAMS.md."""
    doc = (REPO_ROOT / "docs" / "INTEGRATED_UPSTREAMS.md").read_text(encoding="utf-8")
    vendored_markers = {
        "frontend/views/film/composer/blockout": "wassermanproductions/blockout",
        "backend/services/vision/clip_data": "pharmapsychotic/clip-interrogator",
        "backend/services/vision/florence2_model": "kijai/ComfyUI-Florence2",
    }
    for rel, upstream in vendored_markers.items():
        if (REPO_ROOT / rel).exists():
            assert upstream in doc, f"{rel} exists but {upstream} is not recorded in docs/INTEGRATED_UPSTREAMS.md"
