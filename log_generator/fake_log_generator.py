from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# DATA POOLS
# ─────────────────────────────────────────────────────────────────────────────

SERVICES = [
    "auth-service",
    "api-gateway",
    "user-service",
    "product-service",
    "order-service",
    "payment-service",
    "notification-service",
    "db-service",
    "cache-service",
    "worker-service",
]

HOSTS = [
    "prod-server-01", "prod-server-02", "prod-server-03",
    "worker-01", "worker-02", "db-primary", "db-replica",
]

USER_IDS   = list(range(1, 201))
PRODUCT_IDS = list(range(100, 300))
ORDER_IDS   = list(range(5000, 6000))

ENDPOINTS_GET  = ["/users/{id}", "/products", "/products/{id}", "/orders/{id}",
                  "/health", "/metrics", "/cart", "/search?q=shoes"]
ENDPOINTS_POST = ["/auth/login", "/auth/logout", "/auth/register", "/auth/refresh",
                  "/orders", "/orders/{id}/pay", "/cart/add", "/checkout"]

EMAILS = [
    "alice@example.com", "bob@corp.io", "charlie@test.net",
    "dave@example.org", "eve@startup.co", "frank@bigco.com",
    "grace@email.com", "henry@domain.net",
]

IP_ADDRESSES = [
    "192.168.1.10", "10.0.0.5", "172.16.0.22",
    "203.0.113.50", "198.51.100.8", "185.220.101.5",  # last two = suspicious
    "10.10.5.100", "192.168.50.200",
]


# ─────────────────────────────────────────────────────────────────────────────
# ERROR TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

AUTH_ERRORS = [
    {
        "message": "JWT signature verification failed — token may be tampered",
        "level": "ERROR",
        "service": "auth-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"auth/jwt_handler.py\", line 67, in verify_token\n"
            "    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])\n"
            "  File \"jose/jwt.py\", line 133, in decode\n"
            "    decoded = self._load(token)\n"
            "jwt.exceptions.InvalidSignatureError: Signature verification failed"
        ),
        "endpoint": "POST /auth/verify",
    },
    {
        "message": "Authentication failed — invalid credentials for user",
        "level": "ERROR",
        "service": "auth-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"auth/auth_service.py\", line 42, in login_user\n"
            "    raise AuthenticationError('Invalid email or password')\n"
            "AuthenticationError: Invalid email or password"
        ),
        "endpoint": "POST /auth/login",
    },
    {
        "message": "Brute-force attempt detected — account temporarily locked",
        "level": "CRITICAL",
        "service": "auth-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"auth/rate_limiter.py\", line 88, in check_login_attempts\n"
            "    raise AccountLockedException(f'Account locked after {MAX_ATTEMPTS} failed attempts')\n"
            "AccountLockedException: Account locked after 5 failed attempts"
        ),
        "endpoint": "POST /auth/login",
    },
    {
        "message": "OAuth2 token exchange failed — authorization code expired",
        "level": "ERROR",
        "service": "auth-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"auth/oauth2.py\", line 115, in exchange_code\n"
            "    raise OAuthError('Authorization code has expired or already been used')\n"
            "OAuthError: Authorization code has expired or already been used"
        ),
        "endpoint": "POST /auth/oauth/callback",
    },
    {
        "message": "Permission denied — user lacks required role",
        "level": "ERROR",
        "service": "auth-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"auth/rbac.py\", line 54, in require_role\n"
            "    raise PermissionDenied(f'Role \"{required_role}\" required but user has \"{user_role}\"')\n"
            "PermissionDenied: Role \"admin\" required but user has \"viewer\""
        ),
        "endpoint": "DELETE /admin/users/{id}",
    },
    {
        "message": "Refresh token not found or already revoked",
        "level": "ERROR",
        "service": "auth-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"auth/token_store.py\", line 39, in validate_refresh_token\n"
            "    raise TokenRevokedException('Refresh token not found in store — may have been revoked')\n"
            "TokenRevokedException: Refresh token not found in store"
        ),
        "endpoint": "POST /auth/refresh",
    },
    {
        "message": "FATAL: Auth service secret key is None — cannot sign tokens",
        "level": "FATAL",
        "service": "auth-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"auth/jwt_handler.py\", line 22, in __init__\n"
            "    assert self.secret_key is not None, 'SECRET_KEY env var is not set'\n"
            "AssertionError: SECRET_KEY env var is not set"
        ),
        "endpoint": "POST /auth/login",
    },
]

