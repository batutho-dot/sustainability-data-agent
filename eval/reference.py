"""Compute the right answers to eval/questions.json from the two public APIs. No model, no MCP.

Standard library only, with its own JSON-stat decoding and its own hourly grouping (by the
Danish-time hour string), so it shares no code with the servers the agent uses.

    python eval/reference.py            # uses saved raw answers in eval/data/, downloads what is missing
    python eval/reference.py --refresh  # downloads everything again

Writes eval/expected.json. The raw API answers saved in eval/data/ are also the fixtures
the offline tests replay, so the tests and this script read exactly the same numbers.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
REFRESH = "--refresh" in sys.argv
USER_AGENT = "sustainability-data-agent eval (open-source)"

# ---------------- Energi Data Service (Energinet) ----------------

ENERGI_URL = "https://api.energidataservice.dk/dataset/{dataset}"
WINDOW = ("2026-11-17T00:00", "2026-11-19T00:00")
SERIES = {
    "co2": ("CO2Emis", "Minutes5DK", "CO2Emission"),
    "eur": ("DayAheadPrices", "TimeDK", "DayAheadPriceEUR"),
}


def energi_path(dataset: str, area: str) -> Path:
    return DATA / f"energi_{dataset}_{area}_{WINDOW[0][:10]}_{WINDOW[1][:10]}.json"


def energi_rows(dataset: str, area: str) -> list[dict]:
    """All rows of one dataset and price area over WINDOW, saved to disk on first download."""
    path = energi_path(dataset, area)
    if path.exists() and not REFRESH:
        return json.loads(path.read_text(encoding="utf-8"))
    query = urllib.parse.urlencode(
        {"start": WINDOW[0], "end": WINDOW[1], "filter": json.dumps({"PriceArea": [area]}), "limit": 0}
    )
    request = urllib.request.Request(ENERGI_URL.format(dataset=dataset) + "?" + query, headers={"User-Agent": USER_AGENT})
    for _ in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                rows = json.load(response)["records"]
            break
        except urllib.error.HTTPError as err:
            if err.code != 429:
                raise
            found = re.search(r"(\d+) seconds", err.read().decode("utf-8", "replace"))
            wait = int(found.group(1)) + 2 if found else 65
            print(f"  Energi Data Service rate limit on {dataset} {area}, waiting {wait} s")
            time.sleep(wait)
    else:
        raise RuntimeError(f"gave up on {dataset} {area}")
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def hours(series: str, area: str, day: str) -> dict[str, float]:
    """{'08:00': mean of the sub-hourly values in that Danish hour} for one Danish day."""
    dataset, time_key, value_key = SERIES[series]
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in energi_rows(dataset, area):
        stamp = row[time_key]
        if stamp.startswith(day) and row[value_key] is not None:
            buckets[stamp[11:13] + ":00"].append(float(row[value_key]))
    out = {h: sum(v) / len(v) for h, v in sorted(buckets.items())}
    if len(out) != 24:
        raise RuntimeError(f"{series} {area} {day}: expected 24 hours, got {len(out)}")
    return out


def day_mean(h: dict[str, float]) -> float:
    return sum(h.values()) / len(h)


def lowest_hour(h: dict[str, float]) -> str:
    return min(h, key=h.get)  # hours are in time order, so a tie goes to the earlier hour


def highest_hour(h: dict[str, float]) -> str:
    return max(h, key=h.get)


def best_block(h: dict[str, float], n: int) -> tuple[str, float]:
    keys = list(h)
    blocks = [(sum(h[k] for k in keys[i : i + n]) / n, keys[i]) for i in range(len(keys) - n + 1)]
    value, start = min(blocks)
    return start, value


# ---------------- Eurostat ----------------

EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}"
EU27 = "AT BE BG CY CZ DE DK EE EL ES FI FR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split()


def eurostat_key(code: str, params: list[tuple[str, str]]) -> str:
    """File name for one Eurostat request; the offline tests compute the same name."""
    digest = hashlib.sha1(f"{code}?{sorted(params)}".encode()).hexdigest()[:12]
    return f"eurostat_{code}_{digest}.json"


def eurostat_params(filters: dict[str, list[str]], **time_params: str) -> list[tuple[str, str]]:
    """The query the eurostat-mcp server builds: format, lang, one pair per filter value, time."""
    params = [("format", "JSON"), ("lang", "EN")]
    for dim, values in filters.items():
        params.extend((dim, v) for v in values)
    params.extend((k, v) for k, v in time_params.items())
    return params


def eurostat_get(code: str, params: list[tuple[str, str]]) -> dict:
    path = DATA / eurostat_key(code, params)
    if path.exists() and not REFRESH:
        return json.loads(path.read_text(encoding="utf-8"))
    url = EUROSTAT_URL.format(code=code) + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=90) as response:
        data = json.load(response)
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def jsonstat_cells(data: dict) -> dict[tuple[str, ...], float]:
    """{(code per dimension, in data['id'] order): value}. Row-major, last dimension fastest."""
    ids, sizes = data["id"], data["size"]
    codes_by_dim = []
    for dim in ids:
        index = data["dimension"][dim]["category"]["index"]
        ordered = sorted(index, key=index.get) if isinstance(index, dict) else list(index)
        codes_by_dim.append(ordered)
    cells = {}
    for flat, value in data["value"].items():
        rest, key = int(flat), []
        for size, codes in zip(reversed(sizes), reversed(codes_by_dim)):
            key.append(codes[rest % size])
            rest //= size
        cells[tuple(reversed(key))] = float(value)
    return cells


def pick(data: dict, **want: str) -> float:
    ids = data["id"]
    matches = [v for k, v in jsonstat_cells(data).items() if all(k[ids.index(d)] == c for d, c in want.items())]
    if len(matches) != 1:
        raise RuntimeError(f"expected one value for {want}, found {len(matches)}")
    return matches[0]


# The requests the reference makes. The offline tests replay exactly these.
RENEWABLES = (
    "nrg_ind_ren",
    eurostat_params(
        {"geo": ["DK", "EU27_2020"], "nrg_bal": ["REN", "REN_ELC"], "unit": ["PC"]},
        sinceTimePeriod="2015",
        untilTimePeriod="2024",
    ),
)
PRICES = (
    "nrg_pc_204",
    eurostat_params(
        {"geo": EU27 + ["EU27_2020"], "nrg_cons": ["KWH2500-4999"], "tax": ["I_TAX", "X_TAX"], "currency": ["EUR"], "unit": ["KWH"]},
        sinceTimePeriod="2026-S1",
        untilTimePeriod="2026-S1",
    ),
)


def compute() -> dict:
    ren = eurostat_get(*RENEWABLES)
    prices = eurostat_get(*PRICES)

    def share(geo: str, bal: str, year: str) -> float:
        return pick(ren, geo=geo, nrg_bal=bal, time=year)

    def price(geo: str, tax: str = "I_TAX") -> float:
        return pick(prices, geo=geo, tax=tax, time="2026-S1")

    co2 = {(a, d): hours("co2", a, d) for a in ("DK1", "DK2") for d in ("2026-11-17", "2026-11-18")}
    eur = {(a, d): hours("eur", a, d) for a in ("DK1", "DK2") for d in ("2026-11-17", "2026-11-18")}

    answers: dict[str, dict] = {}
    answers["q01"] = {
        "gap_pp": share("DK", "REN", "2024") - share("EU27_2020", "REN", "2024"),
        "hour": lowest_hour(co2["DK1", "2026-11-18"]),
    }
    spot = day_mean(eur["DK1", "2026-11-17"])
    answers["q02"] = {"spot_eur_mwh": spot, "household_eur_kwh": price("DK"), "pct": 100 * (spot / 1000) / price("DK")}
    spot = day_mean(eur["DK2", "2026-11-18"])
    answers["q03"] = {
        "spot_eur_mwh": spot,
        "household_eur_kwh": price("DK", "X_TAX"),
        "pct": 100 * (spot / 1000) / price("DK", "X_TAX"),
    }
    h = eur["DK1", "2026-11-18"]
    cheapest = lowest_hour(h)
    answers["q04"] = {"cheapest_hour": cheapest, "ratio": price("DK") / (h[cheapest] / 1000)}
    means = {a: day_mean(co2[a, "2026-11-17"]) for a in ("DK1", "DK2")}
    answers["q05"] = {"area": min(means, key=means.get), "share_pct": share("DK", "REN_ELC", "2024")}
    eu_prices = {}
    for geo in EU27:
        try:
            eu_prices[geo] = price(geo)
        except RuntimeError:
            pass  # no value reported for this member state
    h = eur["DK2", "2026-11-17"]
    dear = highest_hour(h)
    answers["q06"] = {"country": max(eu_prices, key=eu_prices.get), "hour": dear, "price_eur_mwh": h[dear]}
    start, value = best_block(eur["DK1", "2026-11-17"], 3)
    answers["q07"] = {"block_start": start, "pct": 100 * (value / 1000) / price("EU27_2020")}
    answers["q08"] = {"de_minus_dk_eur_kwh": price("DE") - price("DK"), "co2_g_kwh": day_mean(co2["DK1", "2026-11-18"])}
    answers["q09"] = {
        "gap_pp": share("DK", "REN_ELC", "2024") - share("EU27_2020", "REN_ELC", "2024"),
        "block_start": best_block(co2["DK1", "2026-11-17"], 3)[0],
    }
    answers["q10"] = {
        "change_pp": share("DK", "REN", "2024") - share("DK", "REN", "2015"),
        "dk1_minus_dk2_g_kwh": day_mean(co2["DK1", "2026-11-18"]) - day_mean(co2["DK2", "2026-11-18"]),
    }
    return {
        "computed_by": "eval/reference.py (standard library, no model, no MCP)",
        "sources": {
            "energi_data_service": f"CO2Emis and DayAheadPrices, DK1 and DK2, {WINDOW[0]} to {WINDOW[1]} Danish time",
            "eurostat": {
                "nrg_ind_ren": ren.get("updated"),
                "nrg_pc_204": prices.get("updated"),
                "eu27_prices_reported": len(eu_prices),
            },
        },
        "answers": answers,
    }


def main() -> None:
    result = compute()
    (HERE / "expected.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for qid, ans in result["answers"].items():
        print(qid, json.dumps(ans))


if __name__ == "__main__":
    main()
