# Paid eval with spend cap

**For the user:** the agent's score out of 10, tokens and cost, with every answer and tool call
saved in `eval/results/`.

**How to reach it:** `python eval/run_eval.py [--model claude-sonnet-5-5] [--only q02] [--cap 3]`.

**How verify drives it:** tests run `run()` on question q01 with a scripted Claude and in-memory
servers (end state: score 1/1, ledger total equals the run cost) and check that the budget check
refuses a run that could pass the cap.

**Gotchas:** the real run calls the Claude API and costs money; verify never runs it.
