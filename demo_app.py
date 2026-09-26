"""
Debug Pipeline — Streamlit demo UI
===================================
A self-contained demo that calls the indexing + two-step LLM analysis
pipeline directly in-process (no separate FastAPI server needed), so this
one file is enough to demo or deploy on Streamlit Community Cloud.

The full app (real-time log tailing, JIRA ticket creation, live monitoring)
still lives in app/main.py + frontend/streamlit_app.py and needs a running
FastAPI backend — see README.md. This demo covers the core "index a
codebase, analyze one error" flow synchronously, which is what a reviewer
clicking a live link actually wants to see.

Run locally:
    streamlit run demo_app.py

Deploy on Streamlit Cloud:
    Set GROQ_API_KEY as an app secret (Settings -> Secrets).
"""
import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# Streamlit Cloud secrets -> environment, so app.config picks them up.
# Only touch st.secrets if a secrets.toml actually exists — accessing it
# otherwise makes Streamlit render its own "No secrets found" error banner
# directly into the app UI, which no try/except here can suppress (it's not
# a normal Python exception). Running locally with a .env file — the
# expected case — never needs this at all.
_secrets_paths = [
    Path.home() / ".streamlit" / "secrets.toml",
    Path(__file__).parent / ".streamlit" / "secrets.toml",
]
if any(p.exists() for p in _secrets_paths):
    for _key in ("GROQ_API_KEY", "SMTP_USERNAME", "SMTP_APP_PASSWORD", "NOTIFY_EMAIL"):
        try:
            if _key in st.secrets and not os.getenv(_key):
                os.environ[_key] = st.secrets[_key]
        except Exception:
            pass

from app.indexer.service import IndexingService
from app.analyzer.two_step_analyzer import TwoStepAnalyzer
from app.config import settings
from app.models import ErrorEvent
from app.utils.language_detector import EXTENSION_MAP
from app.jira.client import JiraClient
from app.notifier.email_notifier import notify_ticket_created, is_configured as email_configured

st.set_page_config(page_title="Debug Pipeline — AI Root-Cause Analysis", layout="wide")

REPO_ROOT = Path(__file__).parent
SAMPLE_LOG = REPO_ROOT / "sample_logs" / "app.log"
# Small backend whose code produces the sample errors — indexed at start-up, never executed
SAMPLE_BACKEND = REPO_ROOT / "sample_backend"
CUSTOM = "Custom error (edit the JSON below)"


@st.cache_resource(show_spinner="Loading the pre-built codebase index...")
def _sample_index():
    """Index the bundled sample backend once per server process (takes milliseconds)."""
    return asyncio.run(IndexingService(SAMPLE_BACKEND).run())


def _load_sample_errors() -> list[dict]:
    if not SAMPLE_LOG.exists():
        return []
    entries = []
    for line in SAMPLE_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(entry.get("level", "")).upper() in ("ERROR", "CRITICAL", "FATAL"):
            entries.append(entry)
    return entries


# ── Session state ────────────────────────────────────────────────────────────
st.session_state.setdefault("result", None)      # AnalyzedEvent from the last run
st.session_state.setdefault("run_meta", None)    # {"seconds": float, "mode": "Index" | "Error-only"}
st.session_state.setdefault("jira_ticket", None)  # (ticket_id, ticket_url) once created for the current result

try:
    sample_index = _sample_index()
except Exception:
    sample_index = None

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    use_index = st.toggle("Use the pre-built codebase index", value=sample_index is not None,
                          disabled=sample_index is None,
                          help="Off = the analyzer works from the error message and traceback alone.")
    st.caption("Index of `sample_backend/` (auth, user, database and cache code), the code the sample errors come from.")

    st.divider()
    st.subheader("JIRA (optional)")
    st.caption(
        "Enter your own JIRA Cloud credentials to try real ticket creation. "
        "Used only for this session — never stored or logged."
    )
    jira_base_url = st.text_input("JIRA base URL", placeholder="https://yourorg.atlassian.net")
    jira_email = st.text_input("JIRA account email", placeholder="you@yourorg.com")
    jira_api_token = st.text_input("JIRA API token", type="password", help="Create one at id.atlassian.com/manage-profile/security/api-tokens")
    jira_project_key = st.text_input("JIRA project key", placeholder="PROJ")
    jira_configured = all([jira_base_url, jira_email, jira_api_token, jira_project_key])

    if not settings.groq_api_key or settings.groq_api_key == "YOUR_GROQ_API_KEY":
        st.divider()
        st.error("GROQ_API_KEY is not set. Add it to a .env file locally, or to Streamlit secrets when deployed.")

