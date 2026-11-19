"""The agent loop with a scripted stand-in for Claude, against the two real servers (offline)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from conftest import load_module

from sustainability_data_agent.agent import ask, connect
from sustainability_data_agent.pricing import cost_usd
from sustainability_data_agent.scoring import parse_answer, prompt_for, score

run_eval = load_module("run_eval")


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, **args):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


def reply(stop, *blocks, inp=1000, out=100):
    return SimpleNamespace(stop_reason=stop, content=list(blocks), usage=SimpleNamespace(input_tokens=inp, output_tokens=out))


class ScriptedClaude:
    """Returns the scripted replies in order and keeps every request it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self

    async def create(self, **request):
        self.requests.append(json.loads(json.dumps(request, default=lambda o: o.__dict__)))
        return self.replies.pop(0)


@pytest.mark.anyio
async def test_tools_from_both_servers_are_offered(servers):
    async with connect(servers) as toolbox:
        names = {d["name"] for d in toolbox.definitions}
    assert {"energidata__co2_intensity", "energidata__spot_price", "energidata__best_hours"} <= names
    assert {"eurostat__search_datasets", "eurostat__describe_dataset", "eurostat__fetch_series"} <= names
    assert all(d["input_schema"]["type"] == "object" for d in toolbox.definitions)


@pytest.mark.anyio
async def test_one_question_two_servers_records_every_call(servers):
    claude = ScriptedClaude(
        reply(
            "tool_use",
            text("I need both sources."),
            tool_use("t1", "energidata__best_hours", area="DK1", metric="co2", start="2026-11-18", co2_source="measured"),
            tool_use("t2", "eurostat__fetch_series", dataset="nrg_ind_ren", filters={"geo": ["DK", "EU27_2020"], "nrg_bal": ["REN", "REN_ELC"], "unit": ["PC"]}, since="2015", until="2024"),
        ),
        reply("end_turn", text('Gap computed.\nANSWER: {"gap_pp": 21.22, "hour": "18:00"}'), inp=5000, out=200),
    )
    async with connect(servers) as toolbox:
        answer = await ask("q", toolbox, claude, model="claude-haiku-5-5")

    assert [c.name for c in answer.calls] == ["energidata__best_hours", "eurostat__fetch_series"]
    assert not any(c.is_error for c in answer.calls)
    # both tool results go back in ONE user message, matched by id
    second = claude.requests[1]["messages"]
    results = second[-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert json.loads(results[0]["content"])["picked"][0]["hour_dk"].endswith("18:00")
    assert answer.usage.requests == 2
    assert answer.usage.input_tokens == 6000 and answer.usage.output_tokens == 300
    assert answer.usage.cost_usd == pytest.approx(cost_usd("claude-haiku-5-5", 1000, 100) + cost_usd("claude-haiku-5-5", 5000, 200))
    report = answer.report()
    assert "Tool calls (2):" in report and "energidata__best_hours(" in report and "eurostat__fetch_series(" in report


@pytest.mark.anyio
async def test_bad_tool_calls_come_back_as_errors_not_crashes(servers):
    claude = ScriptedClaude(
        reply(
            "tool_use",
            tool_use("a", "nosuchserver__x"),
            tool_use("b", "energidata__co2_intensity", area="DK1", start="not a date"),
            tool_use("c", "eurostat__fetch_series", dataset="no_such_dataset"),
        ),
        reply("end_turn", text("I could not get the data.")),
    )
    async with connect(servers) as toolbox:
        answer = await ask("q", toolbox, claude)
    assert [c.is_error for c in answer.calls] == [True, True, True]
    results = claude.requests[1]["messages"][-1]["content"]
    assert all(r["is_error"] for r in results)
    assert answer.text == "I could not get the data."


@pytest.mark.anyio
async def test_turn_limit_and_refusal(servers):
    loop = [reply("tool_use", tool_use(f"t{i}", "energidata__spot_price", area="DK1", start="2026-11-17")) for i in range(3)]
    async with connect(servers) as toolbox:
        stuck = await ask("q", toolbox, ScriptedClaude(*loop), max_turns=3)
        refused = await ask("q", toolbox, ScriptedClaude(reply("refusal")))
    assert stuck.stop_reason == "max_turns" and len(stuck.calls) == 3
    assert refused.stop_reason == "refusal" and refused.text


def test_scoring_rules(questions, expected):
    q = next(x for x in questions if x["id"] == "q01")
    want = expected["q01"]
    good = f'blah\nANSWER: {{"gap_pp": {want["gap_pp"] + 0.005}, "hour": "{int(want["hour"][:2])}:00"}}'
    assert score(q, want, good)["right"]
    assert not score(q, want, f'ANSWER: {{"gap_pp": {want["gap_pp"] + 0.05}, "hour": "{want["hour"]}"}}')["right"]
    assert not score(q, want, "no answer line")["right"]
    assert parse_answer('**ANSWER:** {"a": 1}') == {"a": 1}
    q4 = next(x for x in questions if x["id"] == "q04")
    ratio = expected["q04"]["ratio"]
    assert score(q4, expected["q04"], f'ANSWER: {{"cheapest_hour": "{expected["q04"]["cheapest_hour"]}", "ratio": {ratio * 1.004}}}')["right"]
    assert not score(q4, expected["q04"], f'ANSWER: {{"cheapest_hour": "{expected["q04"]["cheapest_hour"]}", "ratio": {ratio * 1.01}}}')["right"]
    assert '"pct": <number>' in prompt_for(next(x for x in questions if x["id"] == "q02"))


def test_budget_check_refuses_a_run_past_the_cap(tmp_path):
    ledger = tmp_path / "spend.jsonl"
    assert run_eval.check_budget("claude-haiku-5-5", 10, 3.0, ledger)[0]
    ledger.write_text(json.dumps({"cost_usd": 2.95}) + "\n", encoding="utf-8")
    assert not run_eval.check_budget("claude-haiku-5-5", 10, 3.0, ledger)[0]
    assert not run_eval.check_budget("claude-sonnet-5-5", 1, 3.0, ledger)[0]


@pytest.mark.anyio
async def test_eval_run_end_to_end_with_scripted_claude(servers, questions, expected, tmp_path):
    q = next(x for x in questions if x["id"] == "q01")
    final = 'ANSWER: ' + json.dumps(expected["q01"])
    claude = ScriptedClaude(reply("tool_use", tool_use("t", "energidata__best_hours", area="DK1", metric="co2", start="2026-11-18")), reply("end_turn", text(final)))
    ledger = tmp_path / "spend.jsonl"
    result = await run_eval.run([q], expected, "claude-haiku-5-5", 3.0, claude, "test", ledger, servers)
    assert result["score"] == 1 and result["asked"] == 1
    assert result["questions"][0]["tool_calls"][0]["name"] == "energidata__best_hours"
    assert run_eval.spent(ledger) == pytest.approx(result["cost_usd"])
