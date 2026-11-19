# Feature map

What the repository does for its user, and how `verify.py` drives each part.

| Feature | File | Driven by verify |
|---|---|---|
| Ask one cross-source question | [ask-question.md](ask-question.md) | partly: tests with a scripted Claude; the live command is paid and not run |
| Both servers behind one toolbox | [toolbox.md](toolbox.md) | yes: stdio step and tests |
| Reference answers without a model | [reference.md](reference.md) | yes: reference step |
| Paid eval with spend cap | [eval-run.md](eval-run.md) | partly: tests drive `run()` with a scripted Claude and the budget check |
