"""
IndexingService — scans the codebase and builds a BackendIndex
with function names, descriptions, and source code.
"""
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.models import BackendIndex, FileIndex, FunctionInfo, IndexSummary
from app.utils.language_detector import iter_source_files
from app.utils.logger import get_logger
from app.indexer.parsers.python_parser import parse_python
from app.indexer.parsers.js_ts_parser import parse_js_ts
from app.indexer.parsers.java_parser import parse_java
from app.indexer.parsers.go_parser import parse_go

logger = get_logger(__name__)

_PARSERS = {
    "python": parse_python,
    "javascript": parse_js_ts,
    "typescript": parse_js_ts,
    "java": parse_java,
    "go": parse_go,
}

MAX_CONCURRENT = 20


def _parse_sync(file_path: Path, language: str, rel_path: str) -> FileIndex:
    parser = _PARSERS.get(language)
    if parser is None:
        return FileIndex(
            file=file_path.name, path=rel_path, language=language,
            size_bytes=file_path.stat().st_size,
            parse_errors=[f"No parser for language: {language}"],
        )
    try:
        raw = parser(file_path)
        functions = [FunctionInfo(**f) for f in raw.get("functions", [])]
        return FileIndex(
            file=file_path.name,
            path=rel_path,
            language=language,
            size_bytes=file_path.stat().st_size,
            functions=functions,
            classes=raw.get("classes", []),
            imports=raw.get("imports", []),
            api_routes=raw.get("api_routes", []),
            dependencies=raw.get("dependencies", []),
            parse_errors=raw.get("parse_errors", []),
        )
    except Exception as exc:
        logger.warning("Error parsing %s: %s", file_path, exc)
        return FileIndex(
            file=file_path.name, path=rel_path, language=language,
            size_bytes=file_path.stat().st_size,
            parse_errors=[f"UnexpectedError: {exc}"],
        )


class IndexingService:
    def __init__(self, root: Path):
        self.root = root

    async def run(self) -> BackendIndex:
        source_files = list(iter_source_files(self.root))
        logger.info("Discovered %d source files under %s", len(source_files), self.root)

        sem = asyncio.Semaphore(MAX_CONCURRENT)
        loop = asyncio.get_running_loop()

        async def bounded(fp: Path, lang: str) -> FileIndex:
            rel = "/" + str(fp.relative_to(self.root)).replace("\\", "/")
            async with sem:
                return await loop.run_in_executor(None, _parse_sync, fp, lang, rel)

        files = [f for f in await asyncio.gather(*[bounded(fp, l) for fp, l in source_files]) if f]
        summary = self._build_summary(files)

        return BackendIndex(
            root_path=str(self.root),
            created_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            files=files,
        )

    @staticmethod
    def _build_summary(files: list[FileIndex]) -> IndexSummary:
        lang_counter: Counter = Counter(f.language for f in files)
        all_deps: set[str] = set()
        tf = tc = tr = 0
        for f in files:
            tf += len(f.functions)
            tc += len(f.classes)
            tr += len(f.api_routes)
            all_deps.update(f.dependencies)
        return IndexSummary(
            total_files=len(files),
            total_functions=tf,
            total_classes=tc,
            total_routes=tr,
            languages_detected=dict(lang_counter),
            all_dependencies=sorted(all_deps),
        )

    @staticmethod
    def save(index: BackendIndex, path: Path) -> None:
        path.write_text(index.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Index saved to %s", path)

    @staticmethod
    def load(path: Path) -> BackendIndex:
        return BackendIndex.model_validate_json(path.read_text(encoding="utf-8"))
