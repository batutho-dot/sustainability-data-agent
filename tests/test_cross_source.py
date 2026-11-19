"""The 10 eval questions answered through the two real servers (in memory, offline), the way a
correct agent would: the tool calls a model should make, then the arithmetic on their output.

Every answer must score right against eval/expected.json, which the plain reference script
computed independently. So the right answer is reachable through the tools, and a miss in the
paid eval is the model's, not the servers'.
"""

from __future__ import annotations

import json

import pytest
from conftest import reference

from sustainability_data_agent.agent import connect
from sustainability_data_agent.scoring import score

REN_FILTERS = {"geo": ["DK", "EU27_2020"], "nrg_bal": ["REN", "REN_ELC"], "unit": ["PC"]}
PRICE_FILTERS = {
    "geo": reference.EU27 + ["EU27_2020"],
    "nrg_cons": ["KWH2500-4999"],
    "tax": ["I_TAX", "X_TAX"],
    "currency": ["EUR"],
    "unit": ["KWH"],
}


async def tool(toolbox, name, **args):
    text, is_error = await toolbox.call(name, args)
    assert not is_error, text
    return json.loads(text)


async def renewables(toolbox):
    out = await tool(toolbox, "eurostat__fetch_series", dataset="nrg_ind_ren", filters=REN_FILTERS, since="2015", until="2024")
    return {(r["geo"], r["nrg_bal"], r["time"]): r["value"] for r in out["rows"]}


async def prices(toolbox):
    out = await tool(toolbox, "eurostat__fetch_series", dataset="nrg_pc_204", filters=PRICE_FILTERS, since="2026-S1", until="2026-S1")
    return {(r["geo"], r["tax"]): r["value"] for r in out["rows"] if r["value"] is not None}


def hh(item):
    return item["hour_dk"][11:16]


async def spot(toolbox, area, day, **extra):
    return await tool(toolbox, "energidata__spot_price", area=area, start=day, currency="EUR", **extra)


async def co2(toolbox, area, day):
    return await tool(toolbox, "energidata__co2_intensity", area=area, start=day, source="measured")


async def best(toolbox, area, metric, day, **extra):
    if metric == "price":
        extra.setdefault("currency", "EUR")
    else:
        extra.setdefault("co2_source", "measured")
    return await tool(toolbox, "energidata__best_hours", area=area, metric=metric, start=day, **extra)


async def answer(qid, t):
    if qid == "q01":
        r = await renewables(t)
        b = await best(t, "DK1", "co2", "2026-11-18")
        return {"gap_pp": r["DK", "REN", "2024"] - r["EU27_2020", "REN", "2024"], "hour": hh(b["picked"][0])}
    if qid == "q02":
        s = (await spot(t, "DK1", "2026-11-17"))["mean_of_hours"]
        hp = (await prices(t))["DK", "I_TAX"]
        return {"spot_eur_mwh": s, "household_eur_kwh": hp, "pct": 100 * s / 1000 / hp}
    if qid == "q03":
        s = (await spot(t, "DK2", "2026-11-18"))["mean_of_hours"]
        hp = (await prices(t))["DK", "X_TAX"]
        return {"spot_eur_mwh": s, "household_eur_kwh": hp, "pct": 100 * s / 1000 / hp}
    if qid == "q04":
        b = (await best(t, "DK1", "price", "2026-11-18"))["picked"][0]
        hp = (await prices(t))["DK", "I_TAX"]
        return {"cheapest_hour": hh(b), "ratio": hp / (b["value"] / 1000)}
    if qid == "q05":
        means = {a: (await co2(t, a, "2026-11-17"))["mean_of_hours"] for a in ("DK1", "DK2")}
        r = await renewables(t)
        return {"area": min(means, key=means.get), "share_pct": r["DK", "REN_ELC", "2024"]}
    if qid == "q06":
        p = await prices(t)
        eu = {g: v for (g, tax), v in p.items() if tax == "I_TAX" and g in reference.EU27}
        b = (await best(t, "DK2", "price", "2026-11-17", highest=True))["picked"][0]
        return {"country": max(eu, key=eu.get), "hour": hh(b), "price_eur_mwh": b["value"]}
    if qid == "q07":
        b = await best(t, "DK1", "price", "2026-11-17", n_hours=3, consecutive=True)
        hp = (await prices(t))["EU27_2020", "I_TAX"]
        return {"block_start": hh(b["picked"][0]), "pct": 100 * b["mean_of_picked"] / 1000 / hp}
    if qid == "q08":
        p = await prices(t)
        return {"de_minus_dk_eur_kwh": p["DE", "I_TAX"] - p["DK", "I_TAX"], "co2_g_kwh": (await co2(t, "DK1", "2026-11-18"))["mean_of_hours"]}
    if qid == "q09":
        r = await renewables(t)
        b = await best(t, "DK1", "co2", "2026-11-17", n_hours=3, consecutive=True)
        return {"gap_pp": r["DK", "REN_ELC", "2024"] - r["EU27_2020", "REN_ELC", "2024"], "block_start": hh(b["picked"][0])}
    if qid == "q10":
        r = await renewables(t)
        d1 = (await co2(t, "DK1", "2026-11-18"))["mean_of_hours"]
        d2 = (await co2(t, "DK2", "2026-11-18"))["mean_of_hours"]
        return {"change_pp": r["DK", "REN", "2024"] - r["DK", "REN", "2015"], "dk1_minus_dk2_g_kwh": d1 - d2}
    raise KeyError(qid)


@pytest.mark.anyio
async def test_every_question_is_answerable_through_the_tools(servers, questions, expected):
    async with connect(servers) as toolbox:
        for q in questions:
            got = await answer(q["id"], toolbox)
            text = "working...\nANSWER: " + json.dumps(got)
            graded = score(q, expected[q["id"]], text)
            assert graded["right"], (q["id"], graded["checks"])


def test_every_question_needs_both_servers(questions):
    for q in questions:
        text = q["question"]
        assert "Eurostat" in text, q["id"]
        assert any(w in text for w in ("DK1", "DK2", "price area")), q["id"]


def test_reference_reproduces_expected_offline(expected):
    assert reference.compute()["answers"] == expected
