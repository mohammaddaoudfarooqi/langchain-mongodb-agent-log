"""Pure projection helpers — turn LangChain messages / agent state into the
JSON-shaped log document.

These functions are framework-agnostic: they take plain objects (with
``getattr`` for message attributes) and return plain dicts. No I/O.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_ALLOWED_TODO_STATUS = ("pending", "in_progress", "completed")


def coerce_content(message: Any) -> str:
    """Project a LangChain message's ``content`` to a plain string.

    Bedrock returns content as either a string or a list of structured
    blocks. The list form must collapse to a string before storage.
    """
    c = getattr(message, "content", "") or ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(c)


def truncate(text: str, cap: int) -> str:
    if cap <= 0 or len(text) <= cap:
        return text
    return text[:cap] + f"\n[truncated, original_size={len(text)} bytes]"


def project_messages(raw: Iterable[Any], *, cap: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in raw:
        content = truncate(coerce_content(m), cap)
        out.append(
            {
                "type": getattr(m, "type", "ai"),
                "content": content,
                "tool_calls": list(getattr(m, "tool_calls", []) or []),
                "tool_call_id": getattr(m, "tool_call_id", None),
                "usage": getattr(m, "usage_metadata", None),
                "model_id": (getattr(m, "additional_kwargs", {}) or {}).get("model_id"),
                "finish_reason": (getattr(m, "additional_kwargs", {}) or {}).get(
                    "stop_reason"
                ),
            }
        )
    return out


def project_todos(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for t in raw:
        if not isinstance(t, Mapping):
            continue
        status = t.get("status")
        if status not in _ALLOWED_TODO_STATUS:
            status = "pending"
        out.append(
            {
                "id": str(t.get("id", "")),
                "content": str(t.get("content") or t.get("text") or ""),
                "status": status,
            }
        )
    return out


def project_files(
    messages: Iterable[Any],
    *,
    fs_write_tools: frozenset[str],
) -> list[dict[str, Any]]:
    """Derive ``files_touched`` from AI-message ``tool_calls``.

    Latest call per path wins (a write followed by an edit reports a single
    entry whose ``op`` is ``edit``). Read-only tools are ignored entirely.
    """
    seen: dict[str, dict[str, Any]] = {}
    for m in messages:
        if getattr(m, "type", None) != "ai":
            continue
        for tc in getattr(m, "tool_calls", None) or []:
            if not isinstance(tc, Mapping):
                continue
            name = tc.get("name") or ""
            if name not in fs_write_tools:
                continue
            args = tc.get("args") or {}
            if not isinstance(args, Mapping):
                continue
            path = args.get("file_path") or args.get("path")
            if not isinstance(path, str) or not path:
                continue
            size = 0
            content = args.get("content")
            if isinstance(content, (str, bytes)):
                size = len(content)
            else:
                new_string = args.get("new_string")
                if isinstance(new_string, (str, bytes)):
                    size = len(new_string)
            seen[path] = {
                "path": path,
                "size": size,
                "content_hash": None,
                "op": "write" if name == "write_file" else "edit",
            }
    out = list(seen.values())
    out.sort(key=lambda d: d.get("path", ""))
    return out


def is_final_step(messages_proj: Sequence[Mapping[str, Any]]) -> bool:
    """A super-step is "final" when the last AI message has no pending tool_calls."""
    last_ai = next((m for m in reversed(messages_proj) if m.get("type") == "ai"), None)
    if last_ai is None:
        return False
    return not (last_ai.get("tool_calls") or [])


def build_search_text(
    messages_proj: Sequence[Mapping[str, Any]], *, cap: int
) -> str:
    """Joint ``human + final-ai`` text for hybrid search; truncated to ``cap``."""
    human = next((m for m in messages_proj if m.get("type") == "human"), None)
    ai = next((m for m in reversed(messages_proj) if m.get("type") == "ai"), None)
    if human is None or ai is None:
        return ""
    text = (human.get("content") or "") + "\n\n" + (ai.get("content") or "")
    if 0 < cap < len(text):
        text = text[:cap]
    return text
