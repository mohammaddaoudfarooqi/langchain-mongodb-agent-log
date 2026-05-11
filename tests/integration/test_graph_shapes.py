"""Multi-graph integration tests — validate the adapter set against every
graph shape v0.1 commits to supporting.

Hermetic. Uses ``FakeMessagesListChatModel`` from langchain-core so no live
LLM is required. Mongomock is the storage backend.

Shapes covered:

- A. ``create_agent`` single
- B. ``create_agent`` multi-agent supervisor + workers (via top-level
     ``StateGraph`` composition; modern multi-agent shape)
- C. Bare ``StateGraph`` with hand-rolled nodes calling ``llm.invoke``
- D. Mixed: raw supervisor node + ``create_agent`` workers
"""
from __future__ import annotations

# NOTE: not marked ``integration`` — these tests are hermetic (mongomock +
# FakeMessagesListChatModel) and run on the unit tier so the four-graph-shape
# matrix is part of the always-on contract. The Atlas-DDL tests in
# ``test_atlas_*.py`` are the ones that gate on ``ATLAS_URI``.
from typing import Any

import mongomock
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


def _make_log() -> Any:
    from langchain_mongodb_agent_log import AgentLog

    coll = mongomock.MongoClient()["t"]["agent_log"]
    return AgentLog(collection=coll), coll


# ---------------------------------------------------------------------------
# Shape A: create_agent single
# ---------------------------------------------------------------------------


def test_shape_A_create_agent_single() -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    log, coll = _make_log()
    model = FakeMessagesListChatModel(responses=[AIMessage(content="hello back")])
    agent = create_agent(
        model=model,
        tools=[],
        middleware=[AgentLogMiddleware(log)],
    )
    agent.invoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": "t1", "user_id": "u1"}},
    )
    log.flush_for_tests()
    assert coll.count_documents({}) >= 1
    doc = coll.find_one({})
    assert doc["agent_name"] == "main"
    assert doc["thread_id"] == "t1"


# ---------------------------------------------------------------------------
# Shape B: create_agent multi-agent supervisor + workers
# ---------------------------------------------------------------------------


class _SuperState(TypedDict, total=False):
    messages: list[Any]


def test_shape_B_create_agent_multi_agent() -> None:
    from langchain_mongodb_agent_log import AgentLogMiddleware

    log, coll = _make_log()

    researcher = create_agent(
        model=FakeMessagesListChatModel(
            responses=[AIMessage(content="research result")]
        ),
        tools=[],
        middleware=[AgentLogMiddleware(log)],
        name="researcher",
    )
    writer = create_agent(
        model=FakeMessagesListChatModel(
            responses=[AIMessage(content="written result")]
        ),
        tools=[],
        middleware=[AgentLogMiddleware(log)],
        name="writer",
    )

    def _researcher_node(state: _SuperState, config: RunnableConfig) -> dict[str, Any]:
        # Inject agent_name via the configurable so the middleware records it.
        cfg = {
            **(config or {}),
            "configurable": {**(config or {}).get("configurable", {}), "agent_name": "researcher"},
        }
        out = researcher.invoke({"messages": state["messages"]}, config=cfg)
        return {"messages": out.get("messages", [])}

    def _writer_node(state: _SuperState, config: RunnableConfig) -> dict[str, Any]:
        cfg = {
            **(config or {}),
            "configurable": {**(config or {}).get("configurable", {}), "agent_name": "writer"},
        }
        out = writer.invoke({"messages": state["messages"]}, config=cfg)
        return {"messages": out.get("messages", [])}

    builder: StateGraph[_SuperState, Any, Any, Any] = StateGraph(_SuperState)
    builder.add_node("researcher", _researcher_node)
    builder.add_node("writer", _writer_node)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "writer")
    builder.add_edge("writer", END)
    graph = builder.compile()

    graph.invoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": "tm", "user_id": "u1"}},
    )
    log.flush_for_tests()

    names = {d["agent_name"] for d in coll.find({})}
    assert "researcher" in names and "writer" in names


# ---------------------------------------------------------------------------
# Shape C: bare StateGraph with hand-rolled nodes calling llm.invoke
# ---------------------------------------------------------------------------


def test_shape_C_bare_stategraph_via_callback() -> None:
    from langchain_mongodb_agent_log import AgentLogCallbackHandler

    log, coll = _make_log()
    handler = AgentLogCallbackHandler(log, user_id="u1")

    supervisor_model = FakeMessagesListChatModel(responses=[AIMessage(content="route to research")])
    research_model = FakeMessagesListChatModel(responses=[AIMessage(content="research done")])

    def _supervisor(state: _SuperState, config: RunnableConfig) -> dict[str, Any]:
        out = supervisor_model.invoke(state["messages"])
        return {"messages": [*state["messages"], out]}

    def _research(state: _SuperState, config: RunnableConfig) -> dict[str, Any]:
        out = research_model.invoke(state["messages"])
        return {"messages": [*state["messages"], out]}

    builder: StateGraph[_SuperState, Any, Any, Any] = StateGraph(_SuperState)
    builder.add_node("supervisor", _supervisor)
    builder.add_node("research", _research)
    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "research")
    builder.add_edge("research", END)
    graph = builder.compile()

    graph.invoke(
        {"messages": [HumanMessage(content="hi")]},
        config={
            "configurable": {"thread_id": "tc", "user_id": "u1"},
            "callbacks": [handler],
        },
    )
    log.flush_for_tests()

    names = {d["agent_name"] for d in coll.find({})}
    # Both top-level nodes should attribute themselves
    assert "supervisor" in names and "research" in names


# ---------------------------------------------------------------------------
# Shape D: mixed — raw supervisor + create_agent workers
# ---------------------------------------------------------------------------


def test_shape_D_mixed_graph() -> None:
    from langchain_mongodb_agent_log import (
        AgentLogCallbackHandler,
        AgentLogMiddleware,
    )

    log, coll = _make_log()
    handler = AgentLogCallbackHandler(log, user_id="u1")

    worker = create_agent(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="worker done")]),
        tools=[],
        middleware=[AgentLogMiddleware(log)],
        name="worker",
    )
    sup_model = FakeMessagesListChatModel(responses=[AIMessage(content="dispatch")])

    def _supervisor(state: _SuperState, config: RunnableConfig) -> dict[str, Any]:
        out = sup_model.invoke(state["messages"])
        return {"messages": [*state["messages"], out]}

    def _worker_node(state: _SuperState, config: RunnableConfig) -> dict[str, Any]:
        cfg = {
            **(config or {}),
            "configurable": {**(config or {}).get("configurable", {}), "agent_name": "worker"},
        }
        out = worker.invoke({"messages": state["messages"]}, config=cfg)
        return {"messages": out.get("messages", [])}

    builder: StateGraph[_SuperState, Any, Any, Any] = StateGraph(_SuperState)
    builder.add_node("supervisor", _supervisor)
    builder.add_node("worker", _worker_node)
    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "worker")
    builder.add_edge("worker", END)
    graph = builder.compile()

    graph.invoke(
        {"messages": [HumanMessage(content="hi")]},
        config={
            "configurable": {"thread_id": "tx", "user_id": "u1"},
            "callbacks": [handler],
        },
    )
    log.flush_for_tests()

    names = {d["agent_name"] for d in coll.find({})}
    # Both supervisor (callback) and worker (middleware + callback) should
    # appear; we just assert presence — duplicates are acceptable for a
    # mixed-shape graph in v0.1, since middleware fires on the worker's
    # internal supersteps and callback fires on the outer node end.
    assert "supervisor" in names
    assert "worker" in names
