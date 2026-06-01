# How to monitor the agent-log write path

The write path is a non-blocking daemon worker. v0.3 exposes counters and
lifecycle hooks so you can build health probes and shut down cleanly.

## Read worker stats (no DB round-trip)

```python
s = log.stats()
# {
#   "queue_depth": 0, "queue_capacity": 256, "worker_alive": True,
#   "enqueued": 1280, "written": 1278, "dropped": 0,
#   "embed_failures": 0, "write_failures": 2,
#   "last_write_ts": "2026-06-02T17:04:11.512000+00:00",
# }
```

Build a `/health` signal from it:

```python
def agent_log_health(log) -> dict:
    s = log.stats()
    fill = s["queue_depth"] / max(1, s["queue_capacity"])
    degraded = (not s["worker_alive"]) or fill >= 0.8 or s["dropped"] > 0
    return {"status": "degraded" if degraded else "ok", **s}
```

- `dropped > 0` means the queue overflowed and the **oldest** docs were
  evicted (drop-oldest, REQ-020). Sustained drops mean the worker can't keep
  up — investigate Atlas write latency or raise `queue_maxsize`.
- `write_failures` counts swallowed `PyMongoError`s; `embed_failures` counts
  embedder errors (the doc is still written, just without search fields).

## Flush and close on shutdown

The worker is a daemon thread, so a hard `kill -9` drops queued docs. For
graceful shutdown, drain first:

```python
# FastAPI lifespan / atexit
log.close(timeout=5.0)   # drain the queue, stop the worker, refuse new writes
```

`close()` is idempotent and returns `True` only if the queue fully drained in
time. Call it **before** closing the `MongoClient` — otherwise the worker's
in-flight insert races a closed client. By default `AgentLog` also registers
an `atexit` best-effort drain; pass `flush_on_exit=False` to manage it
yourself.

For a non-terminal checkpoint (e.g. before reading back what was just
written) use `flush(timeout)`, which drains without stopping the worker.
