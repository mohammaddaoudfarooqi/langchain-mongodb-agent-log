# Configuration

Every configuration knob is a constructor argument. The package reads
exactly one environment variable, and only inside the optional Voyage
factory.

## `AgentLog.__init__`

| Argument | Type | Default | Effect |
|---|---|---|---|
| `collection` | `pymongo.collection.Collection` | required | Where log docs are written. |
| `embeddings` | `langchain_core.embeddings.Embeddings` or `None` | `None` | When set, the worker computes `agent_log_embedding` on the final super-step of each turn. When `None`, no embedding work happens; storage still works. |
| `fs_write_tools` | `frozenset[str]` | `{"write_file", "edit_file"}` | Tool names whose calls populate `files_touched`. Set to `frozenset()` to disable file tracking. |
| `max_content_bytes` | `int` | `15 * 1024 * 1024` | Per-message content cap. Anything longer is truncated and marked. The default is just under MongoDB's 16 MiB BSON limit. |
| `max_search_text_bytes` | `int` | `8 * 1024` | Cap on the `agent_log_text` (and the embedder's input) fed into Atlas Search / Vector Search. |
| `queue_maxsize` | `int` | `256` | Worker queue capacity. When full, `record()` drops the new doc with a warning. |

## `AgentLogMiddleware.__init__`

| Argument | Type | Default | Effect |
|---|---|---|---|
| `log` | `AgentLog` | required | The engine to record into. |

## `AgentLogCallbackHandler.__init__`

| Argument | Type | Default | Effect |
|---|---|---|---|
| `log` | `AgentLog` | required | The engine to record into. |
| `user_id` | `str` or `None` | `None` | Fallback `user_id` when LangGraph doesn't elevate it from `configurable` to per-node metadata. Pass it here OR via `config["metadata"]["user_id"]` per invocation. |

## `AgentLogRetriever.__init__`

| Argument | Type | Default | Effect |
|---|---|---|---|
| `collection` | `Collection` | required | The agent-log collection. |
| `embeddings` | `Embeddings` | required | Used to embed the incoming query. |
| `search_index` | `str` | `"agent_log_search_idx"` | Atlas Search index name. |
| `vector_index` | `str` | `"agent_log_vector_idx"` | Atlas Vector Search index name. |
| `top_k` | `int` | `5` | Result count, capped at 20 internally. |

## `default_voyage(*, model, dimensions, **kwargs)`

| Argument | Type | Default | Effect |
|---|---|---|---|
| `model` | `str` | `"voyage-3"` | Voyage model name. |
| `dimensions` | `Literal[256, 512, 1024, 2048]` | `1024` | Output dimension. Must match your vector index. |
| `**kwargs` | — | — | Forwarded to `langchain_voyageai.VoyageAIEmbeddings`. |

Reads `VOYAGE_API_KEY` from the environment. Raises `RuntimeError` if
unset or if `langchain-voyageai` is not installed.

## Logging

The package uses a single logger named `langchain_mongodb_agent_log`.
All warning lines (queue full, PyMongoError, embedder failure, search
DDL skipped, retriever failure) flow through it. Configure in your
application:

```python
import logging
logging.getLogger("langchain_mongodb_agent_log").setLevel(logging.WARNING)
```

## Environment variables

| Variable | Read by | Required for |
|---|---|---|
| `VOYAGE_API_KEY` | `default_voyage()` only | Using the Voyage factory |

That is the entire list. Nothing else in the package reads from
`os.environ` — all other configuration is constructor-injected.
