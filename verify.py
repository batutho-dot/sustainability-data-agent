"""Check this repository end to end, offline. Changes nothing in the tree.

    python verify.py

Steps: compile every Python file, run the offline tests, recompute the reference answers from
the saved API answers and compare with eval/expected.json, then start both MCP servers over
stdio and check the agent sees the six known tools. No model call and no network call (the
paid eval is eval/run_eval.py, run on purpose, never from here).
"""

from __future__ import annotations

import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KNOWN_TOOLS = [
    "energidata__co2_intensity",
    "energidata__spot_price",
    "energidata__best_hours",
    "eurostat__search_datasets",
    "eurostat__describe_dataset",
    "eurostat__fetch_series",
]


def fail(step: str, reason: str) -> None:
    print(f"verify: FAIL at {step}: {reason}")
    sys.exit(1)


def step_compile() -> None:
    files = [p for d in ("src", "eval", "tests") for p in (ROOT / d).rglob("*.py")] + [ROOT / "verify.py"]
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(files):
            try:
                py_compile.compile(str(path), cfile=os.path.join(tmp, f"{i}.pyc"), doraise=True)
            except py_compile.PyCompileError as exc:
                fail("compile", f"{path.relative_to(ROOT)}: {exc.msg.strip().splitlines()[-1]}")
    print(f"compile: {len(files)} files ok")


def step_tests() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", tmp],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
    last = (proc.stdout.strip().splitlines() or ["(no output)"])[-1]
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        fail("tests", last)
    print(f"tests: {last}")


def step_reference() -> None:
    code = (
        "import json,sys,urllib.request\n"
        "def no(*a,**k): raise RuntimeError('network')\n"
        "urllib.request.urlopen=no\n"
        "sys.path.insert(0,'eval'); import reference\n"
        "got=reference.compute()['answers']\n"
        "want=json.load(open('eval/expected.json',encoding='utf-8'))['answers']\n"
        "print('same' if got==want else 'DIFFERENT')\n"
    )
    proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0 or proc.stdout.strip() != "same":
        fail("reference", (proc.stdout + proc.stderr).strip().splitlines()[-1] if (proc.stdout + proc.stderr).strip() else "no output")
    print("reference: 10 answers recomputed from eval/data/ equal eval/expected.json")


def step_stdio() -> None:
    code = (
        "import anyio\n"
        "from sustainability_data_agent.agent import connect\n"
        "async def m():\n"
        "    async with connect() as t: print(','.join(d['name'] for d in t.definitions))\n"
        "anyio.run(m)\n"
    )
    proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    names = proc.stdout.strip().splitlines()[-1].split(",") if proc.stdout.strip() else []
    if proc.returncode != 0 or names != KNOWN_TOOLS:
        fail("stdio", f"tools seen {names or proc.stderr.strip()[-300:]}")
    print("stdio: both servers started over stdio, 6 known tools listed")


def main() -> None:
    print(f"verify-repo: {ROOT}")
    step_compile()
    step_tests()
    step_reference()
    step_stdio()
    print("verify: PASS")


if __name__ == "__main__":
    main()
