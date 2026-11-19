"""Ask the agent the 10 cross-source questions and score it against eval/expected.json. Paid run.

    python eval/run_eval.py                         # Haiku 5.5, all 10 questions
    python eval/run_eval.py --model claude-sonnet-5-5 --only q02,q07

Both MCP servers are started once and shared by all questions; each question is a fresh
conversation. Every paid run is added to eval/results/spend.jsonl, and a run is refused when
the money already spent plus a pessimistic estimate for this run would pass --cap.
Needs ANTHROPIC_API_KEY in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import anyio

HERE = Path(__file__).parent
ROOT = HERE.parent
RESULTS = HERE / "results"
LEDGER = RESULTS / "spend.jsonl"
sys.path.insert(0, str(ROOT / "src"))

from sustainability_data_agent.agent import ask, connect  # noqa: E402
from sustainability_data_agent.scoring import prompt_for, score  # noqa: E402

# Pessimistic cost of one question, used only for the check before a run (USD): about twice what
# the first Haiku run measured (17K input + 1K output tokens per question), priced per model.
ESTIMATE_PER_QUESTION = {"claude-haiku-5-5": 0.01, "claude-sonnet-5-5": 0.10}


def spent(ledger: Path = LEDGER) -> float:
    if not ledger.exists():
        return 0.0
    return sum(json.loads(line)["cost_usd"] for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip())


def check_budget(model: str, n_questions: int, cap: float, ledger: Path = LEDGER) -> tuple[bool, str]:
    already = spent(ledger)
    estimate = ESTIMATE_PER_QUESTION[model] * n_questions
    ok = already + estimate <= cap
    return ok, f"spent so far {already:.4f} USD, this run up to about {estimate:.2f} USD, cap {cap:.2f} USD"


async def run(questions: list[dict], expected: dict, model: str, cap: float, llm, run_name: str = "test", ledger: Path = LEDGER, servers=None) -> dict:
    records, total_in, total_out, total_cost = [], 0, 0, 0.0
    already = spent(ledger)
    async with connect(servers) as toolbox:
        for q in questions:
            if already + total_cost >= cap:
                print(f"stopping: spend cap {cap} USD reached")
                break
            answer = await ask(prompt_for(q), toolbox, llm, model=model)
            graded = score(q, expected[q["id"]], answer.text)
            total_in += answer.usage.input_tokens
            total_out += answer.usage.output_tokens
            total_cost += answer.usage.cost_usd
            ledger.parent.mkdir(exist_ok=True)
            with ledger.open("a", encoding="utf-8") as f:  # written per question, so a crash loses no spend
                f.write(json.dumps({"run": run_name, "question": q["id"], "model": model, "cost_usd": round(answer.usage.cost_usd, 6)}) + "\n")
            mark = "RIGHT" if graded["right"] else "WRONG"
            print(f"\n=== {q['id']} {mark} ===\n{answer.report()}")
            if not graded["right"]:
                for key, (got, want, ok) in graded["checks"].items():
                    if not ok:
                        print(f"  {key}: got {got!r}, expected {want!r}")
            records.append(
                {
                    "id": q["id"],
                    "kind": q["kind"],
                    "right": graded["right"],
                    "checks": {k: {"got": g, "expected": w, "ok": ok} for k, (g, w, ok) in graded["checks"].items()},
                    "answer": answer.text,
                    "stop_reason": answer.stop_reason,
                    "tool_calls": [{"name": c.name, "arguments": c.arguments, "is_error": c.is_error, "seconds": round(c.seconds, 2)} for c in answer.calls],
                    "usage": {"requests": answer.usage.requests, "input_tokens": answer.usage.input_tokens, "output_tokens": answer.usage.output_tokens, "cost_usd": round(answer.usage.cost_usd, 6)},
                    "seconds": round(answer.seconds, 1),
                }
            )
    return {
        "model": model,
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "score": sum(r["right"] for r in records),
        "asked": len(records),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": round(total_cost, 6),
        "questions": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="claude-haiku-5-5", choices=sorted(ESTIMATE_PER_QUESTION))
    parser.add_argument("--only", help="comma-separated question ids")
    parser.add_argument("--cap", type=float, default=3.0, help="total spend cap in USD across all runs")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))["questions"]
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    expected = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))["answers"]

    ok, message = check_budget(args.model, len(questions), args.cap)
    print(message)
    if not ok:
        sys.exit("refused: this run could pass the spend cap")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set")

    from anthropic import AsyncAnthropic

    out = RESULTS / f"{args.model}-{time.strftime('%Y%m%d-%H%M')}.json"
    result = anyio.run(run, questions, expected, args.model, args.cap, AsyncAnthropic(), out.name)
    RESULTS.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"\nScore {result['score']}/{result['asked']}  tokens {result['input_tokens']} in + {result['output_tokens']} out"
        f"  cost {result['cost_usd']:.4f} USD  (all runs: {spent():.4f} USD)  saved {out.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
