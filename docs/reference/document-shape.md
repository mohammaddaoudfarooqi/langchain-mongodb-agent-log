# Document shape

The schema of a single agent-log document, as written to the
collection.

```jsonc
{
  "_id": ObjectId,
  "thread_id": "string",
  "user_id": "string",
  "agent_name": "string",          // default "main"
  "step": 0,                        // monotonic per thread_id, in-process
  "parent_step": null,              // step - 1, or null when step == 0
  "ts": ISODate,                    // UTC datetime, set at record() time
  "correlation_id": "string",       // empty string when caller doesn't supply

  "messages": [
    {
      "type": "human" | "ai" | "tool" | "system",
      "content": "string",          // Bedrock content lists coerced
      "tool_calls": [ ... ],        // verbatim from message.tool_calls
      "tool_call_id": "string|null",
      "usage": { ... } | null,      // message.usage_metadata
      "model_id": "string|null",    // additional_kwargs.model_id
      "finish_reason": "string|null"// additional_kwargs.stop_reason
    },
    ...
  ],

  "todos": [
    { "id": "string", "content": "string",
      "status": "pending" | "in_progress" | "completed" }
  ],

  "files_touched": [
    { "path": "string", "size": 0,
      "content_hash": null,         // reserved; null in v0.1
      "op": "write" | "edit" }
  ],

  // Present only on the FINAL super-step of a turn AND when an embedder
  // was passed to AgentLog. Omitted entirely otherwise.
  "agent_log_text": "string",      // joint human + final-AI; capped
  "agent_log_embedding": [float]    // vector dimension matches embedder
}
```

## Field-by-field

### `thread_id`, `user_id`
Required identifiers. Missing either skips the write entirely.

### `agent_name`
Defaults to `"main"`. Set per super-step via:

- `RunnableConfig.configurable["agent_name"]` (middleware adapter), or
- `metadata["langgraph_node"]` (callback adapter, automatic).

### `step`
A monotonically-increasing integer per `thread_id`, maintained
**in-process** by the engine. Across process restarts, the counter
resets — `step` is not globally monotonic. If you need a globally
ordered identifier, use `ts` for ordering and `correlation_id` for
cross-system reconciliation.

### `parent_step`
`step - 1` for `step > 0`, otherwise `null`. Cheap pointer for
queries like "find the prior super-step in this thread".

### `ts`
UTC datetime computed at `record()` time, before enqueue. Reflects
when the agent's hook fired, not when the document was actually
inserted (which can be milliseconds later when the worker drains).

### `correlation_id`
Empty string when not supplied. Use this to correlate agent-log
documents with traces in LangSmith, OpenTelemetry, or your own
request-ID header.

### `messages`
Verbatim projection of the super-step's `state["messages"]`. Bedrock
content lists are coerced to strings; oversized content (above
`max_content_bytes`, default 15 MiB) is truncated with a
`[truncated, original_size=N bytes]` marker.

### `todos`
Projected from `state["todos"]` (deepagents-shaped). Statuses outside
`{pending, in_progress, completed}` normalize to `pending`. Both
`content` and the legacy `text` key are accepted; output uses
`content`.

### `files_touched`
Derived from AI-message `tool_calls`. Default tool names that count
as filesystem writes: `write_file`, `edit_file`. Configurable via
`AgentLog(fs_write_tools=...)`. Latest call per path wins (a write
followed by an edit reports a single entry with `op="edit"`).
Read-only tools (`read_file`, `ls`, `glob`, `grep`) never appear here.

### `agent_log_text` / `agent_log_embedding`
**Omitted (not null)** on:

- Non-final super-steps (when the last AI message has pending
  `tool_calls`).
- All super-steps when no embedder is configured.

Present and populated on the final super-step of a user-visible turn.
The text is the joint of the first `human` message + the last `ai`
message, truncated to `max_search_text_bytes` (default 8 KiB).

## Indexable fields

Default indexes:

| Index name | Keys |
|---|---|
| `agent_log_thread_step_idx` | `(thread_id ASC, step ASC)` |
| `agent_log_thread_ts_idx` | `(thread_id ASC, ts DESC)` |
| `agent_log_user_ts_idx` | `(user_id ASC, ts DESC)` |
| `agent_log_ts_ttl_idx` (optional) | `(ts ASC)`, `expireAfterSeconds` |
| `agent_log_search_idx` (Atlas Search) | `agent_log_text`, `user_id` |
| `agent_log_vector_idx` (Atlas Vector) | `agent_log_embedding` (cosine), `user_id` filter |

## Schema evolution policy

- Additive changes (new fields) are minor-version events.
- Removed or renamed fields require a major version bump.
- A field marked "reserved" (e.g. `content_hash` in v0.1) may be
  populated in a later minor version; readers should already tolerate it.
