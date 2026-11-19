# Architecture

Line numbers point at the main function or class of each box.

## (a) Structure

One Python process. It starts the two MCP servers as child processes (unchanged pinned snapshots in `vendor/`), talks to each over stdio, and calls the Claude Messages API. Dashed arrows are test-only.

```mermaid
flowchart LR
    user["You<br/>a question"]
    cli["__main__.py<br/>command line, prints the report"]
    agent["agent.py: ask<br/>tool-use loop, turn limit, records calls"]
    box["agent.py: Toolbox<br/>6 tools, routes each call"]
    claude["Claude Messages API<br/>Haiku 5.5 or Sonnet 5.5"]
    e["energidata-mcp (pinned b7a71f7)<br/>co2_intensity, spot_price, best_hours"]
    s["eurostat-mcp (pinned 7d1aeee)<br/>search_datasets, describe_dataset, fetch_series"]
    eds["Energi Data Service API<br/>CO2Emis, DayAheadPrices"]
    est["Eurostat API<br/>JSON-stat, nrg_ind_ren, nrg_pc_204"]
    tests["tests/<br/>pytest, in-memory servers, scripted Claude"]

    user --> cli --> agent
    agent -->|"messages.create with tools"| claude
    agent -->|"call(name, args)"| box
    box -->|"stdio: tools/call"| e
    box -->|"stdio: tools/call"| s
    e -->|HTTPS| eds
    s -->|HTTPS| est
    tests -.->|"in-memory servers, no network"| box
    tests -.->|"ScriptedClaude stands in"| agent

    classDef outside fill:#eee,stroke:#888,stroke-dasharray: 4 3
    class user,claude,eds,est outside
```

| Box | File | Main function or class | What it does |
|---|---|---|---|
| Command line | `src/sustainability_data_agent/__main__.py:19` | `run` | Connects to both servers, asks one question, prints calls, answer, tokens, cost. |
| Tool-use loop | `src/sustainability_data_agent/agent.py:153` | `ask` | Sends question and tools to Claude, runs the tools it asks for, returns all results in one message. Stops at an answer, a refusal or the turn limit (12). |
| Toolbox | `src/sustainability_data_agent/agent.py:105` | `Toolbox` (`connect` at :145) | Names tools `<server>__<tool>`, routes calls. A failing call becomes error text for Claude. |
| Server commands | `src/sustainability_data_agent/agent.py:41` | `server_commands` | Starts each server with the agent's own Python. |
| Claude Messages API | outside this repository | n/a | Chooses tools, does the arithmetic, writes the answer. |
| energidata-mcp | `vendor/energidata-mcp-b7a71f7.tar.gz` | its own `docs/architecture.md` | CO2 intensity and day-ahead prices, DK1 and DK2. |
| eurostat-mcp | `vendor/eurostat-mcp-7d1aeee.tar.gz` | its own `docs/architecture.md` | Search, describe, fetch any Eurostat dataset. |
| Cost | `src/sustainability_data_agent/pricing.py:18` | `cost_usd` | Price per request from reported tokens. |
| Tests | `tests/conftest.py` | `offline` fixture | Real servers in memory, API calls answered from `eval/data/`. |

## (b) One question, two servers

q02: "What percentage of the Danish household electricity price (Eurostat) was the mean DK1 spot price on 17 November 2026 (Energi Data Service)?" Parallel tool calls run in turn; all results go back in one message.

```mermaid
sequenceDiagram
    participant A as agent.py (ask)
    participant C as Claude Messages API
    participant T as Toolbox
    participant E as energidata-mcp
    participant S as eurostat-mcp

    A->>C: question + 6 tool definitions
    C-->>A: tool_use energidata__spot_price(DK1, 2026-11-17, EUR)
    C-->>A: tool_use eurostat__fetch_series(nrg_pc_204, geo DK, band DC, I_TAX, 2026-S1)
    A->>T: call energidata__spot_price
    T->>E: tools/call spot_price
    E-->>T: 24 hourly prices, mean_of_hours
    A->>T: call eurostat__fetch_series
    T->>S: tools/call fetch_series
    S-->>T: rows with value in EUR/kWh
    A->>C: both tool_result blocks in one user message
    Note over C: converts units, divides, writes the ANSWER line
    C-->>A: end_turn with the answer text
    Note over A: report: 2 tool calls, answer, tokens, cost
```

`ask` (`agent.py:153`) calls `messages.create` and keeps the full assistant content, thinking blocks included. `Toolbox.call` (in `Toolbox` at :105) splits `energidata__spot_price` into server and tool and returns the JSON as text. In the eval, `score` (`src/sustainability_data_agent/scoring.py:50`) compares each key of the final `ANSWER: {...}` line with `eval/expected.json` within its tolerance.

## (c) The eval around it

```mermaid
flowchart LR
    q["eval/questions.json<br/>10 questions, keys, tolerances"]
    ref["eval/reference.py<br/>standard library, own decoder"]
    raw["eval/data/<br/>raw API answers, saved once"]
    exp["eval/expected.json<br/>right answers"]
    run["eval/run_eval.py<br/>agent per question, spend cap"]
    res["eval/results/<br/>answers, tool calls, tokens, cost"]

    ref -->|"downloads once"| raw
    ref --> exp
    q --> run
    exp --> run
    run --> res
```

The reference script shares no code with the servers. The offline tests replay `eval/data/` through the real servers and check that every reference answer is reachable (`tests/test_cross_source.py`), so a miss in the paid eval belongs to the model.
