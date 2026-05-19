"""
Java parser — extracts methods with Javadoc descriptions and source code.
"""
import re
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

RE_IMPORT = re.compile(r"^import\s+([\w.]+)\s*;", re.MULTILINE)
RE_CLASS = re.compile(
    r"^\s*(?:public|protected|private)?\s*(?:abstract\s+|final\s+)?(?:class|interface|enum|record)\s+(\w+)",
    re.MULTILINE,
)
RE_METHOD = re.compile(
    r"^\s*(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)+"
    r"[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{",
    re.MULTILINE,
)
RE_ROUTE_METHOD = re.compile(
    r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)"
    r"(?:\s*\(\s*[\"']?([^\"',)]*)[\"']?\s*\))?",
    re.IGNORECASE,
)
RE_JAVADOC = re.compile(r'/\*\*(.*?)\*/', re.DOTALL)

HTTP_MAP = {
    "getmapping": "GET", "postmapping": "POST", "putmapping": "PUT",
    "deletemapping": "DELETE", "patchmapping": "PATCH",
}


def _javadoc_before(source: str, pos: int) -> str:
    best = ""
    for m in RE_JAVADOC.finditer(source, 0, pos):
        lines = [l.strip().lstrip("*").strip() for l in m.group(1).splitlines()]
        desc = " ".join(l for l in lines if l and not l.startswith("@"))
        if desc:
            best = desc
    return best[:400]


def _extract_body(lines: list[str], start_idx: int) -> tuple[int, str]:
    depth = 0
    started = False
    for i in range(start_idx, min(start_idx + 200, len(lines))):
        depth += lines[i].count("{") - lines[i].count("}")
        if not started and "{" in lines[i]:
            started = True
        if started and depth == 0:
            return i, "\n".join(lines[start_idx: i + 1])
    end = min(start_idx + 30, len(lines))
    return end, "\n".join(lines[start_idx:end])


def parse_java(file_path: Path) -> dict:
    result: dict = {
        "functions": [], "classes": [], "imports": [],
        "api_routes": [], "dependencies": [], "parse_errors": [],
    }

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        result["parse_errors"].append(f"ReadError: {exc}")
        return result

    lines = source.splitlines()

    try:
        imports = [m.group(1) for m in RE_IMPORT.finditer(source)]
        result["imports"] = sorted(set(imports))
        result["dependencies"] = sorted({i.split(".")[0] for i in imports if "." in i})
        result["classes"] = list(dict.fromkeys(RE_CLASS.findall(source)))

        class_names = set(result["classes"])
        for m in RE_METHOD.finditer(source):
            name = m.group(1)
            if name in class_names:
                continue
            line_idx = source[: m.start()].count("\n")
            javadoc = _javadoc_before(source, m.start())
            description = javadoc or f"Method '{name}' — no Javadoc found"
            end_line, src = _extract_body(lines, line_idx)
            result["functions"].append({
                "name": name,
                "description": description,
                "start_line": line_idx + 1,
                "end_line": end_line + 1,
                "source_code": src,
            })

        for m in RE_ROUTE_METHOD.finditer(source):
            verb = HTTP_MAP.get(m.group(1).lower(), m.group(1).upper())
            path = (m.group(2) or "").strip() or "/"
            result["api_routes"].append({"method": verb, "path": path, "handler": ""})

    except Exception as exc:
        result["parse_errors"].append(f"ParseError: {exc}")

    return result
