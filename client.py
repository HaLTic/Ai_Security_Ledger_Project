"""Small role-scoped Ledger transport. Proposals are never blindly retried."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import random
import time

import requests

from config import strict_json

READS = {
    "market_prices.php", "market_news.php", "portfolio.php", "policies.php",
    "transactions.php", "guardian_logs.php", "theory.php", "market_model.php",
}
WRITES = {"trader": "trade_propose.php", "guardian": "trade_review.php"}


class ApiError(RuntimeError):
    def __init__(self, status, code):
        # Do not include server bodies, headers, URLs or credentials in errors.
        self.status = status
        self.code = code if isinstance(code, str) and code.replace("_", "").isalnum() else "api_error"
        super().__init__(f"Ledger HTTP {status}: {self.code}")


class Cooldown(RuntimeError):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__("Ledger cooldown; leave work pending")


class UncertainWrite(RuntimeError):
    pass


class SessionExpired(RuntimeError):
    pass


class LedgerClient:
    def __init__(self, base, key, role, *, deadline=None):
        if base.rstrip("/") != "https://ledger.chanyeun.com/api/v1":
            raise ValueError("Use the canonical Ledger HTTPS API base URL")
        if role not in WRITES or not key.strip() or key.startswith("PASTE_"):
            raise ValueError("Configure a valid role and complete role key")
        self.base, self.key, self.role = base.rstrip("/"), key.strip(), role
        self.session = requests.Session()
        self.next_allowed = self.next_request_at = 0.0
        self.deadline = deadline

    def remaining(self):
        remaining = self.deadline - time.monotonic() if self.deadline else 600.0
        if remaining <= 0.1:
            raise SessionExpired("Session time limit reached")
        return remaining

    def pause(self, seconds):
        if seconds >= self.remaining():
            raise SessionExpired("Session time limit reached")
        time.sleep(max(0, seconds))

    def get(self, endpoint, **params):
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint, body):
        return self.request("POST", endpoint, body=body)

    def request(self, method, endpoint, *, params=None, body=None):
        allowed = READS | ({"trade_pending.php"} if self.role == "guardian" else set())
        if not ((method == "GET" and endpoint in allowed)
                or (method == "POST" and endpoint == WRITES[self.role])):
            raise ValueError("Endpoint or method is not permitted for this role")
        if self.next_allowed > time.monotonic():
            raise Cooldown(self.next_allowed - time.monotonic())
        headers = {"X-Api-Key": self.key}
        data = None
        if method == "POST":
            if not isinstance(body, dict):
                raise ValueError("POST body must be a JSON object")
            data = json.dumps(body, allow_nan=False).encode("utf-8")
            if len(data) > 32768:
                raise ValueError("POST exceeds 32 KiB")
            headers["Content-Type"] = "application/json"
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            self.pause(max(0, self.next_request_at - time.monotonic()))
            self.next_request_at = time.monotonic() + 1.1
            remaining = self.remaining()
            try:
                response = self.session.request(
                    method, f"{self.base}/{endpoint}", headers=headers,
                    params=params, data=data, timeout=(min(5, remaining / 2), min(15, remaining / 2)),
                    allow_redirects=False,
                )
            except requests.RequestException:
                if method == "POST":
                    raise UncertainWrite("Write response lost; reconcile before another write") from None
                if attempt + 1 == attempts:
                    raise ApiError(0, "read_failed") from None
                self.pause(2 ** attempt + random.uniform(0, 1))
                continue
            status = response.status_code
            if status in {429, 503}:
                retry = response.headers.get("Retry-After", "15")
                try:
                    seconds = float(retry)
                    if not 0 <= seconds < 86400:
                        seconds = 15
                except ValueError:
                    try:
                        seconds = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        seconds = 15
                self.next_allowed = time.monotonic() + max(1, seconds) + random.uniform(0, 2)
                if method == "POST" and status == 503:
                    raise UncertainWrite("Write uncertain during service outage; wait and reconcile")
                raise Cooldown(self.next_allowed - time.monotonic())
            if 300 <= status < 400:
                raise ApiError(status, "redirect_refused")
            if method == "POST" and status >= 500:
                raise UncertainWrite("Server error; reconcile before another write")
            if method == "GET" and status >= 500 and attempt + 1 < attempts:
                self.pause(2 ** attempt + random.uniform(0, 1))
                continue
            try:
                result = strict_json(response.text)
                if not isinstance(result, dict):
                    raise ValueError("Expected object")
            except (ValueError, TypeError):
                if method == "POST" and 200 <= status < 300:
                    raise UncertainWrite("Write returned unreadable result") from None
                raise ApiError(status, "expected_json_check_base_url_or_hosting") from None
            if not 200 <= status < 300:
                raise ApiError(status, result.get("error", "api_error"))
            return result
