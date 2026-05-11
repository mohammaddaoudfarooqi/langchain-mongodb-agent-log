# Comparison with LangSmith

LangSmith ships an MCP server and a public REST/SDK API, so the casual
"LangSmith is just a UI" framing is wrong. It does have a runtime
surface agents can call. But the surfaces solve different problems.
This page is about where the line is.

## What LangSmith is good at

- **Trace observability with a UI.** Click into a run, see every node,
  every LLM call, every tool call, with full inputs and outputs.
- **Run comparison and replay.** Diff two traces, replay a failed run.
- **Eval datasets.** Extract example IO from runs, version it, attach
  rubrics.
- **Cost / latency / token rollups.** Per-project dashboards.
- **Trace search.** Metadata filters, text search up to 250 characters
  per field (per the docs), pagination by char-budget.
- **MCP server** ([`langchain-ai/langsmith-mcp-server`](https://github.com/langchain-ai/langsmith-mcp-server))
  exposes `fetch_runs`, `get_thread_history`, `list_projects`, prompt /
  dataset / experiment helpers. Agents can call it.

If your problem is "engineers debugging in a UI" or "compose evals from
production runs", LangSmith is the right primary tool.

## Where this package fills a gap

**Per-user semantic recall, in-loop, in your own database.**

LangSmith's text search is metadata + truncated substring match. There
is no `$vectorSearch` equivalent in their public API. There is no RRF
hybrid retriever. There is no "find conversations across this user's
threads ranked by similarity" primitive. You can build something on top
of `fetch_runs` paginated through the SDK, but it's not the abstraction
they ship.

This package gives you exactly that primitive:

- Hybrid (`$search` + `$vectorSearch`) RRF.
- Per-user `pre_filter`, mandatory and verified at the API surface.
- One round-trip; results are LangChain `Document` objects.

## When self-hosting matters

LangSmith Cloud sends every prompt and every tool I/O to LangChain
Inc.'s infrastructure. For workloads under HIPAA, GDPR EU residency,
SOC 2 Type II, or air-gapped deployment requirements, that's a
non-starter without LangSmith Self-Hosted (an enterprise SKU with its
own Postgres + Redis + object-storage footprint).

This package writes to your existing Atlas cluster. No new
infrastructure, no third party in the data path.

## When you'd run both

Most teams. The combination looks like:

- **LangSmith** for engineering observability — the dashboards, the
  diff tools, the eval pipelines, the on-call dashboards.
- **`langchain-mongodb-agent-log`** for the in-loop primitive — the
  agent's `search_past_conversations` tool, application-owned
  conversation data, per-user retrieval, queryable audit.

These don't compete; they fit different parts of the stack. The agent
log's pitch isn't "replace LangSmith." It's "the retrieval primitive
LangSmith doesn't have."

## Cost model

LangSmith is per-trace pricing. At a high enough volume, "the agent
calls the trace API as a tool" becomes a budget line item the
finance team will eventually want eliminated. This package's cost is
just storage cost on your existing cluster — typically a rounding
error.

## See also

- [Why not a checkpointer?](why-not-checkpointer.md)
- [Architecture](architecture.md)
