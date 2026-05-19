"""
Monitor Router

POST /api/v1/monitor/start      Start reading + watching a JSON log file
POST /api/v1/monitor/stop       Stop the watcher
GET  /api/v1/monitor/status     Current watcher status + live counters
GET  /api/v1/monitor/events     All analyzed error events (newest first)
GET  /api/v1/monitor/events/{id} Single event detail
GET  /api/v1/monitor/debug      Internal diagnostics (for troubleshooting)
DELETE /api/v1/monitor/events   Clear all stored events
"""
from __future__ import annotations

import asyncio
import httpx
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.analyzer.two_step_analyzer import TwoStepAnalyzer
from app.jira.client import JiraClient
from app.models import AnalyzedEvent, ErrorEvent, MonitorStatus, StartMonitorRequest
from app.monitor.log_watcher import LogWatcher
from app.state import state
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# ── module-level references ────────────────────────────────────────────────────
_watcher: LogWatcher | None = None
_sem: asyncio.Semaphore | None = None          # lazy — created inside the event loop


def _get_sem() -> asyncio.Semaphore:
    """Return the analysis semaphore, creating it lazily inside the running loop."""
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(1)             # one LLM call at a time
    return _sem


# ── Analysis pipeline (runs as a background task) ─────────────────────────────

async def _analyse_and_store(event) -> None:
    """
    Full pipeline for one error event:
      Step 1 → LLM identifies suspected functions
      Step 2 → LLM analyses source code + generates fix
      JIRA   → ticket created (failures are non-blocking)

    This always runs as a fire-and-forget asyncio.Task so the log watcher
    is never blocked waiting for LLM responses.
    The semaphore ensures only ONE LLM call runs at a time (no rate-limit errors).
    """
    async with _get_sem():
        analyzed: AnalyzedEvent | None = None

        # ── LLM analysis ──────────────────────────────────────────────────────
        try:
            if state.index is None:
                # No codebase index — still run full LLM analysis on the error itself
                logger.info(
                    "No index loaded — running error-only LLM analysis for %s", event.id[:8]
                )
                analyzer = TwoStepAnalyzer(index=None)
                analyzed = await analyzer.analyze_without_index(event)
            else:
                analyzer = TwoStepAnalyzer(state.index)
                analyzed = await analyzer.analyze(event)

            logger.info(
                "Analysis done — severity=%s confidence=%.0f%% suspected=%s",
                analyzed.step2.severity,
                analyzed.step2.confidence_score * 100,
                analyzed.step1.suspected_functions,
            )
        except Exception as exc:
            logger.error("LLM analysis failed for %s: %s", event.id[:8], exc)
            from app.models import Step1Result, Step2Result
            analyzed = AnalyzedEvent(
                id=event.id,
                error=event,
                step1=Step1Result(
                    suspected_functions=[],
                    reasoning=f"Analysis failed: {exc}",
                    confidence=0.0,
                ),
                step2=Step2Result(
                    root_cause=f"LLM call failed: {exc}",
                    technical_explanation=(
                        "The LLM call to Groq failed. Common causes:\n"
                        "1. GROQ_API_KEY is missing or wrong in .env / .env.example\n"
                        "2. Network / rate-limit error\n"
                        f"Error detail: {exc}"
                    ),
                    debugging_steps=[
                        "Check GROQ_API_KEY in your .env or .env.example file.",
                        "Verify you can reach https://api.groq.com",
                        "Check uvicorn console for full traceback.",
                    ],
                    possible_fixes=["Set a valid GROQ_API_KEY and restart the server."],
                    severity="medium",
                    confidence_score=0.0,
                ),
                analyzed_at=event.detected_at,
            )

        # ── JIRA ticket (completely optional — never blocks) ──────────────────
        if analyzed is not None:
            try:
                jira = JiraClient()
                ticket = await jira.create_ticket(analyzed)
                analyzed = analyzed.model_copy(update={"jira": ticket})
                logger.info("JIRA ticket %s created", ticket.ticket_id)
            except Exception as exc:
                logger.warning("JIRA skipped (non-blocking): %s", exc)

            state.add_event(analyzed)


