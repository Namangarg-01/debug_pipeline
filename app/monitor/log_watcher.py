"""
LogWatcher — reads a JSON log file from the beginning, fires a callback for
every ERROR/CRITICAL/FATAL line found, then continues watching for new lines.

Supported JSON log formats:
  {"timestamp": "...", "level": "ERROR",    "message": "..."}
  {"time": "...",      "severity": "FATAL", "msg": "..."}
  {"@timestamp": "..","log.level": "ERROR", "message": "..."}
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import ErrorEvent
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL"}


def _is_error(entry: dict) -> bool:
    level = (
        entry.get("level")
        or entry.get("severity")
        or entry.get("log.level")
        or entry.get("lvl")
        or ""
    )
    return str(level).upper() in _ERROR_LEVELS


class LogWatcher:
    """
    Reads the ENTIRE log file from line 1, processes all existing error lines,
    then stays alive watching for new lines appended in real-time.

    replay_delay_sec — seconds to wait between consecutive error callbacks
                       during the initial replay (prevents Groq rate-limits).
    """

    def __init__(self, log_path: Path, on_error, replay_delay_sec: float = 0.05):
        self.log_path = log_path
        self._on_error = on_error
        self._replay_delay = replay_delay_sec   # tiny gap so event loop can breathe
        self._running = False
        self.lines_read = 0
        self.errors_fired = 0

    async def start(self) -> None:
        self._running = True
        logger.info("LogWatcher started — reading from beginning of %s", self.log_path)

        if not self.log_path.exists():
            raise FileNotFoundError(f"Log file not found: {self.log_path}")

        with open(self.log_path, "r", encoding="utf-8", errors="replace") as fh:
            # ── Replay existing lines ──────────────────────────────────────────
            logger.info("Replaying existing log entries...")
            while self._running:
                line = fh.readline()
                if not line:
                    break                          # reached current EOF — switch to tail mode
                self.lines_read += 1
                fired = await self._process(line.strip(), replay=True)
                if fired:
                    # small pause between replayed errors so Groq isn't hammered
                    await asyncio.sleep(self._replay_delay)

            logger.info(
                "Replay complete — %d lines read, %d errors found. Now tailing for new lines.",
                self.lines_read, self.errors_fired,
            )

            # ── Tail mode — watch for new appended lines ───────────────────────
            while self._running:
                line = fh.readline()
                if line:
                    self.lines_read += 1
                    await self._process(line.strip(), replay=False)
                else:
                    await asyncio.sleep(0.5)

    def stop(self) -> None:
        self._running = False
        logger.info("LogWatcher stopped — %d lines read, %d errors fired", self.lines_read, self.errors_fired)

    async def _process(self, line: str, replay: bool) -> bool:
        """Returns True if the line was an error that triggered the callback."""
        if not line:
            return False
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return False                           # skip non-JSON lines silently

        if not _is_error(entry):
            return False

        event = ErrorEvent(
            id=str(uuid.uuid4()),
            raw_line=line,
            log_entry=entry,
            detected_at=datetime.now(timezone.utc).isoformat(),
        )
        self.errors_fired += 1
        mode = "replay" if replay else "live"
        logger.info(
            "[%s] Error #%d detected — %s",
            mode, self.errors_fired,
            str(entry.get("message") or entry.get("msg", ""))[:120],
        )

        try:
            await self._on_error(event)
        except Exception as exc:
            # NEVER let a callback failure kill the watcher
            logger.error("on_error callback raised (event ignored): %s", exc)

        return True
