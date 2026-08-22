# 🔍 Debug Pipeline

Automated backend error detection and root-cause analysis. Watches a live log file (or a health-check URL), runs a two-step LLM pipeline to diagnose each error against your indexed codebase, and files a JIRA ticket with the full analysis — no manual triage.

## How it works

```
1. Index your backend code once   →  POST /api/v1/index/upload  (or /index/path)
2. Start monitoring a log/health  →  POST /api/v1/monitor/start
3. An error is detected           →  two-step LLM analysis runs automatically
4. A JIRA ticket is created       →  root cause, fixes, and debugging steps included
```

**Step 1 — Identify**: the error log entry + the function index (names, descriptions) go to the LLM, which returns the functions most likely responsible.

**Step 2 — Analyze**: the actual source of those suspected functions is pulled from the index and sent back to the LLM for a full root-cause analysis — technical explanation, debugging steps, possible fixes, severity, and affected components.

The JIRA ticket is created with the complete analysis embedded in the description (plus a plain-text comment as backup), so a ticket lands in the queue fully triaged.

## Features

- **Codebase indexer** — parses Python, JavaScript/TypeScript, Java, and Go source into a function-level index (name, description, source, API routes, imports).
- **Log or health-check monitoring** — tail a JSON log file for `ERROR`/`CRITICAL`/`FATAL` lines, or poll a URL and raise an event after repeated failures.
- **Two-step LLM analysis** (Groq, `llama-3.3-70b-versatile`) — suspects functions first, then does a deep-dive on their actual source code.
- **Automatic JIRA ticket creation** — falls back through Bug→Task issue types and drops the priority/description fields if the project rejects them, so ticket creation doesn't fail silently.
- **Non-blocking pipeline** — errors are queued and analyzed as background tasks (one LLM call at a time via a semaphore) so the log watcher is never blocked.
- **Streamlit dashboard** — live view of indexed functions, monitor status, and analyzed events.

## Tech stack

Python, FastAPI, Groq (LLaMA 3.3), JIRA REST API v3, Streamlit, Pydantic.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_groq_api_key
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_EMAIL=you@yourorg.com
JIRA_API_TOKEN=your_jira_api_token
JIRA_PROJECT_KEY=PROJ
```

Run the API:

```bash
uvicorn app.main:app --port 8088
```

Run the dashboard (in a separate terminal):

```bash
streamlit run frontend/streamlit_app.py
```

## API reference

| Endpoint | Description |
|---|---|
| `POST /api/v1/index/upload` | Upload a ZIP of your backend and build the function index |
| `POST /api/v1/index/path` | Index a local directory already on the server |
| `GET /api/v1/index/status` | Current index status |
| `POST /api/v1/monitor/start` | Start watching a log file or a health-check URL |
| `POST /api/v1/monitor/stop` | Stop the active monitor |
| `GET /api/v1/monitor/status` | Current monitor status and counters |
| `GET /api/v1/monitor/events` | Analyzed error events, newest first |
| `GET /api/v1/monitor/jira-test` | Verify JIRA credentials and list available issue types/priorities |
| `GET /health` | Service health check |

Interactive docs are available at `/docs` once the API is running.

## Project structure

```
app/
├── analyzer/       # Two-step LLM analysis pipeline
├── indexer/        # Codebase parsers (Python/JS/TS/Java/Go) + index builder
├── jira/           # JIRA ticket creation client
├── monitor/        # Log tailing / health-check watcher
├── routers/        # FastAPI endpoints (index, monitor)
├── config.py       # Settings (Groq + JIRA credentials)
└── main.py         # FastAPI app entrypoint
frontend/
└── streamlit_app.py
log_generator/       # Fake log generator for local testing
```
