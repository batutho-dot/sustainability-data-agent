# Reference answers without a model

**For the user:** the right answers to the 10 questions, computed by a plain script from the
same public APIs, so the agent's score means something.

**How to reach it:** `python eval/reference.py` (downloads only what is missing in `eval/data/`).

**How verify drives it:** step `reference` recomputes all answers from `eval/data/` with the
network blocked and compares with `eval/expected.json` (known-good copy). Nothing is written.

**Gotchas:** `--refresh` downloads again; Eurostat revises data, so new downloads may change
`expected.json`. Energi Data Service rate-limits to about one call a minute.
