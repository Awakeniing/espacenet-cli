"""E2E tests: real Espacenet backend (Edge + network, no graceful degradation)
and installed-command subprocess tests via _resolve_cli()."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from espacenet_cli.core.document import run_claims, run_detail, run_family, run_legal
from espacenet_cli.core.pdf import run_pdf
from espacenet_cli.core.search import run_search
from espacenet_cli.utils.edge_backend import EspacenetBackend


def _resolve_cli(name):
    """Resolve installed CLI command; falls back to python -m for dev.

    Set env ESPACENET_CLI_FORCE_INSTALLED=1 to require the installed command.
    """
    force = os.environ.get("ESPACENET_CLI_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m espacenet_cli")
    return [sys.executable, "-m", "espacenet_cli"]


class TestCLISubprocess:
    CLI_BASE = _resolve_cli("espacenet")

    def _run(self, args, check=True, cwd=None, timeout=300):
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True, text=True, check=check, cwd=cwd, timeout=timeout,
            encoding="utf-8", errors="replace",
        )

    def test_help(self):
        result = self._run(["--help"])
        assert result.returncode == 0
        assert "search" in result.stdout and "REPL" in result.stdout

    def test_version(self):
        result = self._run(["--version"])
        assert result.returncode == 0 and "espacenet" in result.stdout

    def test_status_json(self):
        result = self._run(["status", "--json"])
        data = json.loads(result.stdout)
        assert "profile" in data and "profileRoot" in data

    def test_doctor(self):
        result = self._run(["doctor"])
        data = json.loads(result.stdout)
        assert "edgeExecutable" in data

    def test_journal_workflow_no_network(self, tmp_path):
        cwd = tmp_path / "work"
        cwd.mkdir()
        self._run(["session", "start", "机械结构 tandem 检索", "--goal", "布局摸底"], cwd=str(cwd))
        self._run(["note", "中文词命中不全，改用英文", "--kind", "调整"], cwd=str(cwd))
        listing = json.loads(self._run(["session", "list", "--json"], cwd=str(cwd)).stdout)
        assert len(listing) == 1 and listing[0]["active"] is True
        self._run(["session", "end"], cwd=str(cwd))
        report_out = self._run(["report", "-o", str(cwd / "report.md")], cwd=str(cwd))
        report_path = Path(cwd / "report.md")
        assert report_path.exists() and report_path.stat().st_size > 500
        content = report_path.read_text(encoding="utf-8")
        assert "## 一、检索任务与背景" in content
        assert "## 附录：复现命令" in content
        print(f"\n  report: {report_path} ({report_path.stat().st_size:,} bytes)")

    def test_dry_run_does_not_write(self, tmp_path):
        cwd = tmp_path / "work"
        cwd.mkdir()
        self._run(["note", "不该落盘", "--dry-run"], cwd=str(cwd), check=False)
        # note without an active session fails; nothing must be written either way
        journal = cwd / "espacenet-journal"
        if journal.exists():
            for path in journal.rglob("*"):
                assert path.name != "journal.ndjson"
        self._run(["session", "start", "DRY", "--dry-run"], cwd=str(cwd))
        sessions_dir = cwd / "espacenet-journal" / "sessions"
        assert not sessions_dir.exists() or not list(sessions_dir.iterdir())

    def test_search_json_real_backend(self):
        result = self._run(["--await-budget", "search", 'ti="disc brake"', "-s", "5", "--json"])
        data = json.loads(result.stdout)
        assert data["resultCount"] > 0
        row = data["results"][0]
        for field in ("publicationNumber", "title", "countryCode", "familyId"):
            assert field in row
        print(f"\n  search hits: {data['totalFamilies']} families / {data['totalPublications']} publications")

    def test_search_csv_out_real_backend(self, tmp_path):
        target = tmp_path / "hits.csv"
        result = self._run(["--await-budget", "search", 'ti="bicycle" AND pa="shimano"', "-s", "10",
                            "-f", "csv", "-o", str(target)])
        assert result.returncode == 0
        assert target.exists() and target.stat().st_size > 100
        head = target.read_text(encoding="utf-8-sig").splitlines()[0]
        assert head.startswith("publicationNumber")
        rows = target.read_text(encoding="utf-8-sig").splitlines()
        assert len(rows) >= 5  # header + hits
        print(f"\n  csv: {target} ({target.stat().st_size:,} bytes, {len(rows) - 1} rows)")

    def test_detail_json_real_backend(self):
        result = self._run(["--await-budget", "detail", "EP2600908A1", "--json"])
        data = json.loads(result.stdout)
        assert data["publicationNumber"].startswith("EP2600908")
        assert data["title"] and data["familyId"]


@pytest.fixture(scope="module")
def backend():
    """Talk to the real Espacenet through the real Edge session."""
    instance = EspacenetBackend.create(profile="default", mode="visible", pacing_ms=700)
    yield instance
    instance.close()


class TestRealBackendE2E:

    def test_search(self, backend):
        payload = run_search(backend, 'ti="bicycle" AND pa="shimano"', size=10)
        assert payload["resultCount"] > 0
        row = payload["results"][0]
        assert row["publicationNumber"] and row["title"]
        assert payload["totalFamilies"] > 0
        print(f"\n  search: {payload['totalFamilies']} families, first={row['publicationNumber']}")

    def test_detail(self, backend):
        detail = run_detail(backend, "EP2600908A1")
        assert detail["publicationNumber"].startswith("EP2600908")
        assert detail["applicants"] and detail["familyId"]
        print(f"\n  detail: {detail['publicationNumber']} — {detail['title'][:60]}")

    def test_claims_us_uses_claims_tree(self, backend):
        search = run_search(backend, 'ti="bicycle" AND pa="shimano"', size=25)
        target = next((r["publicationNumber"] for r in search["results"]
                       if r["countryCode"] in ("US", "CN", "WO")), None)
        assert target, "no US/CN/WO member in sample search results"
        payload = run_claims(backend, target)
        assert payload.get("claims"), payload
        assert payload.get("claimCount", len(payload["claims"])) >= 1
        print(f"\n  claims: {payload['publicationNumber']} — {len(payload['claims'])} claims from {payload.get('textFrom')}")

    def test_claims_ep_falls_back_to_family_member(self, backend):
        payload = run_claims(backend, "EP2600908A1")
        if payload.get("textFrom") and payload["textFrom"] != payload["publicationNumber"]:
            assert payload.get("note"), "fallback must be labelled"
            print(f"\n  claims EP fallback: {payload['textFrom']}")
        else:
            assert payload.get("claims")
            print(f"\n  claims EP direct: {len(payload['claims'])} claims")

    def test_family(self, backend):
        family = run_family(backend, "EP2600908A1")
        assert family["memberCount"] >= 1
        assert family["members"]
        print(f"\n  family: {family['publicationNumber']} — {family['memberCount']} members")

    def test_legal(self, backend):
        legal = run_legal(backend, "EP2600908A1")
        assert "events" in legal
        if legal["events"]:
            assert legal["events"][0].get("date")
        print(f"\n  legal: {legal['publicationNumber']} — {legal.get('eventCount', 0)} events")

    def test_pdf_magic_bytes(self, backend, tmp_path):
        out_dir = tmp_path / "pdfs"
        try:
            payload = run_pdf(backend, "EP2600908A1", out_dir=str(out_dir))
        except Exception as error:
            pytest.fail(f"pdf unavailable for sampled document: {error}")
        file = Path(payload["file"])
        assert file.exists() and file.stat().st_size > 1024
        with open(file, "rb") as f:
            assert f.read(5) == b"%PDF-"
        print(f"\n  PDF: {file} ({file.stat().st_size:,} bytes, kind {payload['imageKind']})")