index = sample_index if use_index else None
samples = _load_sample_errors()
summary = sample_index.summary if sample_index else None

# ── Header ───────────────────────────────────────────────────────────────────
st.title("Debug Pipeline — AI Root-Cause Analysis")
st.caption(f"Two-step LLM analysis of production errors against an indexed codebase · "
           f"Python, FastAPI, Groq ({settings.groq_model}), Streamlit")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Indexed files", summary.total_files if summary else "—")
k2.metric("Functions indexed", summary.total_functions if summary else "—")
k3.metric("Sample errors", len(samples))
k4.metric("Codebase index", "On" if index else "Off")
k5.metric("Languages supported", len(set(EXTENSION_MAP.values())))

index_size = f"{summary.total_files} files, {summary.total_functions} functions" if summary else "a handful of files"
with st.expander("About this demo", expanded=True):
    st.markdown(
        f"- **Already indexed:** the app ships with a small sample backend (auth, user, database and cache code; "
        f"{index_size}) that is indexed automatically, so the analyzer can pinpoint the suspect functions and "
        "read their real source code. No upload needed.\n"
        "- **Common test cases:** the sample errors are typical production failures from that backend: a `None` "
        "user object, an exhausted database connection pool, and Redis going down. You can also paste your own "
        "JSON log line.\n"
        "- **Live AI results:** nothing is pre-written or cached. Each time you click **Analyze**, the error (and, "
        f"with the index on, the suspect functions' source code) is sent to an LLM (Groq · `{settings.groq_model}`), "
        "and you see exactly what it returns, so the wording can differ between runs."
    )

st.divider()

# ── Input + how it works ─────────────────────────────────────────────────────
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Error to analyze")
    labels = [f"{e.get('service', '?')} — {str(e.get('message', ''))[:70]}" for e in samples]
    choice = st.selectbox("Sample error (from sample_logs/app.log)", labels + [CUSTOM])
    if choice != CUSTOM:
        default_json = json.dumps(samples[labels.index(choice)], indent=2)
    else:
        default_json = json.dumps({
            "message": "TypeError: cannot unpack non-iterable NoneType object",
            "service": "checkout-api",
            "level": "ERROR",
        }, indent=2)
    raw_json = st.text_area("Error log entry (JSON)", value=default_json, height=220)
    analyze_clicked = st.button("Analyze error", type="primary")

with right:
    st.subheader("How it works")
    with st.container(border=True):
        st.markdown(
            "1. **Identify:** the LLM reads the error and the function index, and picks the functions most "
            "likely responsible.\n"
            "2. **Analyze:** it reads those functions' real source code and returns the root cause, debugging "
            "steps, fixes and severity.\n"
            "3. **Ticket (optional):** the analysis becomes a fully filled-in JIRA ticket."
        )
    if sample_index:
        with st.expander(f"Browse the index ({summary.total_functions} functions)"):
            st.dataframe(
                [{"File": f.path, "Function": fn.name, "Description": fn.description}
                 for f in sample_index.files for fn in f.functions],
                hide_index=True,
            )

