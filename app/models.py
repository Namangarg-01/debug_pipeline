from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Indexer models ─────────────────────────────────────────────────────────────

class FunctionInfo(BaseModel):
    """A single function/method extracted from source code."""
    name: str
    description: str = Field(description="Docstring or inferred description")
    start_line: int
    end_line: int
    source_code: str = Field(description="Full source code of the function")


class FileIndex(BaseModel):
    """Index entry for one source file."""
    file: str
    path: str
    language: str
    size_bytes: int = 0
    functions: list[FunctionInfo] = []
    classes: list[str] = []
    imports: list[str] = []
    api_routes: list[dict[str, str]] = []
    dependencies: list[str] = []
    parse_errors: list[str] = []


class IndexSummary(BaseModel):
    total_files: int
    total_functions: int
    total_classes: int
    total_routes: int
    languages_detected: dict[str, int]
    all_dependencies: list[str]


class BackendIndex(BaseModel):
    """Full codebase index — saved to disk after one-time setup."""
    root_path: str
    created_at: str
    summary: IndexSummary
    files: list[FileIndex]


# ── Monitor / event models ─────────────────────────────────────────────────────

class ErrorEvent(BaseModel):
    """A single error entry detected in the JSON log file."""
    id: str
    raw_line: str
    log_entry: dict[str, Any]        # the full parsed JSON line
    detected_at: str


# ── Analyzer models ────────────────────────────────────────────────────────────

class Step1Result(BaseModel):
    """LLM Step 1 output — which functions are suspected."""
    suspected_functions: list[str]
    reasoning: str
    confidence: float = 0.5


class Step2Result(BaseModel):
    """LLM Step 2 output — full root-cause analysis."""
    root_cause: str
    technical_explanation: str
    debugging_steps: list[str]
    possible_fixes: list[str]
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    confidence_score: float = 0.75
    affected_components: list[str] = []


# ── JIRA model ─────────────────────────────────────────────────────────────────

class JiraTicketInfo(BaseModel):
    ticket_id: str
    ticket_url: str
    created_at: str


# ── Combined analyzed event ────────────────────────────────────────────────────

class AnalyzedEvent(BaseModel):
    """Everything produced for one error: event + both LLM steps + JIRA ticket."""
    id: str
    error: ErrorEvent
    step1: Step1Result
    step2: Step2Result
    jira: Optional[JiraTicketInfo] = None
    analyzed_at: str


# ── API request/response helpers ───────────────────────────────────────────────

class StartMonitorRequest(BaseModel):
    log_path: Optional[str] = Field(
        None,
        description="Absolute path to the JSON log file to watch. Required when monitor_type is 'log'.",
    )
    monitor_type: Literal["log", "health"] = Field(
        "log",
        description="Which monitor mode to start: log file watcher or periodic health check.",
    )
    health_url: Optional[str] = Field(
        None,
        description="URL to poll for health checks. Required when monitor_type is 'health'.",
    )
    check_interval_sec: int = Field(
        3,
        description="Seconds between health check requests.",
    )
    failure_threshold: int = Field(
        3,
        description="Number of failed health checks required before ticket creation.",
    )
    failure_window_sec: int = Field(
        10,
        description="Sliding window in seconds for counting failed checks.",
    )


class MonitorStatus(BaseModel):
    running: bool
    log_path: Optional[str]
    errors_detected: int
    monitor_type: Literal["log", "health"] = "log"
    health_url: Optional[str] = None
    failures_detected: int = 0
    last_error: str = ""


class IndexStatus(BaseModel):
    indexed: bool
    root_path: Optional[str]
    total_files: int
    total_functions: int
    created_at: Optional[str]
