# How to configure TTL retention

Goal: auto-expire old log documents using a MongoDB TTL index instead
of running a cron job.

## Add a TTL index at provisioning time

```python
from langchain_mongodb_agent_log import ensure_agent_log_indexes

ensure_agent_log_indexes(
    db["agent_log"],
    ttl_seconds=30 * 24 * 60 * 60,  # 30 days
)
```

The MongoDB background reaper will remove documents whose `ts` is older
than `ttl_seconds` seconds. The reaper runs every ~60 seconds — don't
expect millisecond precision.

## Different retention per environment

```python
ttl = {"prod": 90 * 86400, "staging": 7 * 86400, "dev": 86400}.get(env)
ensure_agent_log_indexes(db["agent_log"], ttl_seconds=ttl)
```

## Changing the retention period

If a TTL index already exists with a different `expireAfterSeconds`,
re-running `ensure_agent_log_indexes` does **not** modify it (re-running
is a no-op). To change it, drop the index and re-create it:

```python
db["agent_log"].drop_index("agent_log_ts_ttl_idx")
ensure_agent_log_indexes(db["agent_log"], ttl_seconds=new_ttl)
```

## Disabling TTL

Pass `ttl_seconds=None` (the default). The TTL index is never created.

## Caveats

- TTL applies to **the entire collection**, not per user or per thread.
- If you need per-thread retention, query and delete from your
  application or run a scheduled MongoDB Atlas Trigger.
- The Atlas Search and Vector Search indexes do not auto-shrink when
  documents are TTL-deleted; the next refresh window picks them up.

## Change the TTL without dropping the index

`ensure_agent_log_indexes(ttl_seconds=...)` only sets the TTL at creation
time — changing it used to require dropping and recreating the index. Use
`set_ttl` to mutate `expireAfterSeconds` in place via `collMod`:

```python
from langchain_mongodb_agent_log import set_ttl

set_ttl(db["agent_log"], 7 * 24 * 3600)  # 30 days -> 7 days, no drop
set_ttl(db["agent_log"], None)           # remove the TTL index entirely
```

On deployments without `collMod` (mongomock, older community server) it warns
and falls back to creating the index, never raising.
