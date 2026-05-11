# Tutorial: your first agent log

You'll go from an empty repo to a persisted, queryable agent turn in
about 10 minutes. By the end you'll be able to query your agent's first
conversation in MongoDB Compass.

This is a tutorial — its job is to teach you how the moving parts fit
together by doing. The exact code we run isn't production-ready; it's a
learning scaffold.

## What you'll learn

- How to install the package and connect it to MongoDB Atlas.
- How a single `AgentLogMiddleware` instance feeds every super-step into
  one collection.
- What a log document looks like.

## Prerequisites

- Python 3.10+ and a MongoDB Atlas cluster (a free M0 is fine).
- An Anthropic, OpenAI, or Bedrock account — anything `create_agent`
  accepts.
- A Voyage API key (sign up at https://www.voyageai.com if you don't
  have one). Voyage isn't required by the package but we'll use it to
  keep this tutorial short.

## 1. Install

```bash
pip install langchain-mongodb-agent-log[voyage]
pip install langchain-anthropic   # or your model provider's package
```

## 2. Set environment

```bash
export MONGODB_URI="mongodb+srv://USER:PASSWORD@cluster.mongodb.net"
export VOYAGE_API_KEY="..."
export ANTHROPIC_API_KEY="..."
```

## 3. Provision indexes (one-time)

```python
from pymongo import MongoClient
from langchain_mongodb_agent_log import (
    ensure_agent_log_indexes,
    ensure_search_indexes,
)

import os
db = MongoClient(os.environ["MONGODB_URI"]).my_app
coll = db["agent_log"]

ensure_agent_log_indexes(coll)
ensure_search_indexes(coll, embeddings_dim=1024)
```

The first call creates regular B-tree indexes for `(thread_id, step)`,
`(thread_id, ts)`, and `(user_id, ts)`. The second creates the Atlas
Search and Vector Search indexes the retriever uses later. Both are
idempotent — re-running them is a no-op.

> **Note.** The Atlas Search indexes take ~30 seconds to become
> queryable after creation. The log writes don't depend on them, so you
> can keep going.

## 4. Build the agent

Create `quickstart.py`:

```python
import os
from langchain.agents import create_agent
from langchain_mongodb_agent_log import (
    AgentLog,
    AgentLogMiddleware,
    default_voyage,
)
from pymongo import MongoClient

db = MongoClient(os.environ["MONGODB_URI"]).my_app

log = AgentLog(
    collection=db["agent_log"],
    embeddings=default_voyage(),
)

agent = create_agent(
    model="anthropic:claude-haiku-4-5",
    tools=[],
    middleware=[AgentLogMiddleware(log)],
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "What is 2 + 2?"}]},
    config={"configurable": {"thread_id": "demo", "user_id": "alice"}},
)
print(result["messages"][-1].content)

# Block briefly so the background worker drains before the script exits.
log.flush_for_tests()
```

Run it:

```bash
python quickstart.py
```

Expected output: an answer that says "4" (or thereabouts).

## 5. Inspect the log

```python
for doc in db["agent_log"].find({}):
    print(doc["step"], doc["agent_name"], doc["messages"][-1]["content"][:80])
```

You should see at least one document. The final super-step has
`agent_log_text` and `agent_log_embedding` fields populated — that's
what the hybrid retriever uses.

## What just happened

1. The middleware fired once per `after_model` boundary.
2. The engine projected the LangChain messages into plain JSON.
3. The background worker embedded the final-step text and inserted the
   document.
4. None of that work blocked your `agent.invoke(...)` call.

## Where to go next

- [Tutorial: hybrid search](hybrid-search.md) — let the agent recall
  its own past conversations.
- [Reference: document shape](../reference/document-shape.md) — the
  exact field-by-field schema.
- [How-to: configure TTL](../how-to/configure-ttl.md) — auto-expire old
  threads.