DB_ERRORS = [
    {
        "message": "OperationalError: could not connect to server — Connection refused",
        "level": "CRITICAL",
        "service": "db-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"database/pool.py\", line 78, in get_connection\n"
            "    conn = psycopg2.connect(**DB_PARAMS)\n"
            "psycopg2.OperationalError: could not connect to server: Connection refused\n"
            "    Is the server running on host 'db-primary' and accepting TCP/IP connections on port 5432?"
        ),
        "query": "SELECT * FROM users WHERE id = ?",
    },
    {
        "message": "DeadlockDetected: transaction deadlock — retrying",
        "level": "ERROR",
        "service": "db-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"database/transactions.py\", line 103, in execute_transaction\n"
            "    raise DeadlockError('Deadlock detected between transactions T1 and T2')\n"
            "DeadlockError: Deadlock detected between transactions T1 and T2"
        ),
        "query": "UPDATE orders SET status='paid' WHERE id=?",
    },
    {
        "message": "IntegrityError: duplicate key value violates unique constraint",
        "level": "ERROR",
        "service": "db-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"database/user_repo.py\", line 45, in create_user\n"
            "    cursor.execute(INSERT_SQL, params)\n"
            "psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint \"users_email_key\"\n"
            "DETAIL: Key (email)=(alice@example.com) already exists."
        ),
        "query": "INSERT INTO users (email, name) VALUES (?, ?)",
    },
    {
        "message": "ConnectionPool exhausted — all 20 connections in use",
        "level": "CRITICAL",
        "service": "db-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"database/pool.py\", line 56, in acquire\n"
            "    raise PoolExhausted(f'All {MAX_POOL} connections are in use')\n"
            "PoolExhausted: All 20 connections are in use"
        ),
        "active_connections": 20,
        "max_connections": 20,
    },
    {
        "message": "QueryTimeout: query exceeded 30s limit",
        "level": "ERROR",
        "service": "db-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"database/executor.py\", line 88, in run_query\n"
            "    raise QueryTimeoutError(f'Query exceeded {TIMEOUT}s limit')\n"
            "QueryTimeoutError: Query exceeded 30s limit — consider adding an index"
        ),
        "query": "SELECT * FROM orders JOIN users ON ... WHERE created_at > ?",
        "duration_ms": 30001,
    },
]

PAYMENT_ERRORS = [
    {
        "message": "PaymentGatewayError: Stripe charge declined — insufficient funds",
        "level": "ERROR",
        "service": "payment-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"payments/stripe_client.py\", line 67, in charge_card\n"
            "    raise PaymentDeclined(f'Card declined: {stripe_error.code}')\n"
            "PaymentDeclined: Card declined: insufficient_funds"
        ),
        "stripe_error_code": "insufficient_funds",
        "amount_cents": random.randint(500, 50000),
    },
    {
        "message": "PaymentGatewayTimeout: no response from Stripe after 10s",
        "level": "CRITICAL",
        "service": "payment-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"payments/stripe_client.py\", line 43, in create_payment_intent\n"
            "    response = requests.post(STRIPE_URL, timeout=10, ...)\n"
            "requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='api.stripe.com', port=443): "
            "Read timed out. (read timeout=10)"
        ),
        "endpoint": "POST /orders/{id}/pay",
    },
    {
        "message": "InvalidCardError: card number fails Luhn check",
        "level": "ERROR",
        "service": "payment-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"payments/validator.py\", line 29, in validate_card\n"
            "    raise InvalidCardError('Card number failed Luhn algorithm check')\n"
            "InvalidCardError: Card number failed Luhn algorithm check"
        ),
        "endpoint": "POST /checkout",
    },
]

