# How to wire the agent log into a multi-agent supervisor

Goal: in a graph with a supervisor and N worker agents, get one log
document per worker per super-step, attributed by `agent_name`.

## When to use which adapter

| Worker type | Adapter | Where it goes |
|---|---|---|
| `create_agent` instance | `AgentLogMiddleware` | On the worker, in `middleware=[...]` |
| Hand-rolled node calling `llm.invoke` | `AgentLogCallbackHandler` | At graph invocation, in `config["callbacks"]` |
| Mix of both | Both | Middleware on each `create_agent` worker; callback at the graph root for the raw nodes |

## Pattern: `create_agent` workers behind a `StateGraph` supervisor

```python
from langgraph.graph import StateGraph, START, END
from langchain.agents import create_agent
from langchain_mongodb_agent_log import AgentLog, AgentLogMiddleware

log = AgentLog(collection=db["agent_log"], embeddings=embedder)

researcher = create_agent(
    model=..., tools=[...],
    middleware=[AgentLogMiddleware(log)],
    name="researcher",
)
writer = create_agent(
    model=..., tools=[...],
    middleware=[AgentLogMiddleware(log)],
    name="writer",
)

def _researcher_node(state, config):
    cfg = {
        **config,
        "configurable": {**config.get("configurable", {}), "agent_name": "researcher"},
    }
    return researcher.invoke({"messages": state["messages"]}, config=cfg)

def _writer_node(state, config):
    cfg = {
        **config,
        "configurable": {**config.get("configurable", {}), "agent_name": "writer"},
    }
    return writer.invoke({"messages": state["messages"]}, config=cfg)

builder = StateGraph(MyState)
builder.add_node("researcher", _researcher_node)
builder.add_node("writer", _writer_node)
builder.add_edge(START, "researcher")
builder.add_edge("researcher", "writer")
builder.add_edge("writer", END)
graph = builder.compile()
```

The trick is injecting `configurable["agent_name"]` per node. Each
worker's middleware reads it from the active `RunnableConfig` and
stamps it on the doc.

## Querying per agent

```python
db["agent_log"].count_documents({"agent_name": "researcher", "user_id": "alice"})
```

Indexes on `(thread_id, ts DESC)` and `(user_id, ts DESC)` cover
typical filter-and-sort access patterns; for `agent_name` filters on
hot threads, add a compound index in your application's bootstrap.

## Caveats

- **Supervisor as a hand-rolled node.** Use `AgentLogCallbackHandler`
  at graph invocation to capture supervisor steps. See
  [bare-stategraph.md](bare-stategraph.md).
- **Send-based dispatch.** When the supervisor uses `Send(...)` to
  spawn a worker, propagate `agent_name` in the `Send.config`'s
  `configurable` so the dispatched worker knows who it is.
