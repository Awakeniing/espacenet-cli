"""Espacenet real backend.

The "real software" for this harness is a persistent Microsoft Edge session
plus Espacenet's own frontend REST services. This module owns that backend:

1. spawn/attach a dedicated-profile Edge with CDP (hard dependency, like
   Blender for bpy) and share it across CLI invocations via an endpoint file;
2. run requests *inside the Espacenet page context* through an in-page fetch
   bridge (Cloudflare rejects CDP-issued bare requests);
3. solve Cloudflare Turnstile challenges with humanized mouse motion;
4. pace requests (EPO Fair Use) and retry fair-use/challenge responses.

Ported from the prior Node.js implementation's validated transport
(session handling, challenge solving, HTTP client), restructured as a
standalone CLI backend.
"""

import base64
import json
import math
import os
import random
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from espacenet_cli.core.config import (
    CDP_HOST,
    ESPACENET_ORIGIN,
    find_edge,
    get_profile_paths,
    read_endpoint_file,
)
from espacenet_cli.core.errors import CliError

ENDPOINT_PROBE_TIMEOUT_S = 1.2
LAUNCH_TIMEOUT_S = 45.0
CHALLENGE_TITLE_RE = re.compile(r"just\s+a\s+moment|请稍候|attention\s+required|access\s+denied", re.I)

SEARCH_FIELDS = [
    "publications.ti_*",
    "publications.abs_*",
    "publications.pn_docdb",
    "publications.pd",
    "publications.in_patents",
    "publications.inc_patents",
    "publications.pa_patents",
    "publications.pac_patents",
    "publications.pr_docdb",
    "publications.app_fdate.untouched",
    "oprid_full.untouched",
    "opubd_full.untouched",
    "publications.ipc_ic",
    "publications.ipc_icci",
    "publications.ipc_iccn",
    "publications.ipc_icai",
    "publications.ipc_ican",
    "publications.ci_cpci",
    "publications.ca_cpci",
    "publications.cl_cpci",
    "biblio:pa;in;in_patents;pa_patents;inc_patents;pac_patents;in_orig_patents;pa_orig_patents;in_unstd_patents;pa_unstd_patents;pd;pn_docdb;allKindCodes;",
]

# Runs inside the Espacenet page: same-origin fetch with abort timeout,
# binary payloads returned base64-encoded (JSON-serializable over CDP).
FETCH_BRIDGE_JS = """
async ({url, options}) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs || 120000);
  try {
    const resp = await fetch(url, {
      method: options.method || 'GET',
      headers: options.headers || {},
      body: options.body === undefined || options.body === null ? undefined : options.body,
      signal: controller.signal,
    });
    const headers = {};
    resp.headers.forEach((v, k) => { headers[k.toLowerCase()] = v; });
    if (options.binary) {
      const buf = await resp.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = '';
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
      }
      return { status: resp.status, headers, base64: btoa(binary) };
    }
    const text = await resp.text();
    return { status: resp.status, headers, text };
  } finally {
    clearTimeout(timer);
  }
}
"""

CHALLENGE_MARKER_JS = """
() => {
  const text = document.body ? String(document.body.innerText || '').slice(0, 2000) : '';
  return Boolean(
    document.querySelector("#challenge-form, #challenge-stage, [class*='challenge']") ||
    /正在进行安全验证| verifying you are human|attention required/i.test(text)
  );
}
"""


def make_trace_id():
    seg = lambda n: "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(n))
    return f"{seg(6)}-{seg(6)}-AAA-{random.randrange(10**6):06d}"


def probe_endpoint(port, timeout_s=ENDPOINT_PROBE_TIMEOUT_S):
    try:
        with urllib.request.urlopen(f"http://{CDP_HOST}:{port}/json/version", timeout=timeout_s) as resp:
            return resp.status == 200
    except OSError:
        return False