CACHE_ERRORS = [
    {
        "message": "RedisConnectionError: connection to Redis refused on port 6379",
        "level": "CRITICAL",
        "service": "cache-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"cache/redis_client.py\", line 33, in get\n"
            "    return self._client.get(key)\n"
            "redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379. Connection refused."
        ),
    },
    {
        "message": "CacheDeserializationError: failed to unpickle cached object",
        "level": "ERROR",
        "service": "cache-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"cache/serializer.py\", line 55, in deserialize\n"
            "    return pickle.loads(data)\n"
            "pickle.UnpicklingError: invalid load key, '<'"
        ),
        "cache_key": "user:session:abc123",
    },
]

API_ERRORS = [
    {
        "message": "UnhandledException: NoneType object has no attribute 'user_id'",
        "level": "ERROR",
        "service": "api-gateway",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"api/middleware.py\", line 88, in dispatch\n"
            "    user_id = request.user.user_id\n"
            "AttributeError: 'NoneType' object has no attribute 'user_id'"
        ),
        "endpoint": "GET /api/v1/profile",
    },
    {
        "message": "RateLimitExceeded: client exceeded 100 req/min",
        "level": "ERROR",
        "service": "api-gateway",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"api/rate_limiter.py\", line 61, in check_rate\n"
            "    raise RateLimitError(f'Client exceeded {LIMIT} requests per minute')\n"
            "RateLimitError: Client exceeded 100 requests per minute"
        ),
        "requests_in_window": 147,
        "limit": 100,
    },
    {
        "message": "SerializationError: circular reference detected in response object",
        "level": "ERROR",
        "service": "api-gateway",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"api/serializer.py\", line 102, in serialize_response\n"
            "    return json.dumps(obj)\n"
            "ValueError: Circular reference detected"
        ),
        "endpoint": "GET /orders/{id}",
    },
]

WORKER_ERRORS = [
    {
        "message": "WorkerCrashed: celery worker process unexpectedly terminated",
        "level": "FATAL",
        "service": "worker-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"workers/email_worker.py\", line 34, in send_email_task\n"
            "    result = smtp_client.send(msg)\n"
            "  File \"workers/smtp_client.py\", line 78, in send\n"
            "    raise SMTPServerDisconnected('Connection to SMTP server lost mid-send')\n"
            "smtplib.SMTPServerDisconnected: Connection to SMTP server lost"
        ),
        "task_id": str(uuid.uuid4()),
        "queue": "email_queue",
    },
    {
        "message": "MaxRetriesExceeded: task failed after 3 retries",
        "level": "ERROR",
        "service": "worker-service",
        "traceback": (
            "Traceback (most recent call last):\n"
            "  File \"workers/order_worker.py\", line 56, in process_order_task\n"
            "    raise MaxRetriesExceededError('Task failed after 3 retries')\n"
            "MaxRetriesExceededError: Task failed after 3 retries — sending to dead-letter queue"
        ),
        "task_id": str(uuid.uuid4()),
        "retries": 3,
        "queue": "order_processing",
    },
]

ALL_ERROR_POOLS = AUTH_ERRORS + DB_ERRORS + PAYMENT_ERRORS + CACHE_ERRORS + API_ERRORS + WORKER_ERRORS


# ─────────────────────────────────────────────────────────────────────────────
# INFO LOG GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_auth_info() -> dict:
    action = random.choice([
        "User login successful",
        "User logged out",
        "Password changed successfully",
        "New session token issued",
        "Two-factor authentication passed",
        "User registration completed",
        "Email verification link sent",
        "API key rotated successfully",
    ])
    uid = random.choice(USER_IDS)
    email = random.choice(EMAILS)
    return {
        "timestamp": _now_iso(),
        "level": "INFO",
        "service": "auth-service",
        "message": action,
        "user_id": uid,
        "email": email,
        "ip": random.choice(IP_ADDRESSES),
        "user_agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604",
            "PostmanRuntime/7.36.1",
            "python-requests/2.31.0",
        ]),
        "request_id": "req-" + uuid.uuid4().hex[:8],
    }