# ── Run the analysis ─────────────────────────────────────────────────────────
if analyze_clicked:
    if not raw_json or not raw_json.strip():
        st.error("Paste a JSON error log entry first.")
        st.stop()

    try:
        log_entry = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
        st.stop()

    if not isinstance(log_entry, dict):
        st.error("The log entry must be a JSON object, e.g. {\"message\": \"...\", \"service\": \"...\"} — not a bare string, number, or list.")
        st.stop()

    event = ErrorEvent(
        id=str(uuid.uuid4()),
        raw_line=raw_json,
        log_entry=log_entry,
        detected_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        start = time.perf_counter()
        with st.spinner("Running the two-step LLM analysis..."):
            analyzer = TwoStepAnalyzer(index=index)
            analyzed = asyncio.run(analyzer.analyze(event) if index else analyzer.analyze_without_index(event))
        st.session_state.result = analyzed
        st.session_state.run_meta = {"seconds": time.perf_counter() - start, "mode": "Index" if index else "Error-only"}
        st.session_state.jira_ticket = None  # new analysis — clear any ticket from a previous one
    except Exception as exc:
        st.error(f"Analysis failed: {exc}")
        st.session_state.result = None

# ── Results ──────────────────────────────────────────────────────────────────
result, meta = st.session_state.result, st.session_state.run_meta
if result:
    st.divider()
    st.subheader("Analysis result")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Severity", result.step2.severity.title())
    m2.metric("Confidence", f"{result.step2.confidence_score:.0%}")
    m3.metric("Suspected functions", len(result.step1.suspected_functions) or "—")
    m4.metric("Analysis time", f"{meta['seconds']:.1f} s" if meta else "—")
    m5.metric("Mode", meta["mode"] if meta else "—")

    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        st.markdown("**Root cause**")
        with st.container(border=True):
            st.markdown(result.step2.root_cause)
        st.markdown("**Technical explanation**")
        st.markdown(result.step2.technical_explanation)
    with col_b:
        st.markdown("**Debugging steps**")
        st.markdown("\n".join(f"- {step}" for step in result.step2.debugging_steps))
        st.markdown("**Possible fixes**")
        for fix in result.step2.possible_fixes:
            st.markdown(f"- {fix}")

    # Show the real source of the suspected functions when the index was used
    fn_map = {fn.name: (fn, f.path) for f in sample_index.files for fn in f.functions} \
        if (sample_index and meta and meta["mode"] == "Index") else {}
    suspects = [name for name in result.step1.suspected_functions if name in fn_map]
    if suspects:
        st.markdown("**Suspect code (from the index)**")
        st.caption(result.step1.reasoning)
        for name in suspects:
            fn, path = fn_map[name]
            with st.expander(f"{name} · {path} (lines {fn.start_line}–{fn.end_line})"):
                st.code(fn.source_code, language="python" if path.endswith(".py") else None)
    elif result.step1.suspected_functions:
        st.caption("Suspected (from the traceback): " + ", ".join(result.step1.suspected_functions))

    if result.step2.affected_components:
        st.caption("Affected components: " + ", ".join(result.step2.affected_components))

    st.divider()
    st.subheader("JIRA ticket")

    if st.session_state.jira_ticket:
        ticket_id, ticket_url = st.session_state.jira_ticket
        st.success(f"Ticket created: [{ticket_id}]({ticket_url})")
    elif not jira_configured:
        st.info("Fill in your JIRA credentials in the sidebar to create a real ticket from this analysis.")
    else:
        if st.button("Create JIRA ticket"):
            try:
                with st.spinner("Creating ticket..."):
                    jira = JiraClient(
                        base_url=jira_base_url,
                        email=jira_email,
                        api_token=jira_api_token,
                        project_key=jira_project_key,
                    )
                    ticket = asyncio.run(jira.create_ticket(result))
                st.session_state.jira_ticket = (ticket.ticket_id, ticket.ticket_url)

                log_entry = result.error.log_entry
                notify_ticket_created(
                    ticket_id=ticket.ticket_id,
                    ticket_url=ticket.ticket_url,
                    error_message=str(log_entry.get("message", ""))[:200],
                    service=str(log_entry.get("service", "unknown")),
                    severity=result.step2.severity,
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Ticket creation failed: {exc}")

        if not email_configured():
            st.caption("Owner notification email isn't configured on this deployment — ticket creation still works either way.")
