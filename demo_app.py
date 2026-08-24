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
from app.models import ErrorEvent
from app.jira.client import JiraClient
from app.notifier.email_notifier import notify_ticket_created, is_configured as email_configured
import uuid
from datetime import datetime, timezone

st.set_page_config(page_title="Debug Pipeline — Demo", page_icon="🔍", layout="wide")

REPO_ROOT = Path(__file__).parent
SAMPLE_LOG = REPO_ROOT / "sample_logs" / "app.log"


def _load_sample_errors() -> list[dict]:
    if not SAMPLE_LOG.exists():
        return []
    entries = []
    for line in SAMPLE_LOG.read_text().splitlines():
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
if "index" not in st.session_state:
    st.session_state.index = None
if "result" not in st.session_state:
    st.session_state.result = None
if "jira_ticket" not in st.session_state:
    st.session_state.jira_ticket = None  # (ticket_id, ticket_url) once created for the current result

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🔍 Debug Pipeline")
    st.caption("Automated backend error detection & root-cause analysis")

    st.subheader("1. Codebase index (optional)")
    st.caption("Index this repo's own `app/` folder so the analyzer can cite real suspect functions and source code.")
    if st.session_state.index is None:
        if st.button("📂 Index this repo's app/ folder"):
            try:
                with st.spinner("Indexing..."):
                    index = asyncio.run(IndexingService(REPO_ROOT / "app").run())
                if index.summary.total_files == 0:
                    st.warning("No source files found to index.")
                else:
                    st.session_state.index = index
                    st.rerun()
            except Exception as exc:
                st.error(f"Indexing failed: {exc}")
    else:
        idx = st.session_state.index
        st.success(f"Indexed: {idx.summary.total_files} files, {idx.summary.total_functions} functions")
        if st.button("Clear index"):
            st.session_state.index = None
            st.rerun()

    st.divider()
    st.subheader("2. JIRA (optional)")
    st.caption(
        "Enter your own JIRA Cloud credentials to try real ticket creation. "
        "Used only for this session — never stored or logged."
    )
    jira_base_url = st.text_input("JIRA base URL", placeholder="https://yourorg.atlassian.net")
    jira_email = st.text_input("JIRA account email", placeholder="you@yourorg.com")
    jira_api_token = st.text_input("JIRA API token", type="password", help="Create one at id.atlassian.com/manage-profile/security/api-tokens")
    jira_project_key = st.text_input("JIRA project key", placeholder="PROJ")
    jira_configured = all([jira_base_url, jira_email, jira_api_token, jira_project_key])

    st.divider()
    from app.config import settings as _settings
    if not _settings.groq_api_key or _settings.groq_api_key == "YOUR_GROQ_API_KEY":
        st.error("GROQ_API_KEY is not set. Add it to a .env file locally, or to Streamlit secrets when deployed.")

st.title("Analyze a production error")
st.caption("Pick a sample error, or paste your own JSON log line, then run the two-step LLM root-cause analysis.")

samples = _load_sample_errors()
sample_labels = [f"{e.get('service', '?')} — {str(e.get('message', ''))[:70]}" for e in samples]

col1, col2 = st.columns([1, 1])
with col1:
    choice = st.selectbox("Sample errors (from sample_logs/app.log)", ["— custom —"] + sample_labels)

if choice != "— custom —":
    default_json = json.dumps(samples[sample_labels.index(choice)], indent=2)
else:
    default_json = json.dumps({
        "message": "TypeError: cannot unpack non-iterable NoneType object",
        "service": "checkout-api",
        "level": "ERROR",
    }, indent=2)

raw_json = st.text_area("Error log entry (JSON)", value=default_json, height=180)

analyze_clicked = st.button("🧠 Analyze", type="primary")

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
        with st.spinner("Running two-step LLM analysis..."):
            analyzer = TwoStepAnalyzer(index=st.session_state.index)
            if st.session_state.index is not None:
                analyzed = asyncio.run(analyzer.analyze(event))
            else:
                analyzed = asyncio.run(analyzer.analyze_without_index(event))
            st.session_state.result = analyzed
            st.session_state.jira_ticket = None  # new analysis — clear any ticket from a previous one
    except Exception as exc:
        st.error(f"Analysis failed: {exc}")
        st.session_state.result = None

result = st.session_state.result
if result:
    st.divider()
    sev_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(result.step2.severity, "⚪")
    c1, c2, c3 = st.columns(3)
    c1.metric("Severity", f"{sev_color} {result.step2.severity}")
    c2.metric("Confidence", f"{result.step2.confidence_score:.0%}")
    c3.metric("Suspected functions", len(result.step1.suspected_functions) or "—")

    st.subheader("Root cause")
    st.write(result.step2.root_cause)

    st.subheader("Technical explanation")
    st.write(result.step2.technical_explanation)

    st.subheader("Debugging steps")
    for step in result.step2.debugging_steps:
        st.markdown(f"- {step}")

    st.subheader("Possible fixes")
    for fix in result.step2.possible_fixes:
        st.markdown(f"- {fix}")

    if result.step1.suspected_functions:
        with st.expander(f"Suspected functions ({len(result.step1.suspected_functions)})"):
            st.write(", ".join(result.step1.suspected_functions))
            st.caption(result.step1.reasoning)

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
        if st.button("🎫 Create JIRA Ticket"):
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
