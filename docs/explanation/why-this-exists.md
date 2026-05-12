# Why this package exists

Read this first if you're evaluating whether you need it. The other
explanation pages cover specific comparisons; this one covers the
problem and the decision.

## The problem in one sentence

Your agent has been talking to N users for M weeks, and now you need to
**query that conversation data** — for audit, for the agent's own
recall, for evals, or for compliance — and the four obvious tools each
fall short in a different way.

## The pain, concretely

A real moment from a production deployment. The team had:

- An agent on `create_agent` (or deepagents) running in production for
  weeks.
- A `MongoDBSaver` for checkpointing.
- LangSmith for trace observability.
- A user on Slack asking: *"can you tell me what I asked your bot last
  week?"*

The team's options:

1. **Open MongoDB Compass and grep `checkpoints`.** Doesn't work — the
   data is `msgpack`-encoded BSON binary. You can't read it without
   deserializing through the LangGraph runtime.
2. **Open LangSmith and search.** Works, but only on metadata + a
   250-character truncated full-text index, no semantic similarity, and
   the data lives in LangChain Inc.'s SaaS — meaning you can't let the
   *agent itself* query it cheaply at runtime, and compliance teams
   may object.
3. **Write a custom callback that mirrors messages somewhere
   queryable.** Doable; takes ~700 LOC if you want fire-and-forget
   persistence, hybrid search, per-user filtering, and proper async
   isolation. Most teams ship a buggy first version.
4. **Re-use `MongoDBChatMessageHistory`.** Closer fit, but it has no
   per-user `pre_filter` enforcement, no hybrid search, no agent
   metadata (todos, tool calls, file writes), and no audit trail
   shape. You'd have to layer it.

The fix that's actually needed is one library that does (3) properly,
ships with (1)'s simplicity, gives the agent (2)'s in-loop search
capability, and has (4)'s ergonomics for the rest of the team.

## What this package owns

A **queryable, hybrid-searchable, per-user-scoped agent activity log**,
backed by your existing MongoDB Atlas cluster, drop-in via a
middleware or callback adapter.

Three claims, each load-bearing:

1. **Decoded JSON in your DB.** Open Compass, run an aggregation, build
   a dashboard. The data is plain JSON: messages, tool_calls, todos,
   files_touched, agent_name, correlation_id.
2. **Hybrid retrieval the agent itself can call.** RRF fusion of
   `$search` + `$vectorSearch`, scoped per `user_id` via mandatory
   pre-filter. The agent can recall its own past conversations
   in-loop with one tool call.
3. **One-line install** alongside the rest of `langchain-mongodb`.
   `AgentLogMiddleware` plugs into `create_agent` /
   deepagents; `AgentLogCallbackHandler` plugs into bare
   `StateGraph` and multi-agent supervisors.

## What this package explicitly does NOT do

- **Doesn't replace `MongoDBSaver`.** That's the LangGraph runtime's
  resume log. Cannot resume from an agent log doc; pending writes,
  channel versions, and the LangGraph step counter are intentionally
  not stored. Run them together.
- **Doesn't compete with LangSmith for trace observability.**
  LangSmith owns the engineering UI, run diff/replay, eval datasets.
  The agent log owns *agent-callable retrieval over your own DB*.
  Most teams want both.
- **Doesn't replace your knowledge base.** This stores the
  *conversation*, not curated content. Your KB and the agent log are
  different collections with different jobs.
- **Doesn't ship a UI.** It's a library. Bring your own admin
  dashboard or use Atlas Charts.

## How it compares to the alternatives

### vs. `MongoDBSaver` (LangGraph checkpointer for MongoDB)

|  | `MongoDBSaver` | This package |
|---|---|---|
| Purpose | Resume the LangGraph runtime mid-turn | Audit + retrieve the conversation |
| Storage shape | Opaque msgpack BSON binary | Decoded JSON, queryable in Compass |
| Per-user scoping | None at the storage layer | Mandatory `pre_filter` on retrieval |
| Hybrid search | Not supported | RRF over `$search` + `$vectorSearch` |
| Hot-path cost | Synchronous (blocks the agent step) | Fire-and-forget on a daemon thread |
| Replaces by | Cannot — this package complements it | — |

If your problem is "the agent crashed mid-turn and I need it to pick
up where it left off," you need the saver. This package can't do that.

If your problem is "I want to query what the agent did, on demand,
without deserializing checkpoint blobs," you need this package. The
saver can't do that.

You usually run both. They're orthogonal.

### vs. LangSmith

|  | LangSmith | This package |
|---|---|---|
| Trace UI for engineers | Yes (excellent) | No |
| Eval dataset extraction | Yes | No |
| Cost / latency / token rollups | Yes | No |
| Programmatic access for agents | Limited (MCP server, paginated, 250-char truncated text search) | First-class — RRF in one round-trip |
| Hybrid (vector + lexical) search | Not in public API | Yes (RRF) |
| Self-hosted in your DB | LangSmith Self-Hosted (separate SKU) | Default (your existing Atlas) |
| Cost model | Per-trace pricing | Storage cost on your existing cluster |

