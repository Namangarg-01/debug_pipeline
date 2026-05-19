"""
Debug Pipeline — FastAPI Application

Full pipeline:
  1. Index your backend code once  →  /api/v1/index/upload
  2. Start monitoring a JSON log   →  /api/v1/monitor/start
  3. Errors auto-trigger two-step LLM analysis + JIRA ticket creation
"""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.indexer.service import IndexingService
from app.routers import index_router, monitor_router
from app.state import state
from app.utils.logger import get_logger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = get_logger("debug_pipeline")

INDEX_SAVE_PATH = Path("backend_index.json")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-load saved index on startup
    if INDEX_SAVE_PATH.exists() and state.index is None:
        try:
            state.index = IndexingService.load(INDEX_SAVE_PATH)
            logger.info(
                "Loaded saved index — %d files, %d functions",
                state.index.summary.total_files,
                state.index.summary.total_functions,
            )
        except Exception as exc:
            logger.warning("Could not load saved index: %s", exc)
    yield
    if state.watcher_task:
        state.watcher_task.cancel()
    logger.info("Debug Pipeline shutting down.")


app = FastAPI(
    title="Debug Pipeline",
    description=(
        "Automated backend error detection and root-cause analysis.\n\n"
        "**Workflow**:\n"
        "1. `POST /api/v1/index/upload` — index your backend codebase (one-time)\n"
        "2. `POST /api/v1/monitor/start` — start watching a live JSON log file\n"
        "3. Errors auto-trigger two-step LLM analysis and JIRA ticket creation"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(index_router.router, prefix="/api/v1")
app.include_router(monitor_router.router, prefix="/api/v1")


@app.middleware("http")
async def timing(request: Request, call_next):
    t = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - t) * 1000, 1)
    response.headers["X-Process-Time-Ms"] = str(ms)
    return response


@app.exception_handler(Exception)
async def global_exc(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"error": str(exc), "path": str(request.url.path)})


@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "model": settings.groq_model,
        "index_loaded": state.index is not None,
        "monitoring": state.is_monitoring,
        "events_count": len(state.events),
    }
