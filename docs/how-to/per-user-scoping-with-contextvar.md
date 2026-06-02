# How to scope `user_id` per request in a multi-user server

Goal: a single `AgentLogCallbackHandler` instance, shared across many
concurrent requests, attributing each agent-log document to the correct
user — without leaking attribution between users.

Without it, you'd either pass `user_id` in `metadata` on every call, or
instantiate one handler per user. A `ContextVar`-based scope lets a
single handler work correctly under concurrency.

## When you need this

- You build agents on bare `StateGraph` (the callback adapter applies).
- You serve multiple users from a single process — typically a FastAPI /
  ASGI / WSGI server.
- You want one shared handler instance for efficiency / simplicity.

If you're on `create_agent` / deepagents, you don't need this — the
middleware adapter reads `user_id` directly from
`langgraph.config.get_config()`, which is per-task by construction.

## The pattern

```python
from langchain_mongodb_agent_log import (
    AgentLog,
    AgentLogCallbackHandler,
    scoped_user,
)
from fastapi import FastAPI, Request
from pymongo import MongoClient

app = FastAPI()
db = MongoClient(MONGO_URI).my_app

# Construct the engine + handler ONCE at process start.
log = AgentLog(collection=db["agent_log"], embeddings=embedder)
handler = AgentLogCallbackHandler(log)   # no user_id= default — we'll scope per-request

@app.post("/chat")
async def chat(request: Request, payload: ChatRequest):
    # Set the per-request scope, then invoke the graph. ContextVar is
    # async-aware: this scope is visible only inside this coroutine,
    # not in any other concurrently-running request.
    with scoped_user(payload.user_id):
        result = await graph.ainvoke(
            {"messages": payload.messages},
            config={
                "configurable": {
                    "thread_id": payload.thread_id,
                    # Note: still pass user_id in configurable too, so
                    # the retriever's pre_filter and any code reading
                    # configurable directly stays correct.
                    "user_id": payload.user_id,
                },
                "callbacks": [handler],
            },
        )
    return result
```

That's the whole pattern. Two requests for `alice` and `bob` running
in parallel each have their own scope. Alice's callbacks fire with
`current_user_id() == "alice"`; Bob's with `"bob"`. No leakage.

## How resolution actually works

When a callback fires, the handler picks the first non-empty value:

1. `metadata["user_id"]` — explicit per-call override. Useful for
   tests; rare in production.
2. `current_user_id()` — the value set by the active
   `with scoped_user(...)` block. **This is the production path.**
3. `self._default_user_id` — the constructor argument. The fallback
   for "single-user deployment, never wrapped a `scoped_user`."
4. Empty string — the handler skips the write entirely.

Configure each user-attribution path the way that fits your
deployment shape.

## Sync code works too

`ContextVar` works the same way in synchronous code. Each
`threading.Thread` sees its own value:

```python
from concurrent.futures import ThreadPoolExecutor

def run_one(payload):
    with scoped_user(payload["user_id"]):
        return graph.invoke(payload, config={"callbacks": [handler]})

with ThreadPoolExecutor(max_workers=10) as ex:
    results = list(ex.map(run_one, batch_of_payloads))
```

Each thread enters its own `scoped_user(...)` block and exits cleanly.

## Caveat: `threading.Thread(target=...)` does NOT inherit context

If you spawn a thread directly via `threading.Thread`, the new thread
starts with the ContextVar at its default (`None`). This is stdlib
behavior, not a quirk of this package. If you need the parent's scope
visible in the child, set it explicitly inside the child function.

`asyncio.Task` does the right thing automatically — child tasks
inherit a copy of the parent's context. So `await asyncio.gather(...)`
just works.

## Nested scopes are LIFO

```python
with scoped_user("alice"):           # alice
    with scoped_user("bob"):         # bob
        process_handoff()
    # bob is popped here; alice is restored
    process_more_alice_work()
# alice is popped here; previous (often None) is restored
```

Useful when one user delegates to another in the same task — e.g.
admin-impersonation flows. Each scope nests; each exit pops the
latest.

## Pitfall: don't reach into the ContextVar directly

The package exports `scoped_user` and `current_user_id`. The
underlying `_user_id_var` is intentionally private. Bypassing the
context manager (e.g. calling
`_user_id_var.set("alice")` without a matching `reset(token)`)
permanently bleeds state across requests in the same task. Always
use the context manager.

## Tests for your code

If your tests construct a handler and call its hooks directly, you can
either supply `metadata["user_id"]` per test (cleanest) or wrap the
test body in `scoped_user(...)`:

```python
def test_my_handler():
    with scoped_user("test-user"):
        h.on_chain_start(...)
        h.on_chain_end(...)
    assert coll.find_one({})["user_id"] == "test-user"
```

## See also

- [Architecture](../explanation/architecture.md) — why callbacks
  can't read `RunnableConfig` directly via `langgraph.config.get_config()`.
- [Bare `StateGraph`](bare-stategraph.md) — full walkthrough of the
  callback adapter.
- [API reference: `scoped_user` / `current_user_id`](../reference/api.md)