LangSmith is the right primary tool for engineering observability
(debugging in a UI, run comparison, evals). It is not built around the
"agent calls a recall tool in-loop" use case, and its public
retrieval primitives reflect that.

This package is built for the in-loop-recall use case specifically.
Most teams ship LangSmith for the dev/debug loop and this package for
production agent-callable recall.

### vs. `MongoDBChatMessageHistory`

|  | `MongoDBChatMessageHistory` | This package |
|---|---|---|
| Stores messages | Yes | Yes (verbatim, plus structured metadata) |
| Per-user filter | Encoded in `session_id` (no enforcement) | Mandatory `pre_filter` at retriever |
| `tool_calls`, todos, files_touched | No | Yes |
| `agent_name` attribution | No | Yes (multi-agent ready) |
| Hybrid retrieval class | No | Yes — `AgentLogRetriever` |
| Hot-path semantics | Synchronous append per message | Async daemon worker, embed-on-final-step |

The chat-history class is the closest existing primitive in the
ecosystem. For new code, the agent log is a strict superset — it stores
everything chat history does, plus the agent metadata you'd otherwise
have to bolt on. Existing code that uses chat-history can keep doing so.

### vs. "I'll just write it myself"

A handwritten version that matches what this ships needs:

- A `BaseCallbackHandler` or `AgentMiddleware` adapter (200 LOC).
- A daemon-thread + bounded-queue worker so persistence doesn't block
  the agent step (50 LOC + ordering tests).
- A "final super-step" detector so embedding doesn't fire on every
  intermediate planner step (30 LOC + edge cases).
- Atlas Search + Vector Search index DDL with idempotent re-run and
  drift detection (100 LOC + Atlas-CLI quirks).
- A retriever wrapping `MongoDBAtlasHybridSearchRetriever` with a
  mandatory per-user pre-filter (50 LOC + INV-004 tests).
- A `@tool` factory binding the retriever for in-loop agent use (50
  LOC + LangChain `@tool` injection quirks).
- `ContextVar`-based per-async-task `user_id` scoping for multi-tenant
  servers (30 LOC + isolation tests).
- A test suite that catches all of the above (~600 LOC).

Total: ~1100 LOC + the dozen "I didn't think of that" issues that
surface in production multi-tenant code. The package compresses this
into one `pip install` plus three lines of wiring.

DIY is the right answer if your needs diverge from this shape — e.g.,
you want to write to S3 instead of MongoDB, or you want a different
retrieval strategy. For the standard case, the engineering math
favors the library.

## Decision rubric

| If you need... | Reach for... |
|---|---|
| Resume after crash, time travel, branch | `MongoDBSaver` |
| Engineering trace UI, run diff, eval datasets | LangSmith |
| Curated knowledge corpus retrieval | `MongoDBAtlasVectorSearch` over your own KB collection |
| Conversation memory the agent itself queries in-loop | **This package** (`search_past_conversations`) |
| Audit log of what the agent said and did, queryable in MQL | **This package** (the `agent_log` collection) |
| Per-user conversation history with hybrid search | **This package** |
| Multi-tenant async server with one shared handler | **This package** (`scoped_user(...)` ContextVar, v0.2+) |
| Custom storage backend (S3, Postgres, etc.) | DIY — none of the above fit |

## Where it fits in your stack

```
┌─────────────────────────────────────────────────────────────┐
│                   Your agent (create_agent /                │
│                    deepagents / StateGraph)                 │
└────┬─────────────┬─────────────┬─────────────┬──────────────┘
     │             │             │             │
     ▼             ▼             ▼             ▼
 MongoDBSaver  LangSmith    MongoDBAtlas   AgentLog
 (resume)     (eng UI)      VectorSearch   (this pkg)
                            (KB)
     │             │             │             │
     ▼             ▼             ▼             ▼
  Postgres     LangChain      MongoDB        MongoDB
  or Mongo     Inc. SaaS      Atlas          Atlas
                              (KB coll)      (agent_log
                                              coll)
```

Five stores, four jobs, one runtime. None of them is a substitute for
another; each is the right tool for its specific access pattern.

## See also

- [Why not a checkpointer?](why-not-checkpointer.md) — deeper dive on
  the `MongoDBSaver` boundary, with the side-by-side data model and
  field comparison.
- [LangSmith comparison](langsmith-comparison.md) — corrected framing
  on what LangSmith does and doesn't expose to agents.
- [Architecture](architecture.md) — how the engine, adapters, and
  worker fit together.
- [Tutorial: first log](../tutorial/first-log.md) — go from zero to a
  persisted agent turn in 10 minutes.
