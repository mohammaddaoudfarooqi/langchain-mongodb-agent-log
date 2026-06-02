# How to attribute subagents (deepagents) in the log

By default every log document records `agent_name="main"`. In a multi-agent
setup — e.g. a deepagents planner that delegates to a `researcher` and a
`writer` subagent — you usually want each subagent's super-steps attributed to
its own name so you can build `agent_name` forensics.

## Why config threading doesn't work for deepagents

deepagents invokes subagents through the library-owned `task` tool, which calls
`subagent.invoke(state)` **without** a per-subagent config seam. So you cannot
set `configurable["agent_name"]` per subagent, and a root
`AgentLogCallbackHandler` would mis-attribute (subagents run as *inner*
Runnables, not top-level graph nodes) and double-write alongside the main
agent's middleware.

## The seam: a per-subagent middleware with a constructor `agent_name`

`AgentLogMiddleware(log, agent_name="researcher")` hardcodes the attribution
for whichever agent it is attached to. The constructor value beats
`configurable["agent_name"]`. Attach one to each subagent's
`middleware=[...]` list and the unconditional one to the main agent:

```python
from langchain_mongodb_agent_log import AgentLog, AgentLogMiddleware

log = AgentLog(collection=db["agent_log"], embeddings=voyage)

researcher = create_agent(
    model=..., tools=[...],
    middleware=[AgentLogMiddleware(log, agent_name="researcher")],
    name="researcher",
)
writer = create_agent(
    model=..., tools=[...],
    middleware=[AgentLogMiddleware(log, agent_name="writer")],
    name="writer",
)

main = create_deep_agent(
    model=..., tools=[...],
    subagents=[researcher, writer],
    middleware=[AgentLogMiddleware(log)],   # records agent_name="main"
)
```

Now `db.agent_log.distinct("agent_name")` returns
`["main", "researcher", "writer"]`, and `search_past_conversations` / the
`AgentLogRetriever` can scope a structured `$search` by `agent_name` (the
search index maps it).

## Caveat: `parent_step` is per-thread, not a delegation pointer

`parent_step` is `step - 1` within a `thread_id`, shared across all agents on
that thread. It is **not** a causal pointer from a subagent step back to the
delegating main-agent step. Use `agent_name` + `ts` ordering for forensics;
use `correlation_id` to join a turn across systems.
