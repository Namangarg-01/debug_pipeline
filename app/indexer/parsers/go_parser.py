"""
Go parser — extracts functions with comment descriptions and source code.
"""
import re
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

RE_IMPORT_BLOCK = re.compile(r'import\s*\((.*?)\)', re.DOTALL)
RE_IMPORT_SINGLE = re.compile(r'^import\s+"([^"]+)"', re.MULTILINE)
RE_IMPORT_LINE = re.compile(r'(?:_\s+|(\w+)\s+)?"([^"]+)"')
RE_STRUCT = re.compile(r"^type\s+(\w+)\s+struct\s*\{", re.MULTILINE)
RE_INTERFACE = re.compile(r"^type\s+(\w+)\s+interface\s*\{", re.MULTILINE)
RE_FUNC = re.compile(r"^func\s+(?:\(\s*\w*\s*\*?\w+\s*\)\s*)?(\w+)\s*\(", re.MULTILINE)
RE_ROUTE_GIN = re.compile(
    r"""(?:r|router|engine|group)\s*\.\s*(GET|POST|PUT|PATCH|DELETE)\s*\(\s*"([^"]+)"\s*,""",
    re.IGNORECASE,
)
# Go doc comment: lines starting with // immediately before func
RE_GO_COMMENT = re.compile(r"((?:[ \t]*//[^\n]*\n)+)[ \t]*func\s")


def _comment_before(source: str, func_pos: int) -> str:
    """Extract the Go doc comment block immediately preceding the func keyword."""
    snippet = source[max(0, func_pos - 800): func_pos]
    lines = snippet.splitlines()
    comment_lines = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            comment_lines.insert(0, stripped.lstrip("/").strip())
        else:
            break
    return " ".join(comment_lines)[:400]


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


def parse_go(file_path: Path) -> dict:
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
        imports, deps = [], []
        for block in RE_IMPORT_BLOCK.finditer(source):
            for lm in RE_IMPORT_LINE.finditer(block.group(1)):
                pkg = lm.group(2)
                imports.append(pkg)
                deps.append(pkg.split("/")[-1] if "/" in pkg else pkg)
        for m in RE_IMPORT_SINGLE.finditer(source):
            imports.append(m.group(1))
            deps.append(m.group(1).split("/")[-1])
        result["imports"] = sorted(set(imports))
        result["dependencies"] = sorted(set(deps))

        result["classes"] = list(dict.fromkeys(
            RE_STRUCT.findall(source) + RE_INTERFACE.findall(source)
        ))

        for m in RE_FUNC.finditer(source):
            name = m.group(1)
            line_idx = source[: m.start()].count("\n")
            comment = _comment_before(source, m.start())
            description = comment or f"Function '{name}' — no Go doc comment found"
            end_line, src = _extract_body(lines, line_idx)
            result["functions"].append({
                "name": name,
                "description": description,
                "start_line": line_idx + 1,
                "end_line": end_line + 1,
                "source_code": src,
            })

        for m in RE_ROUTE_GIN.finditer(source):
            result["api_routes"].append(
                {"method": m.group(1).upper(), "path": m.group(2), "handler": ""}
            )

    except Exception as exc:
        result["parse_errors"].append(f"ParseError: {exc}")

    return result
