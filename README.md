# langchain-mongodb-agent-log

A queryable, hybrid-searchable activity log for LangChain agents, backed by
MongoDB Atlas. Drop-in for `create_agent`, deepagents, multi-agent
supervisors, and bare `StateGraph` graphs. Sits **alongside** LangGraph's
checkpointer — not a replacement. The checkpointer holds opaque resume
state; this package holds the decoded conversation in your own database
where you can query it, search it, and let agents recall it per user.

> v0.1 — alpha. API is stable but not frozen. Apache-2.0.

---

## Why

LangGraph's `MongoDBSaver` (or the SaaS Postgres saver) stores serialized
channel state. You can't query it, you can't full-text search it, your
agent can't recall it at runtime. LangSmith gives you observability in a
dashboard, but its public API is metadata-filter + 250-char-truncated
substring search — not a per-user semantic memory store.

`langchain-mongodb-agent-log` solves the third surface:

- **Decoded conversation log** — one document per agent super-step, with
  messages, tool calls, todos, files touched, and per-agent attribution.
- **Atlas hybrid search** — RRF fusion of `$search` + `$vectorSearch`,
  scoped per-user via `pre_filter`.
- **Drop-in adapters** — `AgentLogMiddleware` for `create_agent` /
  deepagents, `AgentLogCallbackHandler` for bare `StateGraph` /
  multi-agent / mixed graphs, `agent_log_node` for explicit-node use.
- **Fire-and-forget** — the agent super-step never blocks on the write
  or the embedding round-trip.
- **Self-hosted** — your data, your cluster. No third party in the data
  path.

## 60-second quickstart

```bash
pip install langchain-mongodb-agent-log[voyage]
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

## Where to go next

| If you want to... | Read |
|---|---|
| Walk from zero to a working agent log | [`docs/tutorial/first-log.md`](docs/tutorial/first-log.md) |
| Add agent self-recall via hybrid search | [`docs/tutorial/hybrid-search.md`](docs/tutorial/hybrid-search.md) |
| Wire it into a `create_agent` agent | [`docs/how-to/create-agent.md`](docs/how-to/create-agent.md) |
| Wire it into deepagents | [`docs/how-to/deepagents.md`](docs/how-to/deepagents.md) |
| Multi-agent supervisor + workers | [`docs/how-to/multi-agent-supervisor.md`](docs/how-to/multi-agent-supervisor.md) |
| Bare `StateGraph` (the agentic-ai shape) | [`docs/how-to/bare-stategraph.md`](docs/how-to/bare-stategraph.md) |
| Migrate from `create_react_agent` | [`docs/how-to/migrate-from-create-react-agent.md`](docs/how-to/migrate-from-create-react-agent.md) |
| TTL-based retention | [`docs/how-to/configure-ttl.md`](docs/how-to/configure-ttl.md) |
| Plug in OpenAI / Bedrock / your own embedder | [`docs/how-to/provide-custom-embeddings.md`](docs/how-to/provide-custom-embeddings.md) |
| API surface, every public name | [`docs/reference/api.md`](docs/reference/api.md) |
| Persisted document schema | [`docs/reference/document-shape.md`](docs/reference/document-shape.md) |
| Atlas index DDL | [`docs/reference/indexes.md`](docs/reference/indexes.md) |
| Constructor knobs and defaults | [`docs/reference/configuration.md`](docs/reference/configuration.md) |
| How the engine + adapters fit together | [`docs/explanation/architecture.md`](docs/explanation/architecture.md) |
| Why this isn't a checkpointer | [`docs/explanation/why-not-checkpointer.md`](docs/explanation/why-not-checkpointer.md) |
| How it fits next to LangSmith | [`docs/explanation/langsmith-comparison.md`](docs/explanation/langsmith-comparison.md) |

The full doc index: [`docs/README.md`](docs/README.md).

## Compatibility

- Python 3.10+
- `langchain >= 0.3.27`, `langchain-core >= 0.3`, `langgraph >= 0.3`,
  `langchain-mongodb >= 0.11`, `pymongo >= 4.6`.
- MongoDB Atlas with Search + Vector Search indexes (the search
  features are now generally available on community editions where
  Search is enabled; storage works on any MongoDB).
- Voyage extra (`[voyage]`) optional.

## License

Apache-2.0. See [LICENSE](LICENSE).
