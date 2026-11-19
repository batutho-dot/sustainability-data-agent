"""Offline by default: both servers run in memory, and their API calls are answered from the
raw API answers that eval/reference.py saved in eval/data/. Any other network call fails.

So the tests, the reference script and the servers all read the same numbers.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from energidata_mcp import api as energi_api
from energidata_mcp.server import mcp as energidata_server
from eurostat_mcp import eurostat as eurostat_api
from eurostat_mcp.server import mcp as eurostat_server

ROOT = Path(__file__).parent.parent
EVAL = ROOT / "eval"
DATA = EVAL / "data"
DK_TIME = {"CO2Emis": "Minutes5DK", "DayAheadPrices": "TimeDK"}


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, EVAL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reference = load_module("reference")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def no_network(*args, **kwargs):
        raise RuntimeError("network call in an offline test")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    monkeypatch.setattr("urllib.request.urlopen", no_network)

    async def fake_fetch_records(dataset, start, end, area):
        path = DATA / f"energi_{dataset}_{area}_2026-11-17_2026-11-19.json"
        if not path.exists():
            return []
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in rows if start <= r[DK_TIME[dataset]][:16] < end]

    def fake_get(url, params=None):
        code = url.rstrip("/").rsplit("/", 1)[-1]
        path = DATA / reference.eurostat_key(code, list(params or []))
        if not path.exists():
            raise eurostat_api.EurostatError(f"offline test: no saved Eurostat answer for {code} {params}")
        body = path.read_text(encoding="utf-8")
        return SimpleNamespace(status_code=200, text=body, json=lambda: json.loads(body))

    monkeypatch.setattr(energi_api, "fetch_records", fake_fetch_records)
    monkeypatch.setattr(eurostat_api, "_get", fake_get)


@pytest.fixture
def servers():
    """The two real servers, in memory instead of over stdio."""
    return {"energidata": energidata_server, "eurostat": eurostat_server}


@pytest.fixture
def questions():
    return json.loads((EVAL / "questions.json").read_text(encoding="utf-8"))["questions"]


@pytest.fixture
def expected():
    return json.loads((EVAL / "expected.json").read_text(encoding="utf-8"))["answers"]
