# Indexes

The package creates two index categories. Both helpers are idempotent
and safe on every supported MongoDB deployment.

## Regular B-tree indexes

Created by `ensure_agent_log_indexes(collection, *, ttl_seconds=None)`.

| Name | Keys | Purpose |
|---|---|---|
| `agent_log_thread_step_idx` | `(thread_id, step)` | Read a thread's super-steps in order |
| `agent_log_thread_ts_idx` | `(thread_id, ts DESC)` | Recent activity in a thread |
| `agent_log_user_ts_idx` | `(user_id, ts DESC)` | Recent activity for a user |
| `agent_log_ts_ttl_idx` | `(ts)` with `expireAfterSeconds` | Auto-expire old docs (only when `ttl_seconds` supplied) |

## Atlas Search index — `agent_log_search_idx`

Created by `ensure_search_indexes(collection, *, embeddings_dim)`.

```jsonc
{
  "name": "agent_log_search_idx",
  "type": "search",
  "definition": {
    "mappings": {
      "dynamic": false,
      "fields": {
        "agent_log_text": { "type": "string" },
        "user_id":        { "type": "string" }
      }
    }
  }
}
```

The `dynamic: false` keeps the index size focused; only `agent_log_text`
and `user_id` are indexed. `user_id` is included so the per-user
pre-filter can run efficiently inside `$search`.

## Atlas Vector Search index — `agent_log_vector_idx`

```jsonc
{
  "name": "agent_log_vector_idx",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      { "type": "vector",
        "path": "agent_log_embedding",
        "numDimensions": 1024,        // matches your embedder
        "similarity": "cosine" },
      { "type": "filter",
        "path": "user_id" }
    ]
  }
}
```

Specify the embedder's output dimension at creation time:

```python
ensure_search_indexes(coll, embeddings_dim=1024)   # voyage-3
ensure_search_indexes(coll, embeddings_dim=1536)   # text-embedding-3-small
ensure_search_indexes(coll, embeddings_dim=768)    # bge-base
```

If you change embedders later, drop the vector index and recreate it
with the new dimension. There is no in-place migration; you also need
to re-embed historical docs.

## Behavior on unsupported deployments

`ensure_search_indexes` calls `collection.create_search_index(...)`
under the hood. On deployments that don't expose this method (mongomock,
older MongoDB community editions without Search enabled), it logs a
warning and returns without raising. Storage continues to work; only
the search-related code paths are unavailable.

## Reading indexes from your code

```python
for idx in coll.list_indexes():
    print(idx["name"], idx["key"])

for sidx in coll.list_search_indexes():
    print(sidx["name"], sidx.get("status"), sidx.get("queryable"))
```

## See also

- [Configuration](configuration.md) — `ttl_seconds`, `embeddings_dim`
  arguments.
- [How-to: configure TTL](../how-to/configure-ttl.md).
