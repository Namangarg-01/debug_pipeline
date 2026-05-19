"""
Index Router — one-time setup endpoints.

POST /api/v1/index/upload   Upload ZIP → build + save index
POST /api/v1/index/path     Index a local directory
GET  /api/v1/index/status   Current index status
DELETE /api/v1/index        Clear current index
"""
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.indexer.service import IndexingService
from app.models import BackendIndex, IndexStatus
from app.state import state
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

INDEX_SAVE_PATH = Path("backend_index.json")


@router.post("/index/upload", response_model=BackendIndex, tags=["Index"])
async def index_from_upload(
    file: UploadFile = File(..., description="ZIP archive of the backend codebase"),
):
    """Upload a ZIP of your backend. Extracts function names, descriptions, and source code."""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(400, "Only .zip archives are accepted.")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "upload.zip"
        extract_path = Path(tmp) / "src"
        extract_path.mkdir()

        try:
            zip_path.write_bytes(await file.read())
        except Exception as exc:
            raise HTTPException(400, f"Failed to read upload: {exc}")

        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_path)
        except zipfile.BadZipFile:
            raise HTTPException(400, "Invalid ZIP archive.")

        index = await IndexingService(extract_path).run()

    state.index = index
    IndexingService.save(index, INDEX_SAVE_PATH)
    logger.info(
        "Index built — %d files, %d functions",
        index.summary.total_files, index.summary.total_functions,
    )
    return index


@router.post("/index/path", response_model=BackendIndex, tags=["Index"])
async def index_from_path(
    directory: str = Query(..., description="Absolute path to the source directory"),
):
    """Index a backend directory already present on this server."""
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        raise HTTPException(404, f"Directory not found: {directory}")

    index = await IndexingService(root).run()
    state.index = index
    IndexingService.save(index, INDEX_SAVE_PATH)
    return index


@router.get("/index/status", response_model=IndexStatus, tags=["Index"])
async def index_status():
    """Returns whether an index is currently loaded."""
    if state.index:
        return IndexStatus(
            indexed=True,
            root_path=state.index.root_path,
            total_files=state.index.summary.total_files,
            total_functions=state.index.summary.total_functions,
            created_at=state.index.created_at,
        )
    # Try loading from disk
    if INDEX_SAVE_PATH.exists():
        try:
            state.index = IndexingService.load(INDEX_SAVE_PATH)
            return IndexStatus(
                indexed=True,
                root_path=state.index.root_path,
                total_files=state.index.summary.total_files,
                total_functions=state.index.summary.total_functions,
                created_at=state.index.created_at,
            )
        except Exception:
            pass
    return IndexStatus(indexed=False, root_path=None, total_files=0, total_functions=0, created_at=None)


@router.delete("/index", tags=["Index"])
async def clear_index():
    """Remove the current index from memory (does not delete the saved file)."""
    state.clear_index()
    return {"message": "Index cleared from memory."}
