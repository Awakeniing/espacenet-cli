"""Unit tests for the search budget and the document resolution cache."""

import contextlib
import json

import pytest

from espacenet_cli.core.budget import SearchBudget
from espacenet_cli.core.document import run_claims, run_description, run_family, run_legal
from espacenet_cli.core.errors import CliError


# ---------------------------------------------------------------- budget

class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_budget_starts_full_and_depletes(tmp_path):
    clock = FakeClock()
    budget = SearchBudget(tmp_path / "b.json", clock=clock)
    for _ in range(12):
        budget.acquire()
    with pytest.raises(CliError) as exc:
        budget.acquire()
    assert exc.value.code == "SEARCH_BUDGET"


def test_budget_refills_over_time(tmp_path):
    clock = FakeClock()
    budget = SearchBudget(tmp_path / "b.json", clock=clock)
    for _ in range(12):
        budget.acquire()
    clock.advance(7.0)  # one token
    budget.acquire()
    with pytest.raises(CliError):
        budget.acquire()


def test_budget_persists_across_instances(tmp_path):
    clock = FakeClock()
    b1 = SearchBudget(tmp_path / "b.json", clock=clock)
    for _ in range(12):
        b1.acquire()
    b2 = SearchBudget(tmp_path / "b.json", clock=clock)
    with pytest.raises(CliError):
        b2.acquire()


def test_budget_penalty_blocks_then_expires(tmp_path):
    clock = FakeClock()
    budget = SearchBudget(tmp_path / "b.json", clock=clock)
    budget.acquire()  # tokens=11
    budget.observe_rejection()
    assert budget.penalty_remaining() > 0
    with pytest.raises(CliError):
        budget.acquire()  # penalized even with tokens
    snapshot = budget.snapshot()
    assert snapshot["penaltyUntil"] is not None
    clock.advance(400.0)
    assert budget.penalty_remaining() == 0.0
    budget.acquire()  # refilled during penalty: works again


def test_budget_wait_mode_sleeps_until_token(tmp_path, monkeypatch):
    clock = FakeClock()
    budget = SearchBudget(tmp_path / "b.json", clock=clock)
    for _ in range(12):
        budget.acquire()
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock.advance(seconds)

    monkeypatch.setattr("espacenet_cli.core.budget.time.sleep", fake_sleep)
    budget.acquire(wait=True, wait_budget_s=60)
    assert slept, "wait mode must sleep until the next token"


def test_budget_disabled_bypasses_everything(tmp_path):
    budget = SearchBudget(tmp_path / "b.json", enabled=False)
    for _ in range(50):
        budget.acquire()


def test_budget_state_file_roundtrip(tmp_path):
    clock = FakeClock()
    budget = SearchBudget(tmp_path / "b.json", clock=clock)
    budget.acquire()
    data = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert data["tokens"] == 11.0
    assert data["version"] == 1


# ---------------------------------------------------------------- cache

class CountingBackend:
    """Fake backend that counts search_raw calls (each = 1 search token).

    Document fetches return empty responses so the commands degrade to
    NOT_SUPPORTED/NOT_FOUND *after* resolution — which is the part under test.
    """

    def __init__(self, tmp_path):
        self.paths = {"profile_root": tmp_path}
        self.search_calls = 0
        self._resolution_cache = {}

    def search_raw(self, query, from_=0, size=20):
        self.search_calls += 1
        return _DETAIL_PAYLOAD

    def fetch_json(self, path, method="GET", body=None, headers=None):
        return {"status": 200, "json": None, "text": "", "headers": {}}

    def fetch(self, path, method="GET", body=None, headers=None, binary=False):
        return {"status": 404, "headers": {}, "text": ""}


_DETAIL_PAYLOAD = {
    "familiesNumber": 1,
    "publicationsNumber": 1,
    "hits": [{
        "familyNumber": "555",
        "publicationsCount": 1,
        "hits": [{
            "fields": {
                "publications.pn_docdb": ["EP2600908A1"],
                "publications.ti_en": ["Dossier test"],
                "publications.abs_en": ["abs"],
                "publications.pd": ["2022-06-01"],
                "publications.pa_patents": ["ACME"],
                "publications.in_patents": ["Doe J"],
                "publications.pr_docdb": ["2021-06-01"],
                "publications.app_fdate.untouched": ["2021-06-01"],
                "publications.ipc_icai": ["H01L"],
                "publications.ci_cpci": ["H01L21/00"],
            },
            "score": 1.0,
        }],
    }],
}


def test_full_dossier_costs_one_search(tmp_path):
    backend = CountingBackend(tmp_path)
    with contextlib.suppress(CliError):
        run_claims(backend, "EP2600908A1")
    with contextlib.suppress(CliError):
        run_description(backend, "EP2600908A1")
    with contextlib.suppress(CliError):
        run_family(backend, "EP2600908A1")
    with contextlib.suppress(CliError):
        run_legal(backend, "EP2600908A1")
    assert backend.search_calls == 1, "memory cache must collapse 4 commands to 1 search"


def test_kindless_lookup_hits_same_cache_entry(tmp_path):
    backend = CountingBackend(tmp_path)
    with contextlib.suppress(CliError):
        run_claims(backend, "EP2600908A1")
    with contextlib.suppress(CliError):
        run_claims(backend, "EP2600908")
    assert backend.search_calls == 1


def test_persistent_cache_across_backends(tmp_path):
    b1 = CountingBackend(tmp_path)
    with contextlib.suppress(CliError):
        run_claims(b1, "EP2600908A1")
    b2 = CountingBackend(tmp_path)  # new session, same profile
    with contextlib.suppress(CliError):
        run_description(b2, "EP2600908A1")
    assert b2.search_calls == 0, "persistent cache should serve without a search"
    assert b2._resolution_cache["EP2600908A1"]["family_id"] == "555"


def test_refresh_bypasses_cache(tmp_path):
    backend = CountingBackend(tmp_path)
    with contextlib.suppress(CliError):
        run_claims(backend, "EP2600908A1")
    with contextlib.suppress(CliError):
        run_claims(backend, "EP2600908A1", refresh=True)
    assert backend.search_calls == 2
