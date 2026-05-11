"""Projection unit tests — REQ-002, REQ-003, REQ-004, REQ-005, REQ-009."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def _msg(*, type: str, content: Any, **extra: Any) -> Any:
    m = MagicMock()
    m.type = type
    m.content = content
    m.tool_calls = extra.get("tool_calls", [])
    m.tool_call_id = extra.get("tool_call_id")
    m.usage_metadata = extra.get("usage_metadata")
    m.additional_kwargs = extra.get("additional_kwargs", {})
    return m


# REQ-002: verbatim message fields
def test_TC_002_message_fields_projected_verbatim() -> None:
    from langchain_mongodb_agent_log.core.projection import project_messages

    msg = _msg(
        type="ai",
        content="reply",
        usage_metadata={"input_tokens": 10},
        additional_kwargs={"model_id": "claude-haiku", "stop_reason": "end_turn"},
    )
    out = project_messages([msg], cap=1024)
    assert len(out) == 1
    p = out[0]
    assert p["type"] == "ai"
    assert p["content"] == "reply"
    assert p["tool_calls"] == []
    assert p["tool_call_id"] is None
    assert p["usage"] == {"input_tokens": 10}
    assert p["model_id"] == "claude-haiku"
    assert p["finish_reason"] == "end_turn"


# REQ-003a: under-cap content stored verbatim, no marker
def test_TC_003a_content_under_cap_no_marker() -> None:
    from langchain_mongodb_agent_log.core.projection import project_messages

    body = "x" * 1000
    out = project_messages([_msg(type="human", content=body)], cap=4096)
    assert out[0]["content"] == body
    assert "[truncated" not in out[0]["content"]


# REQ-003b: over-cap content truncated with size marker
def test_TC_003b_content_over_cap_truncation_marker() -> None:
    from langchain_mongodb_agent_log.core.projection import project_messages

    body = "x" * 200
    out = project_messages([_msg(type="human", content=body)], cap=100)
    c = out[0]["content"]
    assert c.startswith("x" * 100)
    assert "truncated, original_size=200" in c


# REQ-004: todos copied verbatim
def test_TC_004_todos_copied() -> None:
    from langchain_mongodb_agent_log.core.projection import project_todos

    raw = [
        {"id": "1", "content": "Outline", "status": "in_progress"},
        {"id": "2", "content": "Draft", "status": "pending"},
    ]
    assert project_todos(raw) == raw


def test_TC_004_todos_normalize_unknown_status() -> None:
    from langchain_mongodb_agent_log.core.projection import project_todos

    raw = [{"id": "1", "content": "X", "status": "weird"}]
    assert project_todos(raw)[0]["status"] == "pending"


def test_TC_004_todos_text_alias_accepted() -> None:
    from langchain_mongodb_agent_log.core.projection import project_todos

    raw = [{"id": "1", "text": "Outline", "status": "in_progress"}]
    out = project_todos(raw)
    assert out[0]["content"] == "Outline"


# REQ-005a: write+edit on same path → single dedup, edit wins
def test_TC_005a_write_then_edit_dedup_edit_wins() -> None:
    from langchain_mongodb_agent_log.core.projection import project_files

    write = {"name": "write_file", "args": {"file_path": "/w/a.md", "content": "hello"}}
    edit = {
        "name": "edit_file",
        "args": {"file_path": "/w/a.md", "old_string": "hello", "new_string": "hi"},
    }
    state_msgs = [_msg(type="ai", content="", tool_calls=[write, edit])]
    out = project_files(state_msgs, fs_write_tools=frozenset({"write_file", "edit_file"}))
    assert len(out) == 1
    assert out[0]["path"] == "/w/a.md"
    assert out[0]["op"] == "edit"
    assert out[0]["size"] == len("hi")


# REQ-005b: read_file ignored
def test_TC_005b_read_file_ignored() -> None:
    from langchain_mongodb_agent_log.core.projection import project_files

    read = {"name": "read_file", "args": {"file_path": "/w/a.md"}}
    out = project_files(
        [_msg(type="ai", content="", tool_calls=[read])],
        fs_write_tools=frozenset({"write_file", "edit_file"}),
    )
    assert out == []


# REQ-005c: configurable fs_write_tools
def test_TC_005c_custom_fs_write_tools() -> None:
    from langchain_mongodb_agent_log.core.projection import project_files

    custom = {"name": "save_blob", "args": {"path": "/x/b.bin", "content": b"\0\1\2"}}
    out = project_files(
        [_msg(type="ai", content="", tool_calls=[custom])],
        fs_write_tools=frozenset({"save_blob"}),
    )
    assert len(out) == 1
    assert out[0]["path"] == "/x/b.bin"
    assert out[0]["size"] == 3


# REQ-009: Bedrock content list coerced to string
def test_TC_009_bedrock_content_list_coerced() -> None:
    from langchain_mongodb_agent_log.core.projection import project_messages

    blocks = [
        {"type": "text", "text": "hi"},
        {"type": "text", "text": " world"},
    ]
    out = project_messages([_msg(type="ai", content=blocks)], cap=1024)
    assert out[0]["content"] == "hi world"


def test_TC_009b_bedrock_tool_use_block_dropped() -> None:
    from langchain_mongodb_agent_log.core.projection import project_messages

    blocks = [
        {"type": "text", "text": "calling tool..."},
        {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
    ]
    out = project_messages([_msg(type="ai", content=blocks)], cap=1024)
    assert out[0]["content"] == "calling tool..."


# REQ-010 / REQ-011: final-step detection
def test_is_final_step_detection() -> None:
    from langchain_mongodb_agent_log.core.projection import is_final_step

    final_msgs = [
        {"type": "human", "content": "q"},
        {"type": "ai", "content": "a", "tool_calls": []},
    ]
    not_final = [
        {"type": "human", "content": "q"},
        {"type": "ai", "content": "", "tool_calls": [{"name": "x"}]},
    ]
    no_ai = [{"type": "human", "content": "q"}]

    assert is_final_step(final_msgs) is True
    assert is_final_step(not_final) is False
    assert is_final_step(no_ai) is False


# REQ-012: search text truncated at cap
def test_build_search_text_truncates() -> None:
    from langchain_mongodb_agent_log.core.projection import build_search_text

    msgs = [
        {"type": "human", "content": "x" * 100},
        {"type": "ai", "content": "y" * 100, "tool_calls": []},
    ]
    text = build_search_text(msgs, cap=50)
    assert len(text) == 50


def test_build_search_text_joins_human_and_final_ai() -> None:
    from langchain_mongodb_agent_log.core.projection import build_search_text

    msgs = [
        {"type": "human", "content": "Q"},
        {"type": "ai", "content": "", "tool_calls": [{"name": "x"}]},
        {"type": "tool", "content": "result", "tool_calls": []},
        {"type": "ai", "content": "A", "tool_calls": []},
    ]
    text = build_search_text(msgs, cap=8192)
    # picks first human, last ai
    assert "Q" in text and "A" in text
