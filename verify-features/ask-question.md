# Ask one cross-source question

**For the user:** type a question in plain words, get an answer built from Danish grid data and
Eurostat statistics, with every tool call printed, plus tokens and cost.

**How to reach it:** `python -m sustainability_data_agent "question"` (needs ANTHROPIC_API_KEY).

**How verify drives it:** not live (that costs money). `tests/test_agent.py` runs `ask()` with
`ScriptedClaude`, a stand-in that asks for one tool on each server, then answers. Input: question
q01's tool calls. End state: 2 recorded calls, both tool results in one user message, usage
summed, the report lists both calls.

**Gotchas:** the live path depends on the model; only the paid eval measures that. Server
log lines go to stderr and are mixed into the terminal output.
