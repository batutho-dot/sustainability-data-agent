# sustainability-data-agent

A small agent that answers energy questions no single source can, using two MCP servers at once: **energidata-mcp** (hourly CO2 intensity and spot prices on the Danish grid, from Energinet) and **eurostat-mcp** (EU energy statistics). Ask what share of a Danish household's electricity price is the spot price: it takes the spot price from one server and the household price from the other, converts the units, does the sum and prints every tool call.

## Result

10 questions that each need both servers. A plain script computes the right answers from the same two public APIs.

**Score: 10 out of 10 in each of 3 runs** with Claude Haiku 5.5 (mean 0.0215 USD per run of 10 questions) and **10 out of 10 in each of 3 runs** with Claude Sonnet 5.5 (mean 0.379 USD per run), 2026-11-19. A first run per model, the same day, also scored 10/10. Each server scored 10/10 on its own questions. Here both run unchanged, pinned to one commit each, behind one agent.

```mermaid
flowchart LR
    q["Question<br/>spot price as a share of household price"]
    agent["sustainability-data-agent<br/>tool-use loop, prints every call, tokens and cost"]
    claude["Claude Messages API<br/>Haiku 5.5 or Sonnet 5.5"]
    e["energidata-mcp<br/>co2_intensity, spot_price, best_hours"]
    s["eurostat-mcp<br/>search_datasets, describe_dataset, fetch_series"]
    eds["Energi Data Service<br/>Energinet: CO2Emis, DayAheadPrices"]
    est["Eurostat API<br/>nrg_ind_ren, nrg_pc_204, ..."]

    q --> agent
    agent <-->|"messages + tool results"| claude
    agent <-->|"MCP over stdio"| e
    agent <-->|"MCP over stdio"| s
    e --> eds
    s --> est

    classDef outside fill:#eee,stroke:#888,stroke-dasharray: 4 3
    class claude,eds,est outside
```

More diagrams: [docs/architecture.md](docs/architecture.md).

| # | Question (short) | Right answer (plain script) | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|---|---|
| q01 | DK minus EU27 renewable share 2024; cleanest hour DK1, 18 Nov | 21.22 pp; 18:00 | right (3 calls) | right (2) |
| q02 | DK1 mean spot 17 Nov as % of DK household price 2026-S1, all taxes | 209.17 EUR/MWh, 0.2375 EUR/kWh, 88.07 % | right (3) | right (3) |
| q03 | DK2 mean spot 18 Nov as % of DK household price excl. taxes | 177.57 EUR/MWh, 0.1889 EUR/kWh, 94.00 % | right (4, 1 error) | right (3) |
| q04 | DK household price / cheapest DK1 hour 18 Nov | 04:00; 2.38 times | right (3) | right (3) |
| q05 | Lower-CO2 area 17 Nov; DK renewable share in electricity 2024 | DK2; 79.655 % | right (4) | right (3) |
| q06 | Dearest EU27 household price 2026-S1; dearest DK2 hour 17 Nov | IE; 09:00, 266.97 EUR/MWh | right (3) | right (4, 1 error) |
| q07 | Cheapest 3 h DK1 block 17 Nov as % of EU27 household price | starts 21:00; 59.31 % | right (4, 1 error) | right (3) |
| q08 | DE minus DK household price 2026-S1; DK1 mean CO2 18 Nov | 0.1243 EUR/kWh; 120.92 g/kWh | right (3) | right (3) |
| q09 | DK minus EU27 renewable share in electricity 2024; cleanest 3 h DK1 17 Nov | 32.152 pp; starts 21:00 | right (2) | right (3) |
| q10 | DK renewable share change 2015 to 2024; DK1 minus DK2 CO2 18 Nov | 15.992 pp; -0.55 g/kWh | right (4) | right (4) |

This table is the first run per model; numbers in brackets are tool calls. Every question used at least one tool from each server. In the 3 later runs per model, every question was right every time.

Three runs per model, 10 questions each:

| Model | Score per run | Mean | Min to max | Cost per run (mean, min to max) | Tokens in per run (mean) | Tokens out per run (mean) | Tool calls per run | Tool errors per run |
|---|---|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | 10, 10, 10 | 10.0 | 10 to 10 | 0.0215 USD (0.0212 to 0.0221) | 168,679 | 9,347 | 33 to 36 | 1 to 3 |
| Claude Sonnet 5.5 | 10, 10, 10 | 10.0 | 10 to 10 | 0.3792 USD (0.3682 to 0.3995) | 156,516 | 6,619 | 32 to 34 | 2 to 3 |

Run files: `eval/results/claude-haiku-5-5-20261119-{2248,2249,2255}.json` and `eval/results/claude-sonnet-5-5-20261119-{2302,2309,2315}.json`. A tool error is a call the server rejected (mostly a guessed filter name); the model read the error and retried.

Cost is computed from reported tokens and the list prices in `src/sustainability_data_agent/pricing.py`, not from an invoice. Total spent on this repository: 1.6158 USD (`eval/results/spend.jsonl`). That covers the 8 full runs, one unscored demo question, and 0.0353 USD for two runs I stopped part way and one single-question check.

## Run it

