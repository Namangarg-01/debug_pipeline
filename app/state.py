"""
Global in-memory application state.
Shared between routers, the log watcher, and the analyzer pipeline.
"""
from __future__ import annotations
import asyncio
from typing import Optional
from app.models import AnalyzedEvent, BackendIndex


class AppState:
    def __init__(self):
        self.index: Optional[BackendIndex] = None
        self.watcher_task: Optional[asyncio.Task] = None
        self.log_path: Optional[str] = None
        self.health_url: Optional[str] = None
        self.is_monitoring: bool = False
        self.monitor_type: str = "log"
        self.events: list[AnalyzedEvent] = []
        # Counters for UI progress display
        self.errors_detected: int = 0      # raw errors found in log
        self.errors_queued: int = 0        # waiting for LLM analysis
        self.errors_analyzed: int = 0      # fully analyzed + stored
        self.health_failures: int = 0      # failed health checks in current window
        self.last_error_msg: str = ""      # last detected log error message
        self.last_health_error: str = ""   # last failed health check message

    def add_event(self, event: AnalyzedEvent) -> None:
        self.events.append(event)
        self.errors_analyzed += 1
        if self.errors_queued > 0:
            self.errors_queued -= 1
        if len(self.events) > 500:
            self.events = self.events[-500:]

    def clear_index(self) -> None:
        self.index = None


state = AppState()