def make_api_info() -> dict:
    method = random.choice(["GET", "GET", "GET", "POST", "PUT", "DELETE"])
    if method == "GET":
        endpoint = random.choice(ENDPOINTS_GET).replace("{id}", str(random.randint(1, 500)))
    else:
        endpoint = random.choice(ENDPOINTS_POST).replace("{id}", str(random.randint(1, 500)))

    status = random.choices([200, 201, 204, 400, 401, 403, 404, 429], weights=[50, 10, 5, 8, 5, 3, 8, 3])[0]
    duration = random.randint(5, 800)

    return {
        "timestamp": _now_iso(),
        "level": "INFO",
        "service": "api-gateway",
        "message": f"{method} {endpoint} {status} OK" if status < 400 else f"{method} {endpoint} {status}",
        "method": method,
        "endpoint": endpoint,
        "status_code": status,
        "duration_ms": duration,
        "request_id": "req-" + uuid.uuid4().hex[:8],
        "user_id": random.choice(USER_IDS + [None]),
        "ip": random.choice(IP_ADDRESSES),
    }


def make_db_info() -> dict:
    op = random.choice(["SELECT", "INSERT", "UPDATE", "DELETE"])
    table = random.choice(["users", "orders", "products", "sessions", "payments", "audit_log"])
    duration = random.randint(1, 250)
    return {
        "timestamp": _now_iso(),
        "level": "INFO",
        "service": "db-service",
        "message": f"Query executed: {op} on {table} ({duration}ms)",
        "operation": op,
        "table": table,
        "duration_ms": duration,
        "rows_affected": random.randint(0, 50),
        "host": "db-primary" if op in ("INSERT", "UPDATE", "DELETE") else "db-replica",
    }


def make_payment_info() -> dict:
    action = random.choice([
        "Payment intent created",
        "Payment captured successfully",
        "Refund processed",
        "Subscription renewed",
        "Invoice generated",
        "Webhook received from Stripe",
    ])
    amount = random.randint(99, 99900)
    return {
        "timestamp": _now_iso(),
        "level": "INFO",
        "service": "payment-service",
        "message": action,
        "amount_cents": amount,
        "currency": random.choice(["USD", "EUR", "GBP", "INR"]),
        "order_id": random.choice(ORDER_IDS),
        "user_id": random.choice(USER_IDS),
        "request_id": "req-" + uuid.uuid4().hex[:8],
    }


def make_cache_info() -> dict:
    op = random.choice(["HIT", "MISS", "SET", "DEL", "EXPIRE"])
    key_type = random.choice(["user:session", "product:detail", "rate:limit", "cart:items", "config:flags"])
    kid = random.randint(1, 999)
    ttl = random.choice([60, 300, 900, 3600])
    return {
        "timestamp": _now_iso(),
        "level": "INFO",
        "service": "cache-service",
        "message": f"Cache {op}: {key_type}:{kid}",
        "operation": op,
        "key": f"{key_type}:{kid}",
        "ttl_seconds": ttl if op in ("SET", "EXPIRE") else None,
        "hit": op == "HIT",
    }


def make_worker_info() -> dict:
    task = random.choice([
        "send_welcome_email",
        "process_order",
        "generate_invoice_pdf",
        "sync_inventory",
        "send_push_notification",
        "cleanup_expired_sessions",
        "daily_report_generation",
    ])
    duration = random.randint(100, 8000)
    return {
        "timestamp": _now_iso(),
        "level": "INFO",
        "service": "worker-service",
        "message": f"Task completed: {task} ({duration}ms)",
        "task": task,
        "task_id": str(uuid.uuid4()),
        "duration_ms": duration,
        "queue": random.choice(["default", "email_queue", "order_processing", "reports"]),
        "worker": random.choice(["worker-01", "worker-02"]),
    }


def make_system_info() -> dict:
    event = random.choice([
        ("Server health check passed",       "api-gateway"),
        ("Deployment completed successfully","api-gateway"),
        ("Config reloaded from environment", "api-gateway"),
        ("SSL certificate renewed",          "api-gateway"),
        ("Scheduled backup completed",       "db-service"),
        ("Replica lag: 0ms (healthy)",       "db-service"),
        ("Disk usage: 42% (healthy)",        "worker-service"),
        ("Memory usage: 68% (healthy)",      "worker-service"),
        ("Index rebuild started",            "db-service"),
        ("Cache warm-up completed",          "cache-service"),
    ])
    return {
        "timestamp": _now_iso(),
        "level": "INFO",
        "service": event[1],
        "message": event[0],
        "host": random.choice(HOSTS),
        "uptime_seconds": random.randint(3600, 864000),
    }


