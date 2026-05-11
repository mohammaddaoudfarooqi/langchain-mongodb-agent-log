# Architecture

This page explains the design rather than telling you how to use it. If
you're trying to get something working, the [tutorial](../tutorial/first-log.md)
or a [how-to](../how-to/) is the right starting point.

## The boundary that matters

There are exactly three layers in this package:

1. **Adapters** — middleware, callback, graph node. Their job is to
   turn a hook firing into a single `engine.record(...)` call. They
   know LangChain shapes; they know nothing about MongoDB.
2. **Engine (`AgentLog`)** — projects state into a JSON document. Knows
   nothing about LangChain hooks. Everything is plain kwargs.
3. **Worker** — drains a bounded queue on a daemon thread, embeds when
   appropriate, inserts into MongoDB. Knows nothing about agents.

The cardinal rule: **adapters do not write to MongoDB**, and the engine
does not call `langchain.agents.middleware.AgentMiddleware`. Each layer
has one job. The boundary is what makes a single engine usable from
three completely different hook surfaces.

## Why a daemon worker

A LangGraph super-step is a synchronous boundary in the agent loop. If
the agent logging code blocked on the MongoDB write — let alone an
embedding round-trip to Voyage — every step of every turn would pay
that cost on the hot path. With a long conversation that's tens to
hundreds of extra seconds.

So the engine never blocks. `record()` projects the state, builds the
JSON document, and calls `Queue.put_nowait`. The worker thread drains
the queue at its own pace. Total cost on the hot path: a few hundred
microseconds, no I/O.

There's exactly one worker thread per process. FIFO order per
`thread_id` is preserved trivially. Multiple workers would require
per-`thread_id` partitioning and offer no observable throughput win at
our default queue depths.

## Why embedding only on the final super-step

A typical agent turn looks like:

```
super-step 1: planner emits tool_call
super-step 2: tool runs
super-step 3: planner consumes tool result, emits another tool_call
super-step 4: tool runs
super-step 5: planner emits user-visible reply
```

Embedding every super-step would trigger five Voyage calls per turn.
Most of them embed text that nobody will ever search — a tool
invocation, an intermediate planner step. The engine instead detects
the "final super-step" — the one whose last AI message has no pending
`tool_calls` — and embeds only there. One embedding per
user-visible turn.

Code: `core/projection.py:is_final_step`. The detector is intentionally
simple. If your graph has unusual shapes (e.g. a tool that always
fires after the user-visible reply), override the heuristic by
disabling embeddings on `AgentLog` and embedding manually with a
custom node.

## Why `files_touched` comes from tool calls

Under spec-503's `CompositeBackend` (S3 VFS + StoreBackend), the
deepagents `state["files"]` is empty by design — files live outside
graph state to keep the checkpointer small. Reading state to derive
`files_touched` would always return `[]`.

Instead, the projection inspects AI-message `tool_calls` for known
filesystem-mutating tool names (`write_file`, `edit_file`, customizable
via `fs_write_tools`). The intent of the call is what gets logged: the
path, the new size if knowable, and the operation kind — not the blob
itself. The mirror remains audit-only and never holds file content.

## Why the callback adapter pairs start + end

LangGraph stamps per-node metadata (`langgraph_node`, `langgraph_step`,
`thread_id`) on `on_chain_start` callbacks. On `on_chain_end`, the
metadata field is `None`. Without state across the two events, the
handler can't attribute the document to the correct node.

So the handler keeps a small `dict[run_id -> attribution_data]`. On
start, capture the metadata if `langgraph_node` is present. On end,
look up by `run_id`, write the document, and free the entry. Inner
Runnables (per-LLM-call, per-tool-call events) don't carry
`langgraph_node` and are silently ignored — they would otherwise
flood the log.

`user_id` is the awkward one: LangGraph elevates `thread_id` to per-node
metadata but not `user_id`. We accept `user_id=` on the callback's
constructor as a fallback, with the alternative being to put it in
`config["metadata"]["user_id"]` at invocation. Spelunking into context
vars from inside a callback was tried and doesn't reliably work.

## Why no `Settings` object

The package is constructor-injected end-to-end. `AgentLog(...)` accepts
everything you'd otherwise put in env vars. The reason is pragmatic:
the alternative is two competing config systems (yours + ours), and at
v0.1 we'd rather you bring your own.

The single exception is `default_voyage()`, which reads
`VOYAGE_API_KEY`. That's purely a convenience for the tutorial path; if
you don't use the factory, the package never touches `os.environ`.

## What this is not

- **Not a LangGraph checkpointer.** It cannot resume execution. Use
  `MongoDBSaver` (or the SaaS Postgres saver) for resume / replay /
  time-travel.
- **Not a chat-history store.** `MongoDBChatMessageHistory` exists for
  that; the agent log's `messages[]` array is a superset of what
  chat-history stores, so for new code you can rely on the agent log
  for both purposes, but the migration is the user's call.
- **Not LangSmith.** LangSmith owns trace observability with a UI, run
  comparison, eval datasets. The agent log owns *agent-callable
  retrieval* over your own DB. Most teams want both.

## See also

- [Why not a checkpointer?](why-not-checkpointer.md)
- [LangSmith comparison](langsmith-comparison.md)
