"""
Debug Pipeline — Streamlit Frontend

Run:  streamlit run frontend/streamlit_app.py
API:  uvicorn app.main:app --port 8088
"""
import time
import json
import requests
import streamlit as st

API = "http://localhost:8088/api/v1"

st.set_page_config(
    page_title="Debug Pipeline",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🔍 Debug Pipeline")
    st.caption("Automated backend error detection & analysis")
    st.divider()

    # Live health status
    try:
        h = requests.get("http://localhost:8088/health", timeout=2).json()
        st.success("API online")
        col1, col2 = st.columns(2)
        col1.metric("Index", "✅" if h["index_loaded"] else "❌")
        col2.metric("Monitor", "🟢" if h["monitoring"] else "⚫")
        st.caption(f"Model: {h['model']}")
        st.caption(f"Events: {h['events_count']}")
    except Exception:
        st.error("⚠ API offline — start with:\nuvicorn app.main:app --port 8088")

    st.divider()
    page = st.radio(
        "Navigation",
        ["⚙️ Setup Index", "📡 Live Monitor", "📋 Event History", "🔧 JIRA Test", "🧪 Log Generator"],
        label_visibility="collapsed",
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def api_get(path, timeout=15, **kwargs):
    try:
        return requests.get(f"{API}{path}", timeout=timeout, **kwargs)
    except requests.exceptions.Timeout:
        st.error(f"⏱ Request timed out ({timeout}s). The server is running but took too long.")
        return None
    except requests.exceptions.ConnectionError:
        st.error("🔌 Cannot reach API — is `uvicorn app.main:app --port 8088` running?")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"Request error: {e}")
        return None


def api_post(path, timeout=60, **kwargs):
    try:
        return requests.post(f"{API}{path}", timeout=timeout, **kwargs)
    except requests.exceptions.Timeout:
        st.error(f"⏱ Request timed out ({timeout}s).")
        return None
    except requests.exceptions.ConnectionError:
        st.error("🔌 Cannot reach API — is `uvicorn app.main:app --port 8088` running?")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"Request error: {e}")
        return None


