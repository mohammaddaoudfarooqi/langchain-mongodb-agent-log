# How to use the agent log with `create_react_agent` (legacy)

Goal: capture super-steps in graphs whose specialists are
`langgraph.prebuilt.create_react_agent` rather than the modern
`langchain.agents.create_agent`.

`create_react_agent` does not accept the `AgentMiddleware` argument. The
adapter that works is `AgentLogCallbackHandler` at the graph root —
exactly the same pattern as bare-`StateGraph` graphs.

## When to migrate

If you can switch to `create_agent`, do that first. The modern API
gives you per-agent middleware, structured output, and better
tool-call validation. See the `mongodb-langchain-agentic-ai` repo's
[MODERNIZE.md](https://github.com/mongodb-labs/mongodb-langchain-agentic-ai/blob/main/MODERNIZE.md)
for a step-by-step migration of two specific files.

If you can't migrate (yet), this page covers the bridge.

## The pattern

```python
from langgraph.prebuilt import create_react_agent
from langgraph.graph import StateGraph, START, END
from langchain_mongodb_agent_log import AgentLog, AgentLogCallbackHandler

log = AgentLog(collection=db["agent_log"], embeddings=embedder)
handler = AgentLogCallbackHandler(log, user_id="alice")

# Specialist agents (legacy API)
data_agent = create_react_agent(model, tools=[...], prompt="...")
search_agent = create_react_agent(model, tools=[...], prompt="...")

def data_node(state, config):
    return data_agent.invoke({"messages": state["messages"]}, config=config)

def search_node(state, config):
    return search_agent.invoke({"messages": state["messages"]}, config=config)

# Graph composition (unchanged)
builder = StateGraph(MyState)
builder.add_node("data", data_node)
builder.add_node("search", search_node)
# ... supervisor + edges

graph = builder.compile()

graph.invoke(
    {"messages": [...]},
    config={
        "configurable": {"thread_id": "t1", "user_id": "alice"},
        "callbacks": [handler],
    },
)
```

Each top-level node end fires `on_chain_end` with the matching
`metadata["langgraph_node"]` set on the prior `on_chain_start`. The
handler stamps the doc with `agent_name = node_name`.

## What you give up vs. middleware

- **No per-agent guardrails**, since middleware doesn't run. If you want
  to gate a `data_agent`'s tool calls, that gating has to happen inside
  the node function or via a wrapper.
- **No structured-output integration.** `response_format=` is a
  `create_agent` feature.

For the agent log specifically, callback parity is fine — the doc
shape, `agent_name` attribution, hybrid search, and per-user
retrieval all work identically.