INFO_GENERATORS = [
    make_auth_info,
    make_api_info,   make_api_info,   # weighted higher
    make_db_info,    make_db_info,
    make_payment_info,
    make_cache_info,
    make_worker_info,
    make_system_info,
]


# ─────────────────────────────────────────────────────────────────────────────
# ERROR LOG BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def make_error_log() -> dict:
    tmpl = random.choice(ALL_ERROR_POOLS).copy()
    tmpl["timestamp"] = _now_iso()
    tmpl["request_id"] = "req-" + uuid.uuid4().hex[:8]
    tmpl["user_id"] = random.choice(USER_IDS)
    tmpl["host"] = random.choice(HOSTS)
    # Resolve dynamic fields
    if "amount_cents" in tmpl and callable(tmpl["amount_cents"]):
        tmpl["amount_cents"] = tmpl["amount_cents"]()
    if "endpoint" in tmpl:
        tmpl["endpoint"] = tmpl["endpoint"].replace("{id}", str(random.randint(1, 500)))
    return tmpl


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GENERATOR LOOP
# ─────────────────────────────────────────────────────────────────────────────

def generate_line(error_rate: float = 0.15) -> str:
    """Generate one JSON log line. error_rate controls fraction of ERROR lines."""
    if random.random() < error_rate:
        entry = make_error_log()
    else:
        entry = random.choice(INFO_GENERATORS)()
    return json.dumps(entry, ensure_ascii=False)


def stream_logs(
    output_path: str | None,
    interval: float,
    count: int | None,
    error_rate: float,
    stdout: bool,
) -> None:
    if output_path:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

    generated = 0
    print(f"[fake_log_generator] Starting — output={'stdout' if stdout else output_path}  "
          f"interval={interval}s  count={'∞' if count is None else count}  "
          f"error_rate={error_rate:.0%}", file=sys.stderr)

    try:
        while count is None or generated < count:
            line = generate_line(error_rate)

            if stdout:
                print(line, flush=True)
            if output_path:
                with open(output_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")

            generated += 1

            if count is not None:
                # Batch mode: no sleep
                if generated % 50 == 0:
                    print(f"[fake_log_generator] {generated}/{count} lines written", file=sys.stderr)
            else:
                # Stream mode: wait
                time.sleep(interval)

    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n[fake_log_generator] Done — {generated} lines written.", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate fake JSON logs for the Debug Pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Live stream — 1 log per second, ~15%% errors, into a file:
  python log_generator/fake_log_generator.py --output test_logs/live.log

  # Faster stream (0.5 s gap) with higher error rate:
  python log_generator/fake_log_generator.py --output test_logs/live.log --interval 0.5 --error-rate 0.3

  # Static batch of 300 lines and exit:
  python log_generator/fake_log_generator.py --output test_logs/batch.log --count 300

  # Print to stdout (pipe to another tool):
  python log_generator/fake_log_generator.py --stdout --count 50
        """,
    )
    parser.add_argument(
        "--output", "-o",
        metavar="PATH",
        help="Path to the output log file (will be APPENDED to if it exists).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print each line to stdout.",
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Seconds between log lines in live mode (default: 1.0).",
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=None,
        metavar="N",
        help="Generate exactly N lines then exit (omit for continuous stream).",
    )
    parser.add_argument(
        "--error-rate", "-e",
        type=float,
        default=0.15,
        metavar="RATE",
        help="Fraction of lines that are ERROR/CRITICAL/FATAL (0.0–1.0, default: 0.15).",
    )

    args = parser.parse_args()

    if not args.output and not args.stdout:
        # Default: write to test_logs/live.log
        args.output = "test_logs/live.log"
        print(f"[fake_log_generator] No --output given, defaulting to {args.output}", file=sys.stderr)

    stream_logs(
        output_path=args.output,
        interval=args.interval,
        count=args.count,
        error_rate=args.error_rate,
        stdout=args.stdout,
    )


if __name__ == "__main__":
    main()
