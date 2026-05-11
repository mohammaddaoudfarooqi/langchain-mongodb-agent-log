# How to wire `langchain-mongodb-agent-log` into a `create_agent` agent

Goal: persist every super-step of a single `create_agent` instance.

## Steps

```python
from langchain.agents import create_agent
from langchain_mongodb_agent_log import (
    AgentLog,
    AgentLogMiddleware,
)
from pymongo import MongoClient

db = MongoClient(os.environ["MONGODB_URI"]).my_app

log = AgentLog(collection=db["agent_log"])

agent = create_agent(
    model="anthropic:claude-haiku-4-5",
    tools=[...],
    middleware=[AgentLogMiddleware(log)],
)
```

Invoke as usual. `RunnableConfig.configurable.thread_id` and
`user_id` are required:

```python
agent.invoke(
    {"messages": [{"role": "user", "content": "Hi"}]},
    config={"configurable": {"thread_id": "t1", "user_id": "alice"}},
)
```

## Optional: enable hybrid-search enrichment

```python
from langchain_mongodb_agent_log import default_voyage

log = AgentLog(collection=db["agent_log"], embeddings=default_voyage())
```

When configured, the engine writes `agent_log_text` and
`agent_log_embedding` on the **final super-step of each turn** (not
every super-step), so you pay one Voyage round-trip per user-visible
reply.

## Tips

- The middleware is async-safe. `agent.ainvoke(...)` works without
  changes; `aafter_model` mirrors `after_model`.
- `agent_name` defaults to `"main"`. To set a different name (e.g.
  in a multi-agent setup), pass it via configurable:
  `config={"configurable": {..., "agent_name": "researcher"}}`.

## See also

- [Multi-agent supervisor](multi-agent-supervisor.md)
- [Reference: configuration](../reference/configuration.md)