def is_pid_alive(pid):
    if not isinstance(pid, int) or pid < 1:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
            return str(pid) in out
        except OSError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((CDP_HOST, 0))
        return s.getsockname()[1]


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def build_edge_launch_args(profile_dir, port, mode="visible"):
    if not profile_dir:
        raise CliError("INVALID_ARGUMENT", "Edge launch requires a dedicated profile directory.")
    args = [
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-address={CDP_HOST}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
        "--disable-features=msSmartScreenPatch",
    ]
    if mode == "background":
        args += ["--headless=new", "--window-size=1600,1000"]
    else:
        args.append("--start-maximized")
    return args


def acquire_launch_lock(lock_file, stale_s=90.0, wait_s=30.0):
    lock_file = Path(lock_file)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    while True:
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                current = json.loads(lock_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = None
            if (not current or time.time() - float(current.get("ts") or 0) > stale_s
                    or not is_pid_alive(int(current.get("pid") or 0))):
                try:
                    lock_file.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() - t0 > wait_s:
                raise CliError("LOCK_BUSY", f"Another espacenet CLI process holds {lock_file}.",
                               action="Retry in a moment, or run `espacenet edge stop`.")
            time.sleep(0.25)


def release_launch_lock(lock_file):
    try:
        Path(lock_file).unlink()
    except OSError:
        pass


def page_is_challenge(page):
    try:
        if CHALLENGE_TITLE_RE.search(page.title() or ""):
            return True
        return bool(page.evaluate(CHALLENGE_MARKER_JS))
    except Exception:
        return False


def _find_turnstile_target(page):
    for frame in page.frames:
        if "challenges.cloudflare.com" not in (frame.url or ""):
            continue
        for selector in ("input[type='checkbox']", "label.ctp-checkbox-label", "body"):
            el = None
            try:
                el = frame.query_selector(selector)
            except Exception:
                el = None
            if not el:
                continue
            try:
                box = el.bounding_box()
            except Exception:
                box = None
            if box and box["width"] > 5 and box["height"] > 5:
                return {
                    "x": box["x"] + 15 + random.random() * 4,
                    "y": box["y"] + box["height"] / 2 + (random.random() - 0.5) * 3,
                }
    return None


def _human_click(page, target):
    """Humanized trajectory: eased segmented move → hover → press/release."""
    start = {
        "x": max(2.0, target["x"] - 90 - random.random() * 60),
        "y": max(2.0, target["y"] + 40 + random.random() * 30),
    }
    page.mouse.move(start["x"], start["y"])
    steps = 14 + random.randint(0, 8)
    for i in range(1, steps + 1):
        t = i / steps
        ease = 0.5 - 0.5 * math.cos(math.pi * t)
        jitter_x = (random.random() - 0.5) * 2.2 * (1 - t)
        jitter_y = (random.random() - 0.5) * 2.2 * (1 - t)
        page.mouse.move(
            start["x"] + (target["x"] - start["x"]) * ease + jitter_x,
            start["y"] + (target["y"] - start["y"]) * ease + jitter_y,
        )
        page.wait_for_timeout(8 + random.random() * 22)
    page.wait_for_timeout(350 + random.random() * 650)
    page.mouse.down()
    page.wait_for_timeout(60 + random.random() * 90)
    page.mouse.up()


def auto_solve_challenge(page, on_event=lambda m: None, max_clicks=4, click_gap_ms=9000, overall_ms=150000):
    t0 = time.monotonic()
    clicks = 0
    while (time.monotonic() - t0) * 1000 < overall_ms:
        target = _find_turnstile_target(page)
        if target:
            on_event("检测到人机验证控件，正在自动点击…" if clicks == 0 else "再次尝试点击验证控件…")
            _human_click(page, target)
            clicks += 1
            waited = 0
            while waited < click_gap_ms:
                page.wait_for_timeout(1000)
                waited += 1000
                if not page_is_challenge(page):
                    return True
            if clicks >= max_clicks:
                while (time.monotonic() - t0) * 1000 < overall_ms:
                    page.wait_for_timeout(2000)
                    if not page_is_challenge(page):
                        return True
                return False
        else:
            page.wait_for_timeout(1200)
            if not page_is_challenge(page):
                return True
            if (time.monotonic() - t0) * 1000 > overall_ms:
                return False
    return not page_is_challenge(page)


def goto_cleared(page, url, tries=3, settle_ms=4000, on_event=lambda m: None, timeout_ms=45000, wait_ms=150000):
    """Navigate and make sure the Cloudflare challenge is cleared on this page."""
    last_status = None
    for attempt in range(1, tries + 1):
        status = None
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            status = response.status if response else None
        except Exception as error:  # navigation retries are expected under challenge
            on_event(f"导航重试 {attempt}: {str(error)[:90]}")
        last_status = status
        page.wait_for_timeout(2500)
        if page_is_challenge(page):
            if auto_solve_challenge(page, on_event=on_event, overall_ms=wait_ms):
                page.wait_for_timeout(settle_ms)
                return {"ok": True, "status": 200}
            on_event("自动通过验证未成功，重试导航…")
            continue
        if status and status < 400:
            page.wait_for_timeout(settle_ms)
            return {"ok": True, "status": status}
        if not status and not page_is_challenge(page):
            page.wait_for_timeout(settle_ms)
            return {"ok": True, "status": None}
    return {"ok": False, "status": last_status}


class EspacenetBackend:
    """Handle to the shared real Edge + Espacenet page. Sync API."""

    def __init__(self, paths, mode="visible", pacing_ms=700, on_event=lambda m: None,
                 await_budget=False, budget_enabled=True):
        self.paths = paths
        self.mode = mode
        self.pacing_ms = max(0, int(pacing_ms or 0))
        self.on_event = on_event
        self.endpoint = None
        self.reused = False
        self.await_budget = await_budget
        from espacenet_cli.core.budget import SearchBudget

        self.budget = SearchBudget(
            Path(paths["profile_root"]) / "search-budget.json",
            enabled=budget_enabled)
        self._pw = None
        self._browser = None
        self._page = None
        self._last_request_at = 0.0
        self._resolution_cache = {}

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(cls, profile="default", mode="visible", pacing_ms=700, on_event=lambda m: None,
               env=None, await_budget=False, budget_enabled=True):
        paths = get_profile_paths(profile, env=env)
        backend = cls(paths, mode=mode, pacing_ms=pacing_ms, on_event=on_event,
                      await_budget=await_budget, budget_enabled=budget_enabled)
        backend._ensure_edge_session()
        return backend

    def _connect_cdp(self, endpoint):
        try:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.connect_over_cdp(
                f"http://{CDP_HOST}:{endpoint['port']}", timeout=15000)
        except CliError:
            raise
        except Exception as error:
            raise CliError(
                "EDGE_CONNECT_FAILED",
                f"Cannot attach to shared Edge on port {endpoint['port']}: {error}",
                action="Run `espacenet edge stop` and retry.",
            )

    def _ensure_edge_session(self):
        existing = read_endpoint_file(self.paths["edge_endpoint_file"])
        if existing and probe_endpoint(existing["port"]):
            self.endpoint = existing
            self.reused = True
            self._connect_cdp(existing)
            return
        if existing:
            try:
                Path(self.paths["edge_endpoint_file"]).unlink()
            except OSError:
                pass
            if existing["pid"] and is_pid_alive(existing["pid"]) and os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(existing["pid"]), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(0.8)

        acquire_launch_lock(self.paths["launch_lock_file"])
        try:
            again = read_endpoint_file(self.paths["edge_endpoint_file"])
            if again and probe_endpoint(again["port"]):
                self.endpoint = again
                self.reused = True
                self._connect_cdp(again)
                return
            self.on_event("正在启动 Microsoft Edge…" if self.mode != "background" else "正在后台启动 Microsoft Edge…")
            executable = find_edge(env=os.environ)
            port = find_free_port()
            self.paths["browser_profile_dir"].mkdir(parents=True, exist_ok=True)
            args = build_edge_launch_args(str(self.paths["browser_profile_dir"]), port, self.mode)
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            child = subprocess.Popen(
                [executable, *args],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=flags, close_fds=True,
            )
            t0 = time.monotonic()
            while True:
                if probe_endpoint(port, 0.8):
                    break
                if time.monotonic() - t0 > LAUNCH_TIMEOUT_S:
                    raise CliError("EDGE_LAUNCH_TIMEOUT", "Edge did not expose its debugging port in time.",
                                   action="Run `espacenet edge stop`, then retry.")
                time.sleep(0.3)
            self.endpoint = {
                "host": CDP_HOST, "port": port, "pid": child.pid,
                "profile_dir": str(self.paths["browser_profile_dir"]),
                "mode": self.mode, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            atomic_write_json(self.paths["edge_endpoint_file"], {
                "version": 1, **self.endpoint,
            })
            self._connect_cdp(self.endpoint)
        finally:
            release_launch_lock(self.paths["launch_lock_file"])

    def close(self):
        # Shared Edge stays resident; only the CDP attach is torn down.
        for closer in (getattr(self, "_browser", None), getattr(self, "_pw", None)):
            try:
                if closer:
                    closer.close() if closer is self._browser else closer.stop()
            except Exception:
                pass
        self._browser = None
        self._pw = None

    # -- page management ---------------------------------------------------

    def ensure_page(self):
        if self._page and not self._page.is_closed():
            return self._page
        context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        candidates = [p for p in context.pages if not p.is_closed() and re.search(r"espacenet\.com", p.url, re.I)]
        self._page = candidates[0] if candidates else context.new_page()
        self._page.set_default_timeout(60000)  # never block a CLI run indefinitely
        return self._page

    def ensure_on_espacenet(self, force_reload=False):
        page = self.ensure_page()
        url = page.url or ""
        on_origin = bool(re.match(r"^https?://worldwide\.espacenet\.com", url, re.I))
        target = url if (on_origin and "/3.2/" not in url) else f"{ESPACENET_ORIGIN}/patent/search"
        if on_origin and not force_reload and not page_is_challenge(page):
            return page
        self.on_event("打开 Espacenet 页面…")
        result = goto_cleared(page, target, on_event=self.on_event)
        if not result["ok"]:
            raise CliError(
                "CHALLENGE_BLOCKED",
                f"无法通过 Cloudflare 人机验证（最后状态 {result['status'] if result['status'] is not None else 'unknown'}）。",
                action="在弹出的 Edge 窗口中手动完成一次人机验证（点击复选框），然后重试；或改用 --edge-mode visible。",
            )
        return page

    # -- transport ---------------------------------------------------------

    def fetch(self, path_or_url, method="GET", body=None, headers=None, binary=False, _retried=False):
        now = time.monotonic()
        wait = self._last_request_at + self.pacing_ms / 1000 - now
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

        page = self.ensure_on_espacenet()
        url = path_or_url if re.match(r"^https?:", path_or_url, re.I) else f"{ESPACENET_ORIGIN}{path_or_url}"
        payload = {
            "url": url,
            "options": {
                "method": method,
                "headers": {
                    "accept": "application/json,application/i18n+xml",
                    "epo-trace-id": make_trace_id(),
                    "x-epo-client": "NES",
                    "x-epo-pql-profile": "cpci",
                    **(headers or {}),
                },
                "body": body,
                "binary": binary,
            },
        }
        try:
            response = page.evaluate(FETCH_BRIDGE_JS, payload)
        except Exception as error:
            raise CliError("FETCH_FAILED", f"页面内请求失败: {str(error)[:200]}",
                           action="检查 Edge 窗口是否仍打开在 Espacenet 页面；必要时重新 connect。")
        if binary and response.get("base64") is not None:
            response["bytes"] = base64.b64decode(response.pop("base64"))

        ct = (response.get("headers") or {}).get("content-type", "")
        if response.get("status") == 403 and re.search(r"text/html", ct, re.I) and not _retried:
            # Mid-session token loss: drop cf cookies, force re-verify, retry once.
            self.on_event("请求遇到人机验证，正在重新获取验证令牌…")
            try:
                context = self._browser.contexts[0]
                for name in ("__cf_bm", "cf_clearance"):
                    context.clear_cookies(name=name)
            except Exception:
                pass
            self._last_request_at = time.monotonic() + 2.0
            self.ensure_on_espacenet(force_reload=True)
            return self.fetch(path_or_url, method, body, headers, binary, _retried=True)
        return response

    def fetch_json(self, path_or_url, method="GET", body=None, headers=None, _fair_use_retried=0):
        response = self.fetch(path_or_url, method, body, headers)
        try:
            parsed = json.loads(response.get("text") or "null")
        except ValueError:
            parsed = None
        if response.get("status") == 429:
            # Real service throttle: record the penalty so every CLI invocation
            # backs off (measured recovery ~5-6 min), then fail fast. Blind
            # retries only extend Cloudflare's penalty and can escalate the
            # whole page into an interactive challenge.
            self.budget.observe_rejection()
            resume = self.budget.snapshot().get("penaltyUntil")
            raise CliError(
                "FAIR_USE_REJECTED",
                f"Espacenet 限流（429）。检索预算已冻结，约 {resume or '6-7 分钟后'} 恢复。",
                action="期间勿重试（会延长处罚）；文献类命令（claims/family/legal/pdf）不受影响。",
            )
        if response.get("status") == 403:
            ct = (response.get("headers") or {}).get("content-type", "")
            head = (response.get("text") or "")[:300]
            if re.search(r"text/html", ct, re.I):
                raise CliError("CHALLENGE_BLOCKED", "Espacenet 接口返回人机验证页（自动恢复失败）。",
                               action="运行 `espacenet connect` 并在 Edge 窗口中手动完成一次验证后重试。")
            if re.search(r"<error>", head, re.I) and not _fair_use_retried:
                self.on_event("触发 Fair Use 限流，5 秒后重试一次…")
                time.sleep(5)
                self._last_request_at = time.monotonic()
                return self.fetch_json(path_or_url, method, body, headers, _fair_use_retried=max(int(_fair_use_retried), 2))
            if re.search(r"<error>", head, re.I):
                self.budget.observe_rejection()
                m = re.search(r"<message>([^<]*)</message>", head)
                message = (m.group(1) if m else "Fair Use policy").strip()
                resume = self.budget.snapshot().get("penaltyUntil")
                raise CliError("FAIR_USE_REJECTED",
                               f"Espacenet 拒绝请求（Fair Use）: {message}。预算冻结至 {resume or '6-7 分钟后'}。",
                               action="期间勿重试；大批量任务分批（--all --limit 200）并批间歇几分钟。")
            raise CliError("API_ERROR", f"Espacenet 接口返回 403: {path_or_url} — {head[:150]}")
        return {"status": response.get("status"), "json": parsed, "text": response.get("text", ""),
                "headers": response.get("headers") or {}}

    # -- Espacenet SPA search protocol --------------------------------------

    def search_raw(self, query, from_=0, size=20):
        from urllib.parse import quote

        self.budget.acquire(wait=self.await_budget, on_wait=self.on_event)
        q = quote(query, safe="")
        body = {
            "query": {"fields": SEARCH_FIELDS, "from": from_, "size": size},
            "filters": {"publications.patent": [{"value": ["true"]}]},
            "widgets": {},
        }
        path = f"/3.2/rest-services/search?lang=en%2Cde%2Cfr&q={q}&qlang=cql&"
        response = self.fetch_json(path, method="POST", body=json.dumps(body),
                                   headers={"Content-Type": "application/json"})
        parsed = response["json"]
        if parsed is None:
            raise CliError("API_ERROR", f"检索响应无法解析为 JSON（HTTP {response['status']}）。")
        if parsed.get("error") or parsed.get("fault"):
            raise CliError(
                "QUERY_ERROR",
                f"Espacenet 拒绝了检索式: {json.dumps(parsed.get('error') or parsed.get('fault'))[:300]}",
                action="检查检索式语法（ti=、pa=、pn= 等字段代码，大小写不敏感）。",
            )
        return parsed
