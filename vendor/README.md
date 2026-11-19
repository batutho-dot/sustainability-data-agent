# Pinned MCP servers

The agent depends on two MCP servers from the same author. Both are installed from snapshots of
one fixed commit each, so an upgrade in either repository cannot change this agent's behaviour
until the snapshot here is replaced on purpose.

| File | Repository | Commit | Contents |
|---|---|---|---|
| `energidata-mcp-b7a71f7.tar.gz` | energidata-mcp | `b7a71f78aabcaf4739a02f5d93aa09f2cd78796c` | `pyproject.toml`, `README.md`, `LICENSE`, `src/` |
| `eurostat-mcp-7d1aeee.tar.gz` | eurostat-mcp | `7d1aeee0b5c96f7aae0cd3a9070e29afb264c746` | `pyproject.toml`, `README.md`, `src/` |

Made with:

```bash
git -C ../energidata-mcp archive --format=tar.gz --prefix=energidata-mcp/ -o vendor/energidata-mcp-b7a71f7.tar.gz b7a71f7 pyproject.toml README.md LICENSE src
git -C ../eurostat-mcp archive --format=tar.gz --prefix=eurostat-mcp/ -o vendor/eurostat-mcp-7d1aeee.tar.gz 7d1aeee pyproject.toml README.md src
```

To move to a newer server version: make a new snapshot the same way, update `requirements.txt`,
rerun `python eval/reference.py` and `pytest`, then the paid eval.
