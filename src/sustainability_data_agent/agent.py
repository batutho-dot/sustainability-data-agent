"""A small agent that answers questions with two MCP servers at once.

The agent starts both servers (energidata-mcp and eurostat-mcp) as MCP clients, offers all
their tools to Claude through the Messages API, and runs the tool-use loop itself: Claude asks
for a tool, the agent calls it on the right server, the result goes back, until Claude answers.
Every tool call is recorded, with its arguments, the server that ran it and how long it took.
"""

from __future__ import annotations

import json
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

from mcp import Client, StdioServerParameters

from .pricing import cost_usd

DEFAULT_MODEL = "claude-haiku-5-5"
SEPARATOR = "__"  # tool names reach Claude as "<server>__<tool>", e.g. "energidata__best_hours"
MAX_RESULT_CHARS = 60_000  # a tool result longer than this is cut, and the cut is said in the text

SYSTEM = """You answer questions about energy and electricity in Denmark and the EU.
You have tools from two servers:
- energidata__*: Energinet's Energi Data Service. Hourly CO2 intensity (g/kWh) and day-ahead spot
  prices (DKK or EUR per MWh) for the Danish price areas DK1 (West) and DK2 (East). Times are
  Danish local time; a window's end is exclusive and defaults to the next midnight.
- eurostat__*: Eurostat statistics. Use describe_dataset to see a dataset's dimension codes,
  then fetch_series with filters. Eurostat geo codes are two letters (DK, DE, EL for Greece);
  the EU27 aggregate is EU27_2020.
Get every number from a tool; never from memory. Use the most precise value a tool returns
(for a day mean use the tool's mean_of_hours, not a mean of rounded hours). Check units before
combining sources: 1 EUR/MWh = 0.001 EUR/kWh. Show the arithmetic in one or two lines.
If the question asks for an ANSWER line, end with exactly one line:
ANSWER: {json object with the requested keys}"""


def server_commands() -> dict[str, StdioServerParameters]:
    """How to start each server: the installed packages, with the same Python as this agent.

    INFO log lines (one per HTTP request) are switched off so they do not drown the report;
    warnings and errors still reach the terminal.
    """
    quiet = "import logging; logging.disable(logging.INFO); "
    return {
        "energidata": StdioServerParameters(
            command=sys.executable, args=["-c", quiet + "from energidata_mcp.server import main; main()"]
        ),
        "eurostat": StdioServerParameters(
            command=sys.executable, args=["-c", quiet + "from eurostat_mcp.server import main; main()"]
        ),
    }


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    is_error: bool
    seconds: float
    result_chars: int

    def line(self) -> str:
        args = json.dumps(self.arguments, ensure_ascii=False, separators=(",", "="))
        flag = "  [tool error]" if self.is_error else ""
        return f"{self.name}({args[1:-1]})  {self.seconds:.1f} s{flag}"


@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, model: str, usage: Any) -> None:
        inp = usage.input_tokens or 0
        out = usage.output_tokens or 0
        self.requests += 1
        self.input_tokens += inp
        self.output_tokens += out
        self.cost_usd += cost_usd(model, inp, out)


@dataclass
class Answer:
    question: str
    text: str
    stop_reason: str | None
    calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    seconds: float = 0.0

    def report(self) -> str:
        lines = [f"Q: {self.question}", "", f"Tool calls ({len(self.calls)}):"]
        lines += [f"  {i}. {c.line()}" for i, c in enumerate(self.calls, 1)] or ["  (none)"]
        lines += [
            "",
            self.text,
            "",
            f"[{self.usage.requests} model requests, {self.usage.input_tokens} input + "
            f"{self.usage.output_tokens} output tokens, {self.usage.cost_usd:.4f} USD, {self.seconds:.0f} s]",
        ]
        return "\n".join(lines)


class Toolbox:
    """The tools of several connected MCP servers, under one namespace."""

    def __init__(self, clients: dict[str, Client]):
        self.clients = clients
        self.definitions: list[dict[str, Any]] = []

    async def load(self) -> "Toolbox":
        for server, client in self.clients.items():
            listed = await client.list_tools()
            for tool in listed.tools:
                self.definitions.append(
                    {
                        "name": f"{server}{SEPARATOR}{tool.name}",
                        "description": (tool.description or "").strip()[:1024] or tool.name,
                        "input_schema": tool.input_schema,
                    }
                )
        return self

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Run one tool. Returns (text for Claude, is_error). Never raises for a bad call."""
        server, _, tool = name.partition(SEPARATOR)
        client = self.clients.get(server)
        if client is None or not tool:
            return f"Unknown tool {name!r}.", True
        try:
            result = await client.call_tool(tool, arguments)
        except Exception as exc:  # transport or protocol failure: tell the model, keep going
            return f"Tool {name} failed: {type(exc).__name__}: {exc}", True
        if result.structured_content is not None and not result.is_error:
            text = json.dumps(result.structured_content, ensure_ascii=False)
        else:
            text = "\n".join(getattr(block, "text", "") for block in result.content) or "(empty result)"
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"\n[cut: result was {len(text)} characters; filter the request]"
        return text, bool(result.is_error)


@asynccontextmanager
async def connect(servers: dict[str, Any] | None = None) -> AsyncIterator[Toolbox]:
    """Connect to every server (stdio by default; tests pass in-memory servers) and load the tools."""
    servers = servers if servers is not None else server_commands()
    async with AsyncExitStack() as stack:
        clients = {name: await stack.enter_async_context(Client(target)) for name, target in servers.items()}
        yield await Toolbox(clients).load()


async def ask(
    question: str,
    toolbox: Toolbox,
    llm: Any,
    model: str = DEFAULT_MODEL,
    max_turns: int = 12,
    max_tokens: int = 16000,
) -> Answer:
    """Run the tool-use loop for one question. `llm` is an anthropic.AsyncAnthropic client."""
    started = time.monotonic()
    today = datetime.now(ZoneInfo("Europe/Copenhagen")).strftime("%A %Y-%m-%d")
    answer = Answer(question=question, text="", stop_reason=None)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    for _ in range(max_turns):
        response = await llm.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=f"{SYSTEM}\nToday is {today} (Danish time).",
            tools=toolbox.definitions,
            messages=messages,
        )
        answer.usage.add(model, response.usage)
        answer.stop_reason = response.stop_reason
        # Keep the whole content (thinking blocks included) so the next request is valid.
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            answer.text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "refusal":
                answer.text = answer.text or "(the model declined to answer)"
            break
        results = []
        for block in tool_uses:
            t0 = time.monotonic()
            text, is_error = await toolbox.call(block.name, dict(block.input or {}))
            answer.calls.append(ToolCall(block.name, dict(block.input or {}), is_error, time.monotonic() - t0, len(text)))
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    else:
        answer.text = f"(stopped after {max_turns} model turns without a final answer)"
        answer.stop_reason = "max_turns"
    answer.seconds = time.monotonic() - started
    return answer
