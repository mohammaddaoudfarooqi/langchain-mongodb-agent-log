# How to provide custom embeddings

Goal: use OpenAI, Bedrock, a local model, or any other embedder
implementing the `langchain_core.embeddings.Embeddings` interface.

## OpenAI

```python
from langchain_openai import OpenAIEmbeddings
from langchain_mongodb_agent_log import AgentLog, ensure_search_indexes

embedder = OpenAIEmbeddings(model="text-embedding-3-small")
log = AgentLog(collection=db["agent_log"], embeddings=embedder)

ensure_search_indexes(db["agent_log"], embeddings_dim=1536)
# ^ text-embedding-3-small dimension is 1536
```

The vector index dimension must match the embedder's output. If you
change embedders later, you need to drop and re-create the vector index
(and re-embed historical documents — there's no in-place migration).

## Bedrock (Cohere, Titan)

```python
from langchain_aws import BedrockEmbeddings

embedder = BedrockEmbeddings(model_id="cohere.embed-english-v3")
log = AgentLog(collection=db["agent_log"], embeddings=embedder)

ensure_search_indexes(db["agent_log"], embeddings_dim=1024)
```

## Local sentence-transformers

```python
from langchain_huggingface import HuggingFaceEmbeddings

embedder = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")
log = AgentLog(collection=db["agent_log"], embeddings=embedder)

ensure_search_indexes(db["agent_log"], embeddings_dim=768)
```

Local embedders skip the network round-trip; the engine's worker still
absorbs the CPU work off the agent's hot path.

## No embeddings (storage only)

Skip the `embeddings=` argument. The log collection is still populated;
search-related fields (`agent_log_text`, `agent_log_embedding`) are
omitted from documents. The hybrid retriever / `search_past_conversations`
tool will still construct, but RRF results will be lexical-only.

```python
log = AgentLog(collection=db["agent_log"])  # no embeddings
```

## See also

- [Reference: configuration](../reference/configuration.md) — full
  constructor signature.
- [Architecture](../explanation/architecture.md) — when the embedder
  is actually called (only on the final super-step of a turn).
