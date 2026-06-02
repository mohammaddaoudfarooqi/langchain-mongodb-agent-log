# langchain-mongodb-agent-log

A queryable, hybrid-searchable activity log for LangChain agents, persisted in
MongoDB Atlas — drop-in via a middleware or callback adapter.

[![CI](https://github.com/mongodb-partners/langchain-mongodb-agent-log/actions/workflows/ci.yml/badge.svg)](https://github.com/mongodb-partners/langchain-mongodb-agent-log/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## What problem this solves

Your agent has been running for weeks. A user asks:
**"can you tell me what I asked your bot last week?"**

Your existing tools each fall short:

- **`MongoDBSaver` / LangGraph checkpoint** — opaque msgpack BSON. Can't
  grep it, can't search it, can't let the agent recall it.
- **LangSmith** — fine engineering UI, but the public retrieval API is
  metadata filter + 250-char truncated substring search. No semantic
  similarity. Data lives in LangChain Inc.'s SaaS.
- **`MongoDBChatMessageHistory`** — closer, but no per-user enforcement,
  no hybrid search, no `tool_calls` / todos / files-touched metadata.
- **DIY** — ~1100 LOC across worker thread, index DDL, RRF retriever,
  ContextVar scoping, and the test suite that proves it works.

This package is the **fifth option**: a queryable, hybrid-searchable,
per-user-scoped agent activity log in your existing MongoDB Atlas
cluster, drop-in via a middleware or callback adapter.

```
agent ──▶ AgentLogMiddleware ──▶ AgentLog (engine) ──▶ MongoDB Atlas
                                                       │
                                                       ▼
agent ◀── search_past_conversations ◀── AgentLogRetriever (RRF, per-user)
```

→ **[Full motivation, comparisons, and decision rubric](docs/explanation/why-this-exists.md)**

## What you get in three claims

1. **Decoded JSON in your DB.** Open Compass, run an aggregation, build
   a dashboard. `messages`, `tool_calls`, `todos`, `files_touched`,
   `agent_name`, `correlation_id` — all queryable.
2. **Hybrid retrieval the agent itself can call.** RRF fusion of
   `$search` + `$vectorSearch`, scoped per `user_id` via mandatory
   pre-filter. One `pip install` plus three lines of wiring.
3. **Fire-and-forget, multi-tenant safe.** Daemon-thread worker keeps
   the agent's hot path non-blocking. ContextVar-based `user_id`
   scoping (v0.2+) makes one shared handler safe across concurrent
   users.

## What this is NOT

- **Not a LangGraph checkpointer.** Cannot resume execution. Run
  `MongoDBSaver` alongside this; they're orthogonal.
- **Not LangSmith.** Doesn't ship an engineering UI, run-diff/replay,
  or eval datasets. Run LangSmith alongside this; complementary.
- **Not a knowledge-base store.** This stores the *conversation*, not
  curated content.

## 60-second quickstart

```bash
pip install langchain-mongodb-agent-log
```

```python
from langchain.agents import create_agent
from langchain_mongodb_agent_log import (
    AgentLog,
    AgentLogMiddleware,
    default_voyage,
    ensure_agent_log_indexes,
    ensure_search_indexes,
)
from pymongo import MongoClient

db = MongoClient("mongodb+srv://...").my_app

# One-time setup (idempotent on re-run).
ensure_agent_log_indexes(db["agent_log"])
ensure_search_indexes(db["agent_log"], embeddings_dim=1024)

# Per-process setup.
log = AgentLog(collection=db["agent_log"], embeddings=default_voyage())

agent = create_agent(
    model="anthropic:claude-haiku-4-5",
    tools=[...],
    middleware=[AgentLogMiddleware(log)],
)

agent.invoke(
    {"messages": [{"role": "user", "content": "Hello"}]},
    config={"configurable": {"thread_id": "t1", "user_id": "alice"}},
)
```

That's it. One document per super-step lands in `db["agent_log"]`. The
final reply of each turn carries `agent_log_text` + `agent_log_embedding`
fields ready for hybrid search.

## Decision rubric — do you need this?

| If you need... | Reach for... |
|---|---|
| Resume after crash, time travel, branch | `MongoDBSaver` |
| Engineering trace UI, run diff, eval datasets | LangSmith |
| Curated knowledge corpus retrieval | `MongoDBAtlasVectorSearch` over your KB |
| **Conversation memory the agent itself queries in-loop** | **This package** |
| **Audit log of what the agent said and did, queryable in MQL** | **This package** |
| **Multi-tenant async server with one shared handler** | **This package** (v0.2+ `scoped_user`) |

Most teams run several of these together. They're orthogonal, not
substitutes.

## Where to go next

| If you want to... | Read |
|---|---|
| Understand *why* this package exists vs. alternatives | [`docs/explanation/why-this-exists.md`](docs/explanation/why-this-exists.md) |
| Walk from zero to a working agent log | [`docs/tutorial/first-log.md`](docs/tutorial/first-log.md) |
| Add agent self-recall via hybrid search | [`docs/tutorial/hybrid-search.md`](docs/tutorial/hybrid-search.md) |
| Wire it into a `create_agent` agent | [`docs/how-to/create-agent.md`](docs/how-to/create-agent.md) |
| Wire it into deepagents | [`docs/how-to/deepagents.md`](docs/how-to/deepagents.md) |
| Multi-agent supervisor + workers | [`docs/how-to/multi-agent-supervisor.md`](docs/how-to/multi-agent-supervisor.md) |
| Bare `StateGraph` (the agentic-ai shape) | [`docs/how-to/bare-stategraph.md`](docs/how-to/bare-stategraph.md) |
| Migrate from `create_react_agent` | [`docs/how-to/migrate-from-create-react-agent.md`](docs/how-to/migrate-from-create-react-agent.md) |
| Per-user scoping in a multi-user server (v0.2+) | [`docs/how-to/per-user-scoping-with-contextvar.md`](docs/how-to/per-user-scoping-with-contextvar.md) |
| TTL-based retention | [`docs/how-to/configure-ttl.md`](docs/how-to/configure-ttl.md) |
| Plug in OpenAI / Bedrock / your own embedder | [`docs/how-to/provide-custom-embeddings.md`](docs/how-to/provide-custom-embeddings.md) |
| API surface, every public name | [`docs/reference/api.md`](docs/reference/api.md) |
| Persisted document schema | [`docs/reference/document-shape.md`](docs/reference/document-shape.md) |
| Atlas index DDL | [`docs/reference/indexes.md`](docs/reference/indexes.md) |
| Constructor knobs and defaults | [`docs/reference/configuration.md`](docs/reference/configuration.md) |
| How the engine + adapters fit together | [`docs/explanation/architecture.md`](docs/explanation/architecture.md) |
| Why this isn't a checkpointer (deep dive) | [`docs/explanation/why-not-checkpointer.md`](docs/explanation/why-not-checkpointer.md) |
| How it fits next to LangSmith | [`docs/explanation/langsmith-comparison.md`](docs/explanation/langsmith-comparison.md) |

The full doc index: [`docs/README.md`](docs/README.md).

## Compatibility

- Python 3.11+
- `langchain >= 0.3.27`, `langchain-core >= 0.3`, `langgraph >= 0.3`,
  `langchain-mongodb >= 0.11`, `pymongo >= 4.6`.
- MongoDB Atlas with Search + Vector Search indexes (the search
  features are generally available on community editions where Search
  is enabled; storage works on any MongoDB).
- Voyage AI (`langchain-voyageai`) ships as a core dependency and powers
  the default embedder; you may still pass any `Embeddings` instance.

## License

Apache-2.0. See [LICENSE](LICENSE).
