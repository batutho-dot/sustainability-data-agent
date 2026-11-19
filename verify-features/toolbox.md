# Both servers behind one toolbox

**For the user:** one list of six tools from two MCP servers, each call routed to its server.

**How to reach it:** `connect()` in `src/sustainability_data_agent/agent.py`.

**How verify drives it:** step `stdio` starts both pinned servers as child processes over stdio
and lists the tools; known-good list: the six names in `verify.py` (`KNOWN_TOOLS`). Tests also
call every tool in memory against saved API answers (`tests/test_cross_source.py`) and send bad
calls (unknown tool, bad date, unknown dataset) that must come back as errors, not crashes.

**Gotchas:** listing tools touches no network. A changed server snapshot that renames a tool
fails the stdio step on purpose.