async def _on_error(event) -> None:
    """
    Called synchronously by LogWatcher for each error line.
    Immediately increments counters, then fires analysis as a background task
    so the watcher loop is NEVER blocked.
    """
    state.errors_detected += 1
    state.errors_queued += 1
    state.last_error_msg = str(
        event.log_entry.get("message") or event.log_entry.get("msg", "")
    )[:120]
    logger.info("Error #%d queued for analysis: %s", state.errors_detected, state.last_error_msg)

    # Fire and forget — analysis runs in background, watcher keeps reading
    asyncio.create_task(_analyse_and_store(event))


async def _health_check_loop(
    url: str,
    interval_sec: int = 3,
    threshold: int = 3,
    window_sec: int = 10,
) -> None:
    """Polling health checks that create an event only after repeated failures."""
    state.health_url = url
    state.health_failures = 0
    state.last_health_error = ""
    consecutive_failures = 0

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        while state.is_monitoring and state.monitor_type == "health":
            ok = False
            status_description = ""
            try:
                response = await client.get(url)
                status_description = f"HTTP {response.status_code}"
                ok = 200 <= response.status_code < 400
            except Exception as exc:
                status_description = str(exc)

            if not ok:
                consecutive_failures += 1
                state.health_failures = consecutive_failures
                state.last_health_error = (
                    f"Health check failed: {status_description}"
                )[:120]
                logger.warning(
                    "Health check failure #%d/%d: %s",
                    consecutive_failures,
                    threshold,
                    state.last_health_error,
                )

                if consecutive_failures >= threshold:
                    consecutive_failures = 0
                    state.health_failures = 0
                    event = ErrorEvent(
                        id=str(uuid.uuid4()),
                        raw_line=json.dumps({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "health_check_url": url,
                            "failure_reason": status_description,
                        }),
                        log_entry={
                            "message": (
                                "Health check failed repeatedly: site did not respond."
                            ),
                            "url": url,
                            "failure_reason": status_description,
                            "severity": "ERROR",
                        },
                        detected_at=datetime.now(timezone.utc).isoformat(),
                    )
                    logger.error(
                        "Health threshold reached — creating event for %s",
                        url,
                    )
                    asyncio.create_task(_analyse_and_store(event))
            else:
                if consecutive_failures:
                    logger.info("Health check recovered: %s", url)
                consecutive_failures = 0
                state.health_failures = 0
                state.last_health_error = ""

            await asyncio.sleep(interval_sec)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/monitor/start", response_model=MonitorStatus, tags=["Monitor"])
async def start_monitor(body: StartMonitorRequest):
    """
    Start reading a JSON log file from line 1, then tail for new lines.
    Index is optional — raw events with error info are stored even without it.
    """
    global _watcher, _sem

    if state.is_monitoring:
        raise HTTPException(409, "Monitor is already running. Stop it first.")

    _sem = asyncio.Semaphore(1)
    state.errors_detected = 0
    state.errors_queued = 0
    state.errors_analyzed = 0
    state.last_error_msg = ""
    state.health_failures = 0
    state.last_health_error = ""

    if body.monitor_type == "health":
        if not body.health_url:
            raise HTTPException(400, "health_url is required for health monitor")

        _watcher = None
        state.monitor_type = "health"
        state.health_url = body.health_url
        state.log_path = None
        state.is_monitoring = True

        async def _run():
            try:
                await _health_check_loop(
                    body.health_url,
                    interval_sec=body.check_interval_sec,
                    threshold=body.failure_threshold,
                    window_sec=body.failure_window_sec,
                )
            except asyncio.CancelledError:
                logger.info("Health watcher task cancelled.")
            except Exception as exc:
                logger.error("Health watcher crashed: %s", exc, exc_info=True)
            finally:
                state.is_monitoring = False

        state.watcher_task = asyncio.create_task(_run())
        logger.info("Health monitor started on %s", body.health_url)

        return MonitorStatus(
            running=True,
            log_path=None,
            errors_detected=state.health_failures,
            monitor_type=state.monitor_type,
            health_url=state.health_url,
            failures_detected=state.health_failures,
            last_error=state.last_health_error,
        )

    if not body.log_path:
        raise HTTPException(400, "log_path is required for log monitor")

    log_path = Path(body.log_path)
    if not log_path.exists():
        raise HTTPException(404, f"Log file not found: {body.log_path}")

    # Reset semaphore for a clean start
    _watcher = LogWatcher(log_path, _on_error, replay_delay_sec=0.1)
    state.monitor_type = "log"
    state.log_path = str(log_path.resolve())
    state.health_url = None
    state.is_monitoring = True

    async def _run():
        try:
            await _watcher.start()
        except asyncio.CancelledError:
            logger.info("Watcher task cancelled.")
        except FileNotFoundError as exc:
            logger.error("Watcher: %s", exc)
        except Exception as exc:
            logger.error("Watcher crashed: %s", exc, exc_info=True)
        finally:
            state.is_monitoring = False

    state.watcher_task = asyncio.create_task(_run())
    logger.info("Monitor started on %s", log_path)

    return MonitorStatus(
        running=True,
        log_path=state.log_path,
        errors_detected=state.errors_detected,
        monitor_type=state.monitor_type,
        health_url=None,
        failures_detected=0,
        last_error="",
    )


