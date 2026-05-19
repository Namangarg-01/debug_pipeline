"""
Python parser — uses ast to extract functions with docstrings and source code.
"""
import ast
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

ROUTE_DECORATORS = {
    "get", "post", "put", "patch", "delete", "head", "options",
    "route", "add_url_rule", "api_view", "action",
}


def _decorator_method(node) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr.lower()
    if isinstance(node, ast.Call):
        return _decorator_method(node.func)
    return None


def _decorator_path(node) -> str | None:
    if isinstance(node, ast.Call) and node.args:
        a = node.args[0]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    return None


def parse_python(file_path: Path) -> dict:
    result: dict = {
        "functions": [], "classes": [], "imports": [],
        "api_routes": [], "dependencies": [], "parse_errors": [],
    }

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        result["parse_errors"].append(f"SyntaxError: {exc}")
        return result
    except Exception as exc:
        result["parse_errors"].append(f"ParseError: {exc}")
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name)
                result["dependencies"].append(alias.name.split(".")[0])

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result["imports"].append(node.module)
                result["dependencies"].append(node.module.split(".")[0])

        elif isinstance(node, ast.ClassDef):
            result["classes"].append(node.name)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node) or ""
            start = node.lineno - 1
            end = getattr(node, "end_lineno", start + 20)
            source_code = "\n".join(lines[start:end])

            description = docstring[:400] if docstring else f"Function '{node.name}' — no docstring found"

            result["functions"].append({
                "name": node.name,
                "description": description,
                "start_line": node.lineno,
                "end_line": end,
                "source_code": source_code,
            })

            for dec in node.decorator_list:
                method = _decorator_method(dec)
                if method in ROUTE_DECORATORS:
                    path = _decorator_path(dec) or "unknown"
                    result["api_routes"].append(
                        {"method": method.upper(), "path": path, "handler": node.name}
                    )

    result["imports"] = sorted(set(result["imports"]))
    result["dependencies"] = sorted(set(result["dependencies"]))
    return result
