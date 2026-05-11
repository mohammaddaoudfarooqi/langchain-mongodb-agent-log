# How to wire the agent log into a bare `StateGraph`

Goal: capture per-node super-steps in a graph whose nodes are
hand-written functions calling `llm.invoke` directly (no
`create_agent`).

This is the canonical shape of repos like
[`mongodb-langchain-agentic-ai`](https://github.com/mongodb-labs/mongodb-langchain-agentic-ai),
where the supervisor and most specialists are explicit `StateGraph`
nodes.

## Use the callback adapter

Middleware doesn't apply here — there's no `create_agent` runtime to
host it. Use `AgentLogCallbackHandler` instead.

```python
from langgraph.graph import StateGraph, START, END
from langchain_mongodb_agent_log import AgentLog, AgentLogCallbackHandler

log = AgentLog(collection=db["agent_log"], embeddings=embedder)
handler = AgentLogCallbackHandler(log, user_id="alice")
# ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
# Pass user_id here OR via config["metadata"]["user_id"] at invocation.
# LangGraph elevates ``thread_id`` to the callback metadata
# automatically, but does NOT elevate ``user_id``.

builder = StateGraph(MyState)
builder.add_node("supervisor", supervisor_node)
builder.add_node("research", research_node)
# ... edges as usual

graph = builder.compile()

graph.invoke(
    {"messages": [...]},
    config={
        "configurable": {"thread_id": "t1", "user_id": "alice"},
        "callbacks": [handler],
    },
)
```

The handler hooks `on_chain_start` (where LangGraph stamps
`metadata["langgraph_node"]`) and pairs it with `on_chain_end` keyed
by `run_id`. It only writes documents for top-level graph nodes; it
ignores inner Runnables (per-LLM-call, per-tool-call events).

## Mixing with `create_agent` workers

If some nodes are `create_agent` instances and others are raw, attach
**middleware on each `create_agent`** AND **the callback at graph root**:

```python
agent_log_middleware = AgentLogMiddleware(log)
worker = create_agent(model=..., tools=[...], middleware=[agent_log_middleware], name="worker")

# raw supervisor node
def supervisor_node(state, config):
    out = sup_model.invoke(state["messages"])
    return {"messages": [*state["messages"], out]}

builder.add_node("supervisor", supervisor_node)
builder.add_node("worker", lambda s, c: worker.invoke(...))

graph.invoke(
    {"messages": [...]},
    config={
        "configurable": {"thread_id": "t1", "user_id": "alice"},
        "callbacks": [AgentLogCallbackHandler(log, user_id="alice")],
    },
)
```

Yes, this means the worker's super-steps fire **both** middleware (one
write per inner step) and callback (one write per outer node end). For
v0.1 we accept the duplicate; v0.2 may add a deduplication mode keyed
on `(thread_id, step)`.

## Why pass `user_id` to the handler?

LangGraph's per-node callback metadata only includes `thread_id`,
`langgraph_node`, `langgraph_step`, and `langgraph_path`. `user_id`
stays in `configurable` where the callback can't reach it. We accept
`user_id` on the handler as the cleanest alternative to spelunking into
context vars from inside a callback (which doesn't reliably work).
