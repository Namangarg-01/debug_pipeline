from pathlib import Path

EXTENSION_MAP: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".java": "java", ".go": "go",
}

IGNORE_DIRS = {
    "node_modules", "__pycache__", ".git", "dist", "build", ".next",
    "target", "vendor", ".venv", "venv", "env", ".idea", ".vscode",
    "coverage", ".pytest_cache",
}

IGNORE_EXTENSIONS = {".min.js", ".bundle.js", ".map", ".lock"}


def detect_language(path: Path) -> str | None:
    name = path.name.lower()
    for ext in IGNORE_EXTENSIONS:
        if name.endswith(ext):
            return None
    return EXTENSION_MAP.get(path.suffix.lower())


def iter_source_files(root: Path):
    for item in root.rglob("*"):
        if any(p in IGNORE_DIRS or p.startswith(".") for p in item.parts):
            continue
        if item.is_file():
            lang = detect_language(item)
            if lang:
                yield item, lang
