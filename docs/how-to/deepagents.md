# How to wire `langchain-mongodb-agent-log` into deepagents

Goal: persist every super-step of a `create_deep_agent` agent.

## Steps

```python
from deepagents import create_deep_agent
from langchain_mongodb_agent_log import AgentLog, AgentLogMiddleware

log = AgentLog(collection=db["agent_log"], embeddings=embedder)

agent = create_deep_agent(
    model=...,
    tools=[...],
    instructions="...",
    middleware=[AgentLogMiddleware(log)],
)
```

deepagents uses `create_agent` under the hood, so the middleware works
without modification.

## What lands on the doc

- **`messages`** — full message log for the super-step (verbatim).
- **`todos`** — deepagents' planner-managed todo list, projected to
  `{id, content, status}`.
- **`files_touched`** — derived from `write_file` / `edit_file` tool
  calls in the super-step. Read-only tools (`read_file`, `ls`, `glob`,
  `grep`) are filtered out.

## See also

- [`fs_write_tools` configuration](../reference/configuration.md) — to
  customize which tool names count as filesystem writes.
- [Architecture](../explanation/architecture.md) — why `files_touched`
  comes from tool calls rather than graph state.
