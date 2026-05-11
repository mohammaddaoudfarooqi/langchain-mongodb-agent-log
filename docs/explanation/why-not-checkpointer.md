# Why this isn't a checkpointer

If you've used `langgraph.checkpoint.mongodb.MongoDBSaver`, you might
look at this package and wonder: isn't this just another checkpointer?

It isn't. They solve different problems and only share the
"MongoDB" word in the name. This page lays out where the boundary is.

## What `MongoDBSaver` does

`MongoDBSaver` implements `BaseCheckpointSaver`. Its job is to make
LangGraph's runtime resumable.

- Stores serialized channel state. The `messages` channel, the
  `todos` channel, the `files` channel, the LangGraph internals —
  all serialized via `JsonPlusSerializer` and stored as opaque
  msgpack-encoded BSON binary.
- Stores `pending_writes` — intermediate writes within a super-step
  that LangGraph needs to replay if execution is interrupted.
- Tracks channel versions so the runtime can detect what's new.
- Keyed by `(thread_id, checkpoint_ns, checkpoint_id)`.

When you call `graph.invoke(...)` after a crash, LangGraph calls
`MongoDBSaver.get_tuple(...)` to retrieve the last checkpoint and
resumes from there.

## What this package does

`AgentLog` writes one decoded JSON document per super-step boundary.

- Stores **decoded** message content — readable in MongoDB Compass,
  queryable in MQL, indexable with Atlas Search.
- Stores **derived** fields (`agent_name`, `files_touched`,
  `agent_log_text` + `agent_log_embedding`) that don't exist in the
  checkpointer's storage at all.
- Drops what's irrelevant for the audit / search use case
  (`pending_writes`, channel versions, opaque channel state).
- Keyed by `(thread_id, step)` with a per-process monotonic counter.

You can't resume a graph from an agent log document. You can read it,
search it, hand it to a dashboard, feed it back to an agent via
`search_past_conversations`. The two purposes are orthogonal.

## Side-by-side data model

| Field | `checkpoints` (saver) | `agent_log` (this package) |
|---|---|---|
| `thread_id` | yes | yes |
| `checkpoint_id` (UUID) | yes | no — uses `step` integer |
| Messages | yes (msgpack-encoded) | yes (decoded JSON) |
| `tool_calls` on AI messages | yes (inside the channel blob) | yes (verbatim, queryable) |
| `pending_writes` | yes | no — intentionally lossy |
| Channel versions | yes | no |
| `metadata.source` (input/loop/fork) | yes | no |
| `agent_name` (per-agent attribution) | no | yes |
| `correlation_id` at top level | no (only in metadata) | yes |
| `files_touched` derived from tool_calls | no | yes |
| `mirror_text` denormalized | no | yes (`agent_log_text`) |
| Embedding for hybrid search | no | yes (`agent_log_embedding`) |

## Why both

In practice you run them together. The checkpointer for resume; the
agent log for audit, search, and agent recall. Different consumers,
different read patterns, different write semantics.

```python
from langgraph.checkpoint.mongodb import MongoDBSaver
from langchain_mongodb_agent_log import AgentLog, AgentLogMiddleware

saver = MongoDBSaver(client, db_name="my_app", checkpoint_collection_name="checkpoints")
log = AgentLog(collection=client["my_app"]["agent_log"], embeddings=embedder)

agent = create_agent(
    model=...,
    tools=[...],
    middleware=[AgentLogMiddleware(log)],
    checkpointer=saver,
)
```

One agent. Two persistence surfaces. Both serve different purposes.

## A note on LangGraph Platform SaaS

The Platform overrides your `checkpointer=` and stores state in its own
managed Postgres. It does **not** override `middleware=` or
`callbacks=`. So this package keeps working on Platform SaaS — your
agent log writes to Atlas while the platform writes its checkpoints to
Postgres. That's how you get queryable conversation data in your own
database without abandoning Platform.

## See also

- [Architecture](architecture.md)
- [LangSmith comparison](langsmith-comparison.md)
