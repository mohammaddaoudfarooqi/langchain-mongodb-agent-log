# Documentation

This site follows the [Diataxis](https://diataxis.fr) framework: four
distinct kinds of documentation, each with a single purpose.

| Quadrant | Purpose | Files |
|---|---|---|
| **Tutorial** — learning-oriented | "Walk me through it." | [`tutorial/`](tutorial/) |
| **How-to guide** — task-oriented | "Show me how to do X." | [`how-to/`](how-to/) |
| **Reference** — information-oriented | "What does this name mean?" | [`reference/`](reference/) |
| **Explanation** — understanding-oriented | "Why does this exist?" | [`explanation/`](explanation/) |

## Tutorials

Start here if you've never used the package.

- [First log](tutorial/first-log.md) — go from an empty database to your
  first persisted agent turn in under 10 minutes.
- [Hybrid search](tutorial/hybrid-search.md) — give your agent the ability
  to recall its own past conversations.

## How-to guides

Recipes for specific tasks. Skim the headings; pick the one matching your
graph shape.

- [`create_agent` single agent](how-to/create-agent.md)
- [Deep agents](how-to/deepagents.md)
- [Multi-agent supervisor](how-to/multi-agent-supervisor.md)
- [Bare `StateGraph`](how-to/bare-stategraph.md) — and migrating from
  `create_react_agent`
- [Migrate from `create_react_agent`](how-to/migrate-from-create-react-agent.md)
- [Configure TTL retention](how-to/configure-ttl.md)
- [Provide custom embeddings](how-to/provide-custom-embeddings.md)
- [Per-user scoping with ContextVar](how-to/per-user-scoping-with-contextvar.md) *(v0.2+)*

## Reference

Look these up; don't read them top to bottom.

- [API](reference/api.md) — every name in `__all__`.
- [Document shape](reference/document-shape.md) — the persisted JSON
  schema, field by field.
- [Indexes](reference/indexes.md) — index DDL details.
- [Configuration](reference/configuration.md) — constructor arguments and
  defaults.

## Explanations

Read these when you want to understand the design rather than make
something work.

- **[Why this package exists](explanation/why-this-exists.md)** — the
  problem, the four alternatives that fall short, and a decision
  rubric. Start here if you're evaluating whether to adopt this.
- [Architecture](explanation/architecture.md) — engine + adapter +
  worker boundary.
- [Why not a checkpointer?](explanation/why-not-checkpointer.md) — the
  difference vs. `MongoDBSaver`, with side-by-side data model.
- [Comparison with LangSmith](explanation/langsmith-comparison.md) — what
  LangSmith does and doesn't cover for in-loop agent recall.
