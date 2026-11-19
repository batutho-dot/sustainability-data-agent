"""Ask the agent one question from the command line.

    python -m sustainability_data_agent "Compare Denmark's renewable share with the EU average"
    python -m sustainability_data_agent --model claude-sonnet-5-5 "..."

Needs ANTHROPIC_API_KEY in the environment. Prints the tool calls, the answer, tokens and cost.
"""

from __future__ import annotations

import argparse
import sys

import anyio
from anthropic import AsyncAnthropic

from .agent import DEFAULT_MODEL, ask, connect


async def run(question: str, model: str) -> None:
    async with connect() as toolbox:
        answer = await ask(question, toolbox, AsyncAnthropic(), model=model)
    print(answer.report())


def main() -> None:
    parser = argparse.ArgumentParser(prog="sustainability-data-agent", description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=["claude-haiku-5-5", "claude-sonnet-5-5"])
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # answers may hold symbols a Windows console code page lacks
    anyio.run(run, args.question, args.model)


if __name__ == "__main__":
    main()
