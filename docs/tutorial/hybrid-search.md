# Tutorial: hybrid search

You'll add the `search_past_conversations` tool so your agent can recall
its own prior conversations across threads. By the end you'll be running
queries that fuse vector similarity with lexical match, scoped per user.

This builds on [first-log.md](first-log.md). Make sure that tutorial
worked first.

## What you'll learn

- How to build the prebuilt `search_past_conversations` tool.
- Why per-user scoping is enforced through `RunnableConfig`, not
  function arguments.
- How the RRF retriever combines `$search` and `$vectorSearch`.

## Prerequisites

- The collection from `first-log.md` with at least 5–10 documents
  written. Run a few extra agent turns to seed it if you have only one.
- Confirm the search indexes are queryable:
  ```python
  for idx in db["agent_log"].list_search_indexes():
      print(idx["name"], idx.get("status"), idx.get("queryable"))
  ```
  Both `agent_log_search_idx` and `agent_log_vector_idx` should be
  `READY` and `queryable=True`.

## 1. Build a recall-capable agent

```python
import os
from langchain.agents import create_agent
from langchain_mongodb_agent_log import (
    AgentLog,
    AgentLogMiddleware,
    default_voyage,
)
from langchain_mongodb_agent_log.retrieval.tool import build_tool
from pymongo import MongoClient

db = MongoClient(os.environ["MONGODB_URI"]).my_app
embedder = default_voyage()
log = AgentLog(collection=db["agent_log"], embeddings=embedder)

# The tool is BOUND to a specific collection + embedder. The agent
# receives only ``query`` as input — ``user_id`` is read from
# RunnableConfig at runtime so the agent cannot spoof another user.
recall = build_tool(db["agent_log"], embeddings=embedder, top_k=3)

agent = create_agent(
    model="anthropic:claude-haiku-4-5",
    tools=[recall],
    middleware=[AgentLogMiddleware(log)],
    system_prompt=(
        "You have a `search_past_conversations` tool. When the user "
        "asks you to recall something, call it before answering."
    ),
)
```

## 2. Trigger a recall

```python
result = agent.invoke(
    {"messages": [{"role": "user", "content": "What was my first question?"}]},
    config={"configurable": {"thread_id": "recall_demo", "user_id": "alice"}},
)
print(result["messages"][-1].content)
log.flush_for_tests()
```

The agent should pick up the tool, fire it with a query like
`"first question alice asked"`, and weave the result into its reply. The
tool returns a JSON list with `thread_id`, `step`, `ts`, `snippet`,
`agent_name`, and `model_id`.

## 3. Why `user_id` doesn't appear in the tool's input schema

Look at the tool's schema:

```python
from langchain_mongodb_agent_log.retrieval.tool import build_tool

tool = build_tool(db["agent_log"], embeddings=embedder)
print(tool.args_schema.schema())
```

The only required argument is `query`. The tool reads `user_id` from
`RunnableConfig.configurable` because giving the agent the ability to
pass `user_id` would let it ask "what did *bob* talk about?" — a hard
no. Per-user scoping is an invariant; the package enforces it at the
API surface.

## 4. What hybrid search means here

`AgentLogRetriever` wraps `MongoDBAtlasHybridSearchRetriever`, which
issues two queries in parallel:

- **`$vectorSearch`** over `agent_log_embedding`. Captures semantic
  similarity even when the words don't match.
- **`$search`** over `agent_log_text`. Captures keyword matches even
  when the embedding similarity is weak.

Reciprocal-rank fusion (RRF) combines them. You don't write any
aggregation pipeline by hand — the package's retriever does it.

## What just happened

The agent now has read access to its user's full conversation history,
ranked by RRF, in-loop. Every new turn the agent fires through
`AgentLogMiddleware` extends that history; every recall query reads it
back through `search_past_conversations`. Two halves of the same
self-referential loop.

## Where to go next

- [Reference: document shape](../reference/document-shape.md) — see
  what fields ranking can use.
- [Explanation: architecture](../explanation/architecture.md) — why
  embedding only fires on the final super-step.
- [How-to: provide custom embeddings](../how-to/provide-custom-embeddings.md)
  — swap Voyage for OpenAI / Bedrock / local models.
