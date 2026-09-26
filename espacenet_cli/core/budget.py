"""Persistent search budget: a token bucket + penalty box for Espacenet searches.

Calibrated against measured service behaviour (see RATELIMIT.md in the repo):
  - search tokens: burst capacity ~20 observed; we allow 12 (safety margin)
  - refill: official fair-use line is 10 searches/min -> 1 token / 7s
  - penalty: measured recovery 5m18s / 6m03s -> we hold 400s (6m40s)
Document endpoints (family/legal/fulltext/pdf) measured unthrottled and do NOT
consume budget.

State lives in the profile directory so every CLI invocation shares the same
budget. Writes are lock-protected; the bucket itself is best-effort across
processes (small races are acceptable for a single-user CLI).
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from espacenet_cli.core.errors import CliError
from espacenet_cli.core.session import locked_save_json, read_json_or_none

CAPACITY = 12.0
REFILL_SECONDS = 7.0
PENALTY_SECONDS = 400.0
LOCK_TIMEOUT_S = 10.0


class _FileLock:
    """Tiny O_EXCL spin lock for read-modify-write of the state file."""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode())
                return self
            except FileExistsError:
                try:
                    stale = time.time() - self.path.stat().st_mtime > 30
                except OSError:
                    stale = False
                if stale:
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() - t0 > LOCK_TIMEOUT_S:
                    # Fail open: unprotected write is better than blocking the CLI.
                    self.fd = None
                    return self
                time.sleep(0.1)

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            try:
                self.path.unlink()
            except OSError:
                pass


class SearchBudget:
    """Token bucket for search requests, shared across CLI invocations."""

    def __init__(self, state_path, capacity=CAPACITY, refill_seconds=REFILL_SECONDS,
                 penalty_seconds=PENALTY_SECONDS, clock=time.time, enabled=True):
        self.state_path = Path(state_path)
        self.capacity = float(capacity)
        self.refill_seconds = float(refill_seconds)
        self.penalty_seconds = float(penalty_seconds)
        self.clock = clock  # injectable for tests
        self.enabled = enabled
        self.state = self._load()

    # ---------------------------------------------------------------- state

    def _load(self):
        raw = read_json_or_none(self.state_path) or {}
        return {
            "tokens": min(self.capacity, float(raw.get("tokens", self.capacity))),
            "updated_at": float(raw.get("updated_at", self.clock())),
            "penalty_until": float(raw.get("penalty_until", 0)),
        }

    def _save(self):
        locked_save_json(self.state_path, {**self.state, "version": 1})

    def _refill(self):
        now = self.clock()
        elapsed = max(0.0, now - self.state["updated_at"])
        self.state["tokens"] = min(self.capacity, self.state["tokens"] + elapsed / self.refill_seconds)
        self.state["updated_at"] = now

    # ---------------------------------------------------------------- query

    def penalty_remaining(self):
        return max(0.0, self.state["penalty_until"] - self.clock())

    def seconds_until_token(self):
        if self.enabled and self.penalty_remaining() > 0:
            return self.penalty_remaining()
        self._refill()
        deficit = max(0.0, 1.0 - self.state["tokens"])
        return deficit * self.refill_seconds

    def snapshot(self):
        wait = self.seconds_until_token()
        remaining = self.penalty_remaining()
        return {
            "enabled": self.enabled,
            "tokens": round(min(self.capacity, self.state["tokens"]), 2),
            "capacity": self.capacity,
            "refillSeconds": self.refill_seconds,
            "penaltyRemainingS": round(remaining, 1),
            "nextTokenInS": round(wait, 1),
            "penaltyUntil": (datetime.fromtimestamp(self.clock() + remaining).strftime("%H:%M:%S")
                             if remaining > 0 else None),
        }

    # ---------------------------------------------------------------- mutate

    def acquire(self, wait=False, on_wait=None, wait_budget_s=900.0):
        """Consume one search token.

        wait=False: raise SEARCH_BUDGET immediately when unavailable.
        wait=True: sleep (reporting progress via on_wait) until a token exists,
        bounded by wait_budget_s to keep unattended jobs from hanging forever.
        """
        if not self.enabled:
            return
        while True:
            with _FileLock(self.state_path.with_suffix(".lock")):
                self.state = self._load()
                self._refill()
                if self.penalty_remaining() <= 0 and self.state["tokens"] >= 1.0:
                    self.state["tokens"] -= 1.0
                    self._save()
                    return
            wait_s = self.seconds_until_token()
            if not wait:
                raise CliError(
                    "SEARCH_BUDGET",
                    f"检索配额不足（剩 {self.state['tokens']:.1f}/{self.capacity:.0f} 次），"
                    f"约 {int(wait_s + 0.9)} 秒后恢复 1 次。",
                    action="稍后重试；无人值守任务加 --await-budget 自动排队；"
                           "批量拉取用 --all --limit 200 分批。",
                )
            if wait_s > wait_budget_s:
                raise CliError("SEARCH_BUDGET",
                               f"等待预算耗尽（还需 {int(wait_s)}s）。",
                               action="稍后重新运行；或减小任务规模。")
            if on_wait:
                on_wait(f"检索配额等待中，{int(wait_s + 0.9)}s 后继续…")
            time.sleep(min(max(wait_s, 0.5), 30.0))

    def observe_rejection(self):
        """A real 429/403 from the service: start/extend the penalty box."""
        with _FileLock(self.state_path.with_suffix(".lock")):
            self.state = self._load()
            self.state["tokens"] = 0.0
            self.state["updated_at"] = self.clock()
            base = max(self.state["penalty_until"], self.clock())
            self.state["penalty_until"] = base + self.penalty_seconds
            self._save()
