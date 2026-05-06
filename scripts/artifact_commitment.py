"""
Insight Forge — artifact-commitment closure signal (MVP, no git).

Implements signal 4 of the ARA closure-signal set, which was a TODO in
pipeline.py until now. The idea: a heuristic about "use X" or "tests live
in Y/" has earned promotion if the project has actually committed to it
— i.e. files or config now depend on it.

This MVP uses **path/file existence checks against the project root**.
No git history walk, no AST parsing, no subprocess calls. Just:

  - Did the user mention a path like `tests/` or `scripts/`? Does it exist?
  - Did the user mention a well-known tool like `pnpm` or `ruff`? Is the
    canonical marker file present (`pnpm-lock.yaml`, `[tool.ruff]` in
    `pyproject.toml`)?

Conservative by design — false positives are worse than false negatives.
A path mentioned but absent doesn't fire (the rule isn't yet committed
to the project). A tool mentioned without its canonical marker doesn't
fire either. The signal is emitted only when there's hard evidence on
disk.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# Well-known tool → list of file paths that, if present, prove the project
# is committed to that tool. The lists are intentionally short and only
# cover canonical markers — fuzzy matches inflate false positives.
_TOOL_MARKERS: dict[str, list[str]] = {
    "pnpm": ["pnpm-lock.yaml"],
    "yarn": ["yarn.lock"],
    "npm": ["package-lock.json"],
    "poetry": ["poetry.lock"],
    "uv": ["uv.lock"],
    "cargo": ["Cargo.lock"],
    "ruff": [".ruff.toml", "ruff.toml"],
    "black": [".black.toml"],
    "mypy": ["mypy.ini", ".mypy.ini"],
    "pytest": ["pytest.ini", ".pytest.ini", "conftest.py"],
    "docker": ["Dockerfile", "docker-compose.yml", "compose.yaml"],
    "terraform": [".terraform"],
    "kubectl": ["kustomization.yaml", "kustomization.yml"],
    "vite": ["vite.config.js", "vite.config.ts"],
    "webpack": ["webpack.config.js"],
    "eslint": [".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yaml"],
    "prettier": [".prettierrc", ".prettierrc.json", ".prettierrc.js"],
}

# Tools whose presence is signalled by a config file mentioning them
# (e.g. `[tool.ruff]` in pyproject.toml). Each entry is
# (tool_name, [(filename, regex_pattern), ...]).
_CONFIG_REFERENCES: dict[str, list[tuple[str, str]]] = {
    "ruff": [("pyproject.toml", r"\[tool\.ruff")],
    "black": [("pyproject.toml", r"\[tool\.black")],
    "mypy": [("pyproject.toml", r"\[tool\.mypy")],
    "pytest": [("pyproject.toml", r"\[tool\.pytest")],
    "pnpm": [("package.json", r'"packageManager"\s*:\s*"pnpm')],
    "yarn": [("package.json", r'"packageManager"\s*:\s*"yarn')],
}

# Path-shaped tokens to detect in observation text. Accepts:
#   - directory paths with trailing slash:   tests/, src/components/
#   - nested file paths:                      src/components/Header.tsx
#   - leading-dot paths:                      .github/workflows/main.yml
#   - bare filenames with known extensions:   pyproject.toml, package.json
_PATH_RE = re.compile(
    r"(?<![\w/])"                                 # boundary (no word/slash before)
    r"("
    r"\.?[A-Za-z][\w\-]*"                          # first segment, optional leading dot
    r"(?:/[\w\-]+)*"                               # zero or more middle dir segments
    r"(?:/|\.[A-Za-z][\w]{0,5})"                    # trailing slash OR file extension
    r")"
    r"(?![\w/])"                                   # boundary after
)


def _extract_paths(text: str) -> list[str]:
    """Pull path-shaped tokens out of the rule text."""
    if not text:
        return []
    out: list[str] = []
    for m in _PATH_RE.finditer(text):
        path = m.group(1)
        if not path:
            continue
        clean = path.rstrip("/")
        if clean and clean not in out:
            out.append(clean)
    return out


def _extract_tools(text: str) -> list[str]:
    """Pull well-known tool names out of the rule text (case-insensitive)."""
    if not text:
        return []
    text_lower = text.lower()
    out: list[str] = []
    for tool in _TOOL_MARKERS:
        # Word-boundary match so `pnpm` doesn't match `pnpmpkg` or similar.
        if re.search(rf"\b{re.escape(tool)}\b", text_lower):
            out.append(tool)
    return out


def detect_artifact_commitment(observation_text: str,
                                  project_root: Optional[Path]) -> Optional[str]:
    """Return a human-readable description of the matched artifact, or None.

    Two passes:
      1. Path mentioned in the rule + file/dir exists at project_root
      2. Tool mentioned in the rule + canonical marker file exists OR
         config file references the tool

    Returns the FIRST hit. Conservative — null when there's no evidence,
    null when project_root is missing/None, null on any I/O error.
    """
    if not observation_text or project_root is None:
        return None
    try:
        if not project_root.exists() or not project_root.is_dir():
            return None
    except OSError:
        return None

    # --- Pass 1: path-based ---------------------------------------------
    for path_str in _extract_paths(observation_text):
        # Skip path tokens that are mostly noise (e.g. things like "I/O"
        # would be filtered by the regex but be defensive).
        if len(path_str) < 2:
            continue
        candidate = project_root / path_str
        try:
            if candidate.exists():
                return f"path '{path_str}' exists in project"
        except OSError:
            continue

    # --- Pass 2: tool-based ---------------------------------------------
    for tool in _extract_tools(observation_text):
        # 2a. Marker files
        for marker in _TOOL_MARKERS.get(tool, []):
            try:
                if (project_root / marker).exists():
                    return f"tool '{tool}' confirmed by '{marker}'"
            except OSError:
                continue

        # 2b. Config-file references (e.g. [tool.ruff] in pyproject.toml)
        for config_file, pattern in _CONFIG_REFERENCES.get(tool, []):
            cf = project_root / config_file
            try:
                if not cf.exists():
                    continue
                content = cf.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if re.search(pattern, content):
                return f"tool '{tool}' referenced in '{config_file}'"

    return None