Python 3.11 or newer and an Anthropic API key. From a clone:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
export ANTHROPIC_API_KEY=...                        # PowerShell: $env:ANTHROPIC_API_KEY="..."
.venv/Scripts/python -m sustainability_data_agent "How does Denmark's renewable share compare with the EU average?"
```

On Windows, clone to a short path (for example `C:\code\sustainability-data-agent`) or enable long paths. The `anthropic` package passes the 260-character limit in a deep venv and pip stops halfway.

`requirements.txt` installs both servers from `vendor/` (see [vendor/README.md](vendor/README.md)) and this agent, which starts them itself. `--model claude-sonnet-5-5` selects Sonnet; Haiku 5.5 is the default.

Every answer starts with its tool calls. q02 with Haiku 5.5 (shortened):

```text
Tool calls (3):
  1. energidata__spot_price("area"="DK1","start"="2026-11-17","currency"="EUR")
  2. eurostat__describe_dataset("dataset"="nrg_pc_204")
  3. eurostat__fetch_series("dataset"="nrg_pc_204","filters"={"geo"=["DK"],"nrg_cons"=["KWH2500-4999"],"tax"=["I_TAX"],"currency"=["EUR"],"unit"=["KWH"],"siec"=["E7000"],"freq"=["S"]},"since"="2026-S1","until"="2026-S1")
...
ANSWER: {"spot_eur_mwh": 209.17, "household_eur_kwh": 0.2375, "pct": 88.07}
```

All calls and answers: `eval/results/`. An unscored run: [docs/example-run.md](docs/example-run.md).

## Tests

```bash
.venv/Scripts/python -m pytest      # 10 tests, offline: no model, no network
.venv/Scripts/python verify.py      # compile, tests, reference check, both servers over stdio
```

Both real servers run in memory on the raw answers in `eval/data/`. The tests check that all 10 right answers are reachable through the six tools, drive the agent loop with a scripted Claude (parallel calls, bad tool names, a bad date, an unknown dataset, the turn limit, a refusal) and check the spend cap.

## The eval

- `eval/questions.json`: 10 questions, the keys each answer needs, a tolerance per number. Four combine both sources in one calculation (q02, q03, q04, q07); six put a Danish grid fact next to an EU statistic.
- `eval/reference.py`: right answers from the standard library only, with its own JSON-stat decoding and hourly averaging of Energinet's 5 and 15 minute rows. Writes `eval/expected.json`.
- `eval/run_eval.py`: asks each question in a fresh conversation, scores the final `ANSWER: {...}` line, saves answers, calls, tokens and cost in `eval/results/` and `eval/results/spend.jsonl`. It refuses to start if spend plus an estimate would pass `--cap` (default 3 USD).

Right means every key is present, each number is within tolerance (0.01 for percentage points, g/kWh and EUR/MWh; 0.0001 EUR/kWh; 0.1 for percentages; 0.5 percent relative for the ratio in q04) and each hour, area or country code matches exactly. I set this before the runs.

```bash
.venv/Scripts/python eval/reference.py      # uses eval/data/, downloads only what is missing
.venv/Scripts/python eval/run_eval.py       # paid: about 0.02 USD on Haiku 5.5
```

## What did not work, or nearly

- **Guessed filter names.** Twice (Haiku, q03 and q07) the model sent a made-up dimension `band` to `fetch_series`, got a tool error, called `describe_dataset`, found `nrg_cons` with code `KWH2500-4999`, and got it right. Once (Sonnet, q06) it put the period in both the filters and `since`, got an error and retried. Each cost one round trip.
- **The rate limit sets the pace.** A dataset not in the server's 5 minute cache made the server wait about a minute. q03 to q05 took 59 to 67 s and q10 about 35 s. The rest took 4 to 10 s.
- **Server logs drowned the report.** Both servers log one INFO line per HTTP request. The agent now turns INFO logging off in them.
- **"Tomorrow" needs a date.** The system prompt now carries today's date (Danish time). At 04:00 the next day's CO2 forecast was not published, and the agent said so ([example](docs/example-run.md)).

## Limits

- 10 questions, 4 runs per model; 40 out of 40 right per model does not say every phrasing works. The grid questions use fixed past days (17 and 18 November 2026). Forecasts are not scored.
- Eurostat revises data. `expected.json` holds the values downloaded on 2026-11-19 (nrg_ind_ren updated 2026-09-15, nrg_pc_204 updated 2026-10-19). Run `eval/reference.py --refresh` before a new paid run.
- Each question names its Eurostat dataset (for example `nrg_pc_204`, band DC), because "the household price" alone has several readings. Some compare a November 2026 spot price with a 2026-S1 household price, as published.
- Day-ahead prices exclude taxes, tariffs and grid fees. Eurostat household prices include them unless the question says otherwise.
- Cost uses the list prices in `pricing.py` (cached 2026-11-03).
- The servers are pinned at commits `b7a71f7` (energidata-mcp) and `7d1aeee` (eurostat-mcp). Later fixes reach the agent only when `vendor/` is replaced and the eval rerun.

## Data sources and credit

- Energinet, [Energi Data Service](https://www.energidataservice.dk/): datasets `CO2Emis`, `CO2EmisProg` and `DayAheadPrices`, under CC BY 4.0 per its terms. Source: Energinet. Changes made: sub-hourly values averaged into hours. Energinet does not endorse this project.
- Eurostat: datasets `nrg_ind_ren` (share of renewable energy) and `nrg_pc_204` (electricity prices for household consumers, bi-annual), reused with acknowledgement per the [Eurostat copyright notice](https://ec.europa.eu/eurostat/web/main/help/copyright-notice). Eurostat bears no responsibility for this project.
- Raw API answers for the eval and offline tests: unchanged, in `eval/data/`.
- Built with the [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) and the [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/) (version 2.3).