@router.post("/monitor/stop", response_model=MonitorStatus, tags=["Monitor"])
async def stop_monitor():
    """Stop the running monitor task."""
    global _watcher

    if _watcher:
        _watcher.stop()
        _watcher = None

    if state.watcher_task and not state.watcher_task.done():
        state.watcher_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(state.watcher_task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    state.is_monitoring = False
    path = state.log_path
    state.log_path = None
    state.health_url = None
    state.monitor_type = "log"
    state.health_failures = 0
    state.last_health_error = ""

    return MonitorStatus(
        running=False,
        log_path=path,
        errors_detected=0,
        monitor_type=state.monitor_type,
        health_url=None,
        failures_detected=0,
        last_error="",
    )


@router.get("/monitor/status", response_model=MonitorStatus, tags=["Monitor"])
async def monitor_status():
    if state.watcher_task and state.watcher_task.done():
        state.is_monitoring = False
    return MonitorStatus(
        running=state.is_monitoring,
        log_path=state.log_path,
        errors_detected=(state.health_failures if state.monitor_type == "health" else state.errors_detected),
        monitor_type=state.monitor_type,
        health_url=state.health_url,
        failures_detected=state.health_failures,
        last_error=(state.last_health_error or state.last_error_msg),
    )


@router.get("/monitor/debug", tags=["Monitor"])
async def monitor_debug():
    """Live diagnostics — shows exactly what the pipeline is doing."""
    from app.config import settings
    key = settings.groq_api_key
    key_preview = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "(not set)"
    return {
        "monitor_running": state.is_monitoring,
        "monitor_type": state.monitor_type,
        "log_path": state.log_path,
        "health_url": state.health_url,
        "index_loaded": state.index is not None,
        "index_functions": state.index.summary.total_functions if state.index else 0,
        "groq_key_preview": key_preview,
        "groq_key_looks_valid": key.startswith("gsk_") and len(key) > 20,
        "errors_detected_in_log": state.errors_detected,
        "errors_queued_for_analysis": state.errors_queued,
        "errors_fully_analyzed": state.errors_analyzed,
        "health_failures": state.health_failures,
        "last_error_message": state.last_health_error or state.last_error_msg,
        "watcher_task_alive": (
            state.watcher_task is not None and not state.watcher_task.done()
        ),
    }


@router.get("/monitor/jira-test", tags=["Monitor"])
async def jira_test():
    """
    Test JIRA credentials and show available issue types + priorities.
    Use this to diagnose why tickets aren't being created.
    """
    from app.jira.client import JiraClient
    from app.config import settings
    try:
        client = JiraClient()
        result = await client.test_connection()
        result["jira_base_url"]    = settings.jira_base_url
        result["jira_project_key"] = settings.jira_project_key
        result["jira_email"]       = settings.jira_email
        result["api_token_set"]    = bool(
            settings.jira_api_token and settings.jira_api_token != "YOUR_JIRA_API_TOKEN"
        )
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/monitor/events", response_model=list[AnalyzedEvent], tags=["Monitor"])
async def get_events(limit: int = 50):
    """Return the most recent analyzed error events (newest first)."""
    return list(reversed(state.events[-limit:]))


@router.get("/monitor/events/{event_id}", response_model=AnalyzedEvent, tags=["Monitor"])
async def get_event(event_id: str):
    for ev in state.events:
        if ev.id == event_id:
            return ev
    raise HTTPException(404, f"Event {event_id} not found.")


@router.delete("/monitor/events", tags=["Monitor"])
async def clear_events():
    state.events.clear()
    state.errors_detected = 0
    state.errors_queued = 0
    state.errors_analyzed = 0
    return {"message": "All events cleared."}