def severity_badge(severity: str) -> str:
    colors = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    return f"{colors.get(severity, '⚪')} {severity.upper()}"


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — SETUP INDEX
# ══════════════════════════════════════════════════════════════════════════════
if page == "⚙️ Setup Index":
    st.header("⚙️ Step 1 — Index Your Backend Codebase")
    st.info(
        "This is a **one-time setup**. Upload your backend source code and the agent "
        "will extract every function's name, description (from docstrings/comments), "
        "and source code. This index is saved to `backend_index.json` and reloaded automatically on restart."
    )

    # Current status
    resp = api_get("/index/status")
    if resp and resp.ok:
        s = resp.json()
        if s["indexed"]:
            st.success(
                f"✅ Index loaded — **{s['total_files']} files**, **{s['total_functions']} functions**  "
                f"| Root: `{s['root_path']}` | Built: {s.get('created_at', 'unknown')[:19]}"
            )
        else:
            st.warning("No index loaded yet.")

    st.divider()
    tab_upload, tab_path = st.tabs(["📦 Upload ZIP", "📁 Local Directory Path"])

    with tab_upload:
        st.subheader("Upload a ZIP of your backend")
        uploaded = st.file_uploader(
            "Select your backend ZIP file",
            type="zip",
            help="Supports Python, JavaScript, TypeScript, Java, Go",
        )
        if st.button("🚀 Build Index from ZIP", disabled=uploaded is None):
            with st.spinner("Indexing source code — extracting functions and descriptions..."):
                r = requests.post(
                    f"{API}/index/upload",
                    files={"file": (uploaded.name, uploaded.getvalue(), "application/zip")},
                    timeout=120,
                )
            if r.ok:
                data = r.json()
                st.success(
                    f"✅ Index built! **{data['summary']['total_files']} files**, "
                    f"**{data['summary']['total_functions']} functions**, "
                    f"**{data['summary']['total_classes']} classes**"
                )
                with st.expander("View language breakdown"):
                    st.json(data["summary"]["languages_detected"])
                with st.expander("View all dependencies"):
                    st.write(", ".join(data["summary"]["all_dependencies"]))
            else:
                st.error(f"Indexing failed: {r.text[:300]}")

    with tab_path:
        st.subheader("Index a directory on this server")
        dir_path = st.text_input("Absolute directory path", placeholder="C:/projects/my-backend")
        if st.button("🚀 Build Index from Path", disabled=not dir_path):
            with st.spinner("Indexing..."):
                r = api_post(f"/index/path?directory={dir_path}")
            if r and r.ok:
                data = r.json()
                st.success(
                    f"✅ Index built! **{data['summary']['total_files']} files**, "
                    f"**{data['summary']['total_functions']} functions**"
                )
            elif r:
                st.error(f"Failed: {r.text[:300]}")

    # Show indexed functions sample
    resp = api_get("/index/status")
    if resp and resp.ok and resp.json()["indexed"]:
        st.divider()
        st.subheader("📖 Index Preview")
        st.caption("Showing a sample of indexed functions (from saved index file):")
        try:
            import pathlib
            idx_path = pathlib.Path("backend_index.json")
            if idx_path.exists():
                idx = json.loads(idx_path.read_text())
                rows = []
                for f in idx.get("files", [])[:5]:
                    for fn in f.get("functions", [])[:3]:
                        rows.append({
                            "File": f["path"],
                            "Function": fn["name"],
                            "Description": fn["description"][:100],
                            "Lines": f"{fn['start_line']}–{fn['end_line']}",
                        })
                if rows:
                    st.dataframe(rows, use_container_width=True)
        except Exception as e:
            st.caption(f"Preview unavailable: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — LIVE MONITOR
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📡 Live Monitor":
    st.header("📡 Step 2 — Monitor Live JSON Logs")

    # ── Live debug panel ──────────────────────────────────────────────────────
    dbg_resp = api_get("/monitor/debug")
    dbg = dbg_resp.json() if dbg_resp and dbg_resp.ok else {}

    is_running = dbg.get("monitor_running", False)

    monitor_type = dbg.get("monitor_type", "log")
    if is_running:
        if monitor_type == "health":
            st.success(f"🟢 Health monitoring active — `{dbg.get('health_url', '')}`")
        else:
            st.success(f"🟢 Log monitoring active — `{dbg.get('log_path', '')}`")
    else:
        st.warning("⚫ Monitor is stopped.")

    # Live pipeline counters — always visible
    c1, c2, c3, c4 = st.columns(4)
    if monitor_type == "health":
        c1.metric("Failed checks", dbg.get("health_failures", 0))
        c2.metric("⏳ Queued (analysing)", dbg.get("errors_queued_for_analysis", 0))
        c3.metric("✅ Fully analysed", dbg.get("errors_fully_analyzed", 0))
    else:
        c1.metric("Errors in log", dbg.get("errors_detected_in_log", 0))
        c2.metric("⏳ Queued (analysing)", dbg.get("errors_queued_for_analysis", 0))
        c3.metric("✅ Fully analysed", dbg.get("errors_fully_analyzed", 0))
    c4.metric("Index functions", dbg.get("index_functions", 0),
              help="0 = no index loaded; upload in Setup Index tab")

    # Groq key warning
    if not dbg.get("groq_key_looks_valid", True):
        st.error(
            "⚠️ **Groq API key looks invalid** — check `GROQ_API_KEY` in your "
            "`.env` or `.env.example` file and restart the server. "
            "Key must start with `gsk_`."
        )

    # Last detected error or health failure
    if dbg.get("last_error_message"):
        st.info(f"🔎 Last detected: `{dbg['last_error_message']}`")

    # Queued spinner
    if dbg.get("errors_queued_for_analysis", 0) > 0:
        st.warning(
            f"⏳ **{dbg['errors_queued_for_analysis']} error(s) are being analysed by LLM** — "
            "results will appear below in ~15–30 s each. Page auto-refreshes."
        )

    st.divider()
    monitor_mode = st.radio(
        "Monitor mode",
        ["Log file watcher", "Health check"],
        index=0 if monitor_type == "log" else 1,
    )

    col_start, col_stop = st.columns(2)

    with col_start:
        st.subheader("Start Monitoring")
        if monitor_mode == "Log file watcher":
            st.caption("Enter the absolute path to your JSON log file:")
            log_path_input = st.text_input(
                "JSON log file path",
                value=r"C:\Users\naman\Downloads\debug_pipeline\test_logs\live.log",
                label_visibility="collapsed",
            )
            st.caption(
                "**Test file:**  "
                r"`C:\Users\naman\Downloads\debug_pipeline\test_logs\live.log`  "
                "— generate it first using **🧪 Log Generator**"
            )
            payload = {"monitor_type": "log", "log_path": log_path_input}
            ready_to_start = bool(log_path_input)
            start_message = "Monitor started — replaying log file..."
        else:
            st.caption(
                "Health check polls your site every 3 seconds. "
                "If the site fails 3 consecutive checks, a JIRA ticket will be created."
            )
            health_url_input = st.text_input(
                "Health check URL",
                value="https://example.com/health",
                label_visibility="collapsed",
            )
            st.caption("Enter the URL that should respond successfully to each health check.")
            payload = {
                "monitor_type": "health",
                "health_url": health_url_input,
                "check_interval_sec": 3,
                "failure_threshold": 3,
            }
            ready_to_start = bool(health_url_input)
            start_message = "Health monitor started — polling every 3 seconds..."

        btn_label = "🔄 Restart" if is_running else "▶️ Start"
        if st.button(btn_label, disabled=not ready_to_start, type="primary"):
            if is_running:
                api_post("/monitor/stop")
                import time
                time.sleep(0.5)
            r = api_post("/monitor/start", json=payload)
            if r and r.ok:
                st.success(start_message)
                st.rerun()
            elif r:
                try:
                    detail = r.json().get("detail", r.text)
                except Exception:
                    detail = r.text
                st.error(f"Failed ({r.status_code}): {detail}")

    with col_stop:
        st.subheader("Controls")
        if st.button("⏹ Stop Monitor", disabled=not is_running):
            r = api_post("/monitor/stop")
            if r and r.ok:
                st.info("Monitor stopped.")
                st.rerun()
        if st.button("🗑 Clear All Events"):
            requests.delete(f"{API}/monitor/events", timeout=5)
            st.rerun()

    st.divider()
    st.subheader("🔴 Analysed Errors")

    auto_refresh = st.checkbox("Auto-refresh every 4 seconds", value=is_running)

    resp = api_get("/monitor/events?limit=20")
    events = resp.json() if resp and resp.ok else []

    if not events:
        if is_running and dbg.get("errors_detected_in_log", 0) > 0:
            st.info(
                f"🔄 **{dbg['errors_detected_in_log']} error(s) detected, LLM analysing them...** "
                "Results appear here once analysis completes (~15–30 s each)."
            )
        elif is_running:
            st.info("Watching for errors. No ERROR/CRITICAL/FATAL lines found yet.")
        else:
            st.info("Start the monitor and point it at a log file.")
    else:
        for ev in events:
            msg = (
                ev["error"]["log_entry"].get("message")
                or ev["error"]["log_entry"].get("msg", "No message")
            )
            sev = ev["step2"]["severity"]
            with st.expander(
                f"{severity_badge(sev)}  |  {msg[:90]}  |  {ev['error']['detected_at'][:19]}"
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("Severity", sev.upper())
                c2.metric("Confidence", f"{ev['step2']['confidence_score']:.0%}")
                c3.metric("JIRA", ev["jira"]["ticket_id"] if ev.get("jira") else "—")

                st.markdown(f"**Root Cause:** {ev['step2']['root_cause']}")

                st.markdown("**Suspected Functions (Step 1):**")
                fns = ev["step1"]["suspected_functions"]
                st.write(", ".join(f"`{f}`" for f in fns) if fns else "None identified")
                st.caption(f"Reasoning: {ev['step1']['reasoning']}")

                st.markdown("**Debugging Steps:**")
                for step in ev["step2"]["debugging_steps"]:
                    st.markdown(f"- {step}")

                st.markdown("**Possible Fixes:**")
                for fix in ev["step2"]["possible_fixes"]:
                    st.markdown(f"- {fix}")

                if ev.get("jira"):
                    st.success(
                        f"JIRA: [{ev['jira']['ticket_id']}]({ev['jira']['ticket_url']})"
                    )

                st.caption("Raw log entry:")
                st.json(ev["error"]["log_entry"])

    if auto_refresh and (is_running or dbg.get("errors_queued_for_analysis", 0) > 0):
        time.sleep(4)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — EVENT HISTORY
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📋 Event History":
    st.header("📋 Event History")

    resp = api_get("/monitor/events?limit=200")
    events = resp.json() if resp and resp.ok else []

    if not events:
        st.info("No analyzed events yet.")
        st.stop()

    st.caption(f"Total events: {len(events)}")

    # Summary table
    rows = []
    for ev in events:
        msg = (
            ev["error"]["log_entry"].get("message")
            or ev["error"]["log_entry"].get("msg", "")
        )
        rows.append({
            "Time": ev["error"]["detected_at"][:19],
            "Severity": ev["step2"]["severity"].upper(),
            "Message": msg[:80],
            "Suspected Functions": ", ".join(ev["step1"]["suspected_functions"]) or "—",
            "JIRA Ticket": ev["jira"]["ticket_id"] if ev.get("jira") else "—",
            "Confidence": f"{ev['step2']['confidence_score']:.0%}",
        })

    st.dataframe(rows, use_container_width=True)

    st.divider()
    st.subheader("Event Detail")

    event_ids = [f"{ev['error']['detected_at'][:19]} — {ev['id'][:8]}" for ev in events]
    selected = st.selectbox("Select event", event_ids)
    if selected:
        idx = event_ids.index(selected)
        ev = events[idx]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Severity", ev["step2"]["severity"].upper())
        c2.metric("Confidence", f"{ev['step2']['confidence_score']:.0%}")
        c3.metric("Step 1 Confidence", f"{ev['step1']['confidence']:.0%}")
        c4.metric("JIRA", ev["jira"]["ticket_id"] if ev.get("jira") else "—")

        st.markdown(f"### Root Cause\n{ev['step2']['root_cause']}")
        st.markdown(f"### Technical Explanation\n{ev['step2']['technical_explanation']}")

        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("**Debugging Steps**")
            for s in ev["step2"]["debugging_steps"]:
                st.markdown(f"- {s}")
        with col_r:
            st.markdown("**Possible Fixes**")
            for f in ev["step2"]["possible_fixes"]:
                st.markdown(f"- {f}")

        st.markdown("**Suspected Functions (Step 1)**")
        st.write(", ".join(ev["step1"]["suspected_functions"]) or "None")
        st.caption(ev["step1"]["reasoning"])

        if ev.get("jira"):
            st.success(
                f"JIRA ticket **[{ev['jira']['ticket_id']}]({ev['jira']['ticket_url']})** "
                f"created at {ev['jira']['created_at'][:19]}"
            )

        with st.expander("Raw log entry JSON"):
            st.json(ev["error"]["log_entry"])

        with st.expander("Full event JSON"):
            st.json(ev)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — JIRA TEST
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔧 JIRA Test":
    st.header("🔧 JIRA Connection Test")
    st.info(
        "Use this page to verify your JIRA credentials and see exactly what "
        "issue types and priorities are available in your project."
    )

    if st.button("🔌 Test JIRA Connection", type="primary"):
        with st.spinner("Connecting to JIRA — this takes up to 30 seconds..."):
            # Long timeout: JIRA test makes 2 external HTTPS calls to Atlassian
            r = api_get("/monitor/jira-test", timeout=45)

        if r is None:
            st.warning(
                "The API server could not be reached or timed out. "
                "Make sure `uvicorn app.main:app --port 8088` is running "
                "and you have restarted it after the latest code update."
            )
            st.stop()

        if not r.ok:
            st.error(f"API returned HTTP {r.status_code}. "
                     "Restart uvicorn — the `/monitor/jira-test` endpoint may not exist yet.")
            st.code(r.text[:400])
            st.stop()

        data = r.json()

        if data.get("ok"):
                st.success(f"✅ JIRA connected! Logged in as: **{data.get('logged_in_as')}**")

                c1, c2 = st.columns(2)
                c1.metric("Project", data.get("project_name", "—"))
                c2.metric("Project Key", data.get("jira_project_key", "—"))

                col_l, col_r = st.columns(2)
                with col_l:
                    st.markdown("**Available Issue Types**")
                    for it in data.get("issue_types", []):
                        st.markdown(f"- `{it}`")
                    st.caption(
                        "If 'Bug' is not listed above, the client will use 'Task' automatically."
                    )

                with col_r:
                    st.markdown("**Available Priorities**")
                    for p in data.get("priorities", []):
                        st.markdown(f"- `{p}`")
                    st.caption(
                        "If 'Highest/High/Medium/Low' don't match, "
                        "edit SEVERITY_TO_PRIORITY in app/jira/client.py."
                    )

        else:
            st.error(f"❌ JIRA connection failed:\n\n`{data.get('error')}`")
            st.markdown("### Troubleshooting")
            st.markdown("""
1. **Wrong API token** — generate a new one at https://id.atlassian.com/manage-profile/security/api-tokens
2. **Wrong email** — must be the email you log into JIRA with
3. **Wrong base URL** — must be exactly `https://yourorg.atlassian.net` (no trailing path)
4. **Wrong project key** — go to JIRA → Project Settings → Details → Key
5. **Token in quotes** — make sure `.env.example` has NO quotes around the token value
""")

    st.divider()
    st.subheader("Current JIRA Config (from .env / .env.example)")
    # Use a short timeout here — we only want the config fields, not a full connection test
    try:
        from app.config import settings as _s
        st.markdown(f"- **Base URL:** `{_s.jira_base_url}`")
        st.markdown(f"- **Email:** `{_s.jira_email}`")
        st.markdown(f"- **Project Key:** `{_s.jira_project_key}`")
        token_ok = _s.jira_api_token and _s.jira_api_token != "YOUR_JIRA_API_TOKEN"
        st.markdown(f"- **API Token set:** {'✅ Yes' if token_ok else '❌ No (still placeholder)'}")
    except Exception:
        # Fallback: read from API with 45s timeout
        r2 = api_get("/monitor/jira-test", timeout=45)
        if r2 and r2.ok:
            d = r2.json()
            st.markdown(f"- **Base URL:** `{d.get('jira_base_url', '—')}`")
            st.markdown(f"- **Email:** `{d.get('jira_email', '—')}`")
            st.markdown(f"- **Project Key:** `{d.get('jira_project_key', '—')}`")
            st.markdown(f"- **API Token set:** {'✅ Yes' if d.get('api_token_set') else '❌ No'}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — LOG GENERATOR
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🧪 Log Generator":
    import subprocess
    import sys
    import os

    st.header("🧪 Fake Log Generator")
    st.info(
        "Generate realistic JSON logs — **authentication**, **API requests**, "
        "**database operations**, **payments**, **cache**, and **worker** events — "
        "with injected ERROR / CRITICAL / FATAL entries so the pipeline detects them."
    )

    st.divider()

    col_cfg, col_preview = st.columns([1, 1])

    with col_cfg:
        st.subheader("Configuration")

        out_path = st.text_input(
            "Output log file path",
            value=r"C:\Users\naman\Downloads\debug_pipeline\test_logs\live.log",
            help="File is APPENDED to if it already exists.",
        )

        gen_mode = st.radio(
            "Mode",
            ["📦 Batch (generate N lines, then stop)", "🔴 Live Stream (continuous, 1 line/interval)"],
            index=0,
        )

        if "Batch" in gen_mode:
            n_lines = st.slider("Number of log lines", min_value=20, max_value=1000, value=150, step=10)
            interval = 0.0
        else:
            n_lines = None
            interval = st.slider("Interval between lines (seconds)", min_value=0.2, max_value=5.0,
                                 value=1.0, step=0.1)

        error_rate = st.slider(
            "Error rate (fraction of ERROR/CRITICAL/FATAL lines)",
            min_value=0.05, max_value=0.60, value=0.15, step=0.05,
            format="%.0f%%",
            help="0.15 = ~15% of lines are errors. Higher = more JIRA tickets created.",
        )

        st.markdown("---")
        st.caption("Log types included:")
        st.markdown(
            "🔑 **Auth** — login, JWT, OAuth, brute-force  \n"
            "🌐 **API** — GET/POST requests, rate limits  \n"
            "🗄️ **Database** — queries, deadlocks, pool exhaustion  \n"
            "💳 **Payment** — Stripe charges, timeouts, declines  \n"
            "⚡ **Cache** — Redis hits/misses/errors  \n"
            "⚙️ **Workers** — Celery tasks, retries, crashes  \n"
            "🖥️ **System** — health, deploys, backups"
        )

    with col_preview:
        st.subheader("Live Preview (sample lines)")
        if st.button("🔄 Generate Sample Preview", type="secondary"):
            import sys, os
            sys.path.insert(0, os.path.abspath("."))
            try:
                from log_generator.fake_log_generator import generate_line
                preview_lines = [generate_line(error_rate) for _ in range(12)]
                preview_text = "\n".join(preview_lines)
                st.code(preview_text, language="json")
            except Exception as e:
                st.error(f"Preview error: {e}")

        st.markdown("")
        st.subheader("Log counts")
        if out_path and os.path.exists(out_path):
            try:
                with open(out_path, encoding="utf-8", errors="replace") as f:
                    all_lines = [l.strip() for l in f if l.strip()]
                import json as _json
                total = len(all_lines)
                errors = 0
                for line in all_lines:
                    try:
                        lvl = _json.loads(line).get("level", "")
                        if lvl in ("ERROR", "CRITICAL", "FATAL"):
                            errors += 1
                    except Exception:
                        pass
                m1, m2, m3 = st.columns(3)
                m1.metric("Total lines", total)
                m2.metric("Error lines", errors)
                m3.metric("Error %", f"{errors/total*100:.1f}%" if total else "—")
            except Exception as e:
                st.caption(f"Could not read file: {e}")
        else:
            st.caption("File does not exist yet — will be created when you generate.")

    st.divider()

    # ── Action buttons ────────────────────────────────────────────────────────
    ca, cb, cc = st.columns(3)

    gen_script = os.path.abspath(
        os.path.join(os.path.dirname(__file__) or ".", "..", "log_generator", "fake_log_generator.py")
    )

    with ca:
        btn_gen = st.button("▶️ Generate Now", type="primary", use_container_width=True,
                            disabled=not out_path)
    with cb:
        btn_clear = st.button("🗑 Clear Log File", use_container_width=True,
                              disabled=not out_path)
    with cc:
        btn_open_monitor = st.button("📡 Use in Monitor", use_container_width=True,
                                     help="Switches to Live Monitor page with this file pre-loaded")

    if btn_clear and out_path:
        try:
            open(out_path, "w").close()
            st.success(f"Cleared: `{out_path}`")
        except Exception as e:
            st.error(f"Could not clear: {e}")

    if btn_open_monitor:
        st.session_state["monitor_path"] = out_path
        st.info(f"Go to 📡 Live Monitor and paste:  `{out_path}`")

    if btn_gen and out_path:
        cmd = [sys.executable, gen_script, "--output", out_path,
               "--error-rate", str(error_rate)]
        if n_lines is not None:
            cmd += ["--count", str(n_lines)]
        else:
            cmd += ["--interval", str(interval)]

        if "Batch" in gen_mode:
            with st.spinner(f"Generating {n_lines} log lines into `{out_path}` ..."):
                try:
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=120,
                        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__) or ".", ".."))
                    )
                    if result.returncode == 0:
                        st.success(f"✅ Done! {n_lines} lines written to `{out_path}`")
                        st.caption(result.stderr.strip())
                    else:
                        st.error(f"Generator failed:\n{result.stderr[:500]}")
                except subprocess.TimeoutExpired:
                    st.error("Generator timed out (>120s).")
                except Exception as e:
                    st.error(f"Error running generator: {e}")
        else:
            st.warning(
                "**Live stream mode** cannot run inside Streamlit — it would block the UI.  \n"
                "Run this command in a **separate terminal** instead:\n"
            )
            cmd_str = " ".join(cmd)
            st.code(cmd_str, language="bash")
            st.info(
                "Then go to **📡 Live Monitor**, set the log path to:  \n"
                f"`{out_path}`  \n"
                "and click **▶️ Start** — errors will stream in live."
            )

    st.divider()
    st.subheader("Quick-start commands")
    st.caption("Copy and run in a terminal from the `debug_pipeline` folder:")

    st.code(
        "# Batch: 200 lines with 20% error rate\n"
        "python log_generator/fake_log_generator.py "
        "--output test_logs/live.log --count 200 --error-rate 0.20\n\n"
        "# Live stream: 1 line per second, 15% errors\n"
        "python log_generator/fake_log_generator.py "
        "--output test_logs/live.log --interval 1.0 --error-rate 0.15\n\n"
        "# Fast stream: 1 line per 0.5s, print to screen too\n"
        "python log_generator/fake_log_generator.py "
        "--output test_logs/live.log --interval 0.5 --stdout",
        language="bash",
    )
