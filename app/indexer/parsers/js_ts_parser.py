"""
JavaScript / TypeScript parser.
Extracts functions with JSDoc descriptions and source code via brace-matching.
"""
import re
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

RE_IMPORT = re.compile(
    r"""(?:import\s+(?:.*?from\s+)?['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))""",
    re.MULTILINE,
)
RE_CLASS = re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
RE_ROUTE = re.compile(
    r"""(?:app|router|server|fastify)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.IGNORECASE | re.MULTILINE,
)

# Matches: function foo(  |  async function foo(  |  const foo = (  |  const foo = async (
RE_FUNC_START = re.compile(
    r"""(?:^|\n)([ \t]*)(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("""
    r"""|(?:^|\n)([ \t]*)(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(""",
    re.MULTILINE,
)

# JSDoc comment block immediately before a function
RE_JSDOC = re.compile(r'/\*\*(.*?)\*/', re.DOTALL)


def _extract_jsdoc_before(source: str, func_pos: int) -> str:
    """Find the closest JSDoc comment ending before func_pos."""
    best = ""
    for m in RE_JSDOC.finditer(source, 0, func_pos):
        raw = m.group(1)
        # strip leading * from each line
        lines = [l.strip().lstrip("*").strip() for l in raw.splitlines()]
        desc = " ".join(l for l in lines if l and not l.startswith("@"))
        if desc:
            best = desc
    return best[:400]


def _extract_body(lines: list[str], start_idx: int) -> tuple[int, str]:
    """Brace-match to find where the function body ends."""
    depth = 0
    started = False
    for i in range(start_idx, min(start_idx + 300, len(lines))):
        depth += lines[i].count("{") - lines[i].count("}")
        if not started and "{" in lines[i]:
            started = True
        if started and depth == 0:
            return i, "\n".join(lines[start_idx: i + 1])
    end = min(start_idx + 30, len(lines))
    return end, "\n".join(lines[start_idx:end])


def parse_js_ts(file_path: Path) -> dict:
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
        # imports / deps
        imports, deps = [], []
        for m in RE_IMPORT.finditer(source):
            mod = m.group(1) or m.group(2)
            if mod:
                imports.append(mod)
                pkg = mod.lstrip("@").split("/")[0] if mod.startswith("@") else mod.split("/")[0]
                if not mod.startswith("."):
                    deps.append(pkg)
        result["imports"] = sorted(set(imports))
        result["dependencies"] = sorted(set(deps))

        result["classes"] = list(dict.fromkeys(RE_CLASS.findall(source)))

        # functions with JSDoc + source
        for m in RE_FUNC_START.finditer(source):
            name = m.group(2) or m.group(4)
            if not name or name in ("if", "for", "while", "switch"):
                continue
            func_line = source[:m.start()].count("\n")
            jsdoc = _extract_jsdoc_before(source, m.start())
            description = jsdoc or f"Function '{name}' — no JSDoc found"
            end_line, src = _extract_body(lines, func_line)
            result["functions"].append({
                "name": name,
                "description": description,
                "start_line": func_line + 1,
                "end_line": end_line + 1,
                "source_code": src,
            })

        for m in RE_ROUTE.finditer(source):
            result["api_routes"].append(
                {"method": m.group(1).upper(), "path": m.group(2), "handler": ""}
            )

    except Exception as exc:
        result["parse_errors"].append(f"ParseError: {exc}")

    return result
