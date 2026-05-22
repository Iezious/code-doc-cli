# code_index — usage

The agent-facing usage manual ships inside the wheel. Read it at runtime via the CLI:

- `code_index usage` — index page (the 9-topic catalog).
- `code_index usage <topic>` — one of `init`, `index-build`, `index-sync`, `index-rebuild`, `search`, `symbols`, `graph`, `config-show`.
- `code_index --format json usage [<topic>]` — same content as `{"topic", "content", "available"}`.

In-tree source: [`src/code_index/usage/USAGE.md`](src/code_index/usage/USAGE.md).
