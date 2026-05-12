"""Spec v0.2: ContextVar-based ``user_id`` propagation.

REQ-101..105, REQ-108. Per-task / per-thread isolation is the load-bearing
property; the rest is mechanical.
"""
from __future__ import annotations

import asyncio
import threading


def test_TC_101_default_is_None() -> None:
    """REQ-101 / REQ-102: default value of the scoped user_id is None."""
    from langchain_mongodb_agent_log.core.context import current_user_id

    assert current_user_id() is None


def test_TC_102a_set_via_scoped_user_visible_inside() -> None:
    """REQ-102 / REQ-103: scoped_user(...) makes current_user_id() return it."""
    from langchain_mongodb_agent_log.core.context import (
        current_user_id,
        scoped_user,
    )

    with scoped_user("alice"):
        assert current_user_id() == "alice"


def test_TC_103b_value_restored_on_exit() -> None:
    """REQ-103: __exit__ restores the previous value."""
    from langchain_mongodb_agent_log.core.context import (
        current_user_id,
        scoped_user,
    )

    assert current_user_id() is None
    with scoped_user("alice"):
        pass
    assert current_user_id() is None


def test_TC_103c_nested_scopes_pop_LIFO() -> None:
    """REQ-103: nested scope_user(...) calls pop in reverse order."""
    from langchain_mongodb_agent_log.core.context import (
        current_user_id,
        scoped_user,
    )

    with scoped_user("alice"):
        assert current_user_id() == "alice"
        with scoped_user("bob"):
            assert current_user_id() == "bob"
        # After exiting bob's scope, alice is restored, NOT None.
        assert current_user_id() == "alice"
    assert current_user_id() is None


def test_TC_108_value_restored_on_exception() -> None:
    """REQ-108: exception inside the with block still restores."""
    from langchain_mongodb_agent_log.core.context import (
        current_user_id,
        scoped_user,
    )

    class _Boom(RuntimeError):
        pass

    try:
        with scoped_user("alice"):
            raise _Boom("inside the scope")
    except _Boom:
        pass
    assert current_user_id() is None


async def test_TC_104_per_asyncio_task_isolation() -> None:
    """REQ-104: a value set in one Task does NOT leak into a sibling Task.

    Each ``asyncio.Task`` gets its own copy of the ContextVar context, so
    setting a value in task A is invisible in task B.
    """
    from langchain_mongodb_agent_log.core.context import (
        current_user_id,
        scoped_user,
    )

    saw_in_alice: list[str | None] = []
    saw_in_bob: list[str | None] = []
    alice_started = asyncio.Event()
    bob_started = asyncio.Event()

    async def _alice() -> None:
        with scoped_user("alice"):
            alice_started.set()
            # Wait for bob to set its value before reading ours.
            await bob_started.wait()
            saw_in_alice.append(current_user_id())

    async def _bob() -> None:
        await alice_started.wait()  # ensure alice has set first
        with scoped_user("bob"):
            bob_started.set()
            saw_in_bob.append(current_user_id())

    await asyncio.gather(_alice(), _bob())

    # Alice sees alice (her own task's value, not bob's).
    assert saw_in_alice == ["alice"]
    # Bob sees bob.
    assert saw_in_bob == ["bob"]


def test_TC_105_per_thread_isolation() -> None:
    """REQ-105: a value set in one thread does NOT leak into another."""
    from langchain_mongodb_agent_log.core.context import (
        current_user_id,
        scoped_user,
    )

    saw_in_alice: list[str | None] = []
    saw_in_bob: list[str | None] = []
    alice_inside = threading.Event()
    bob_inside = threading.Event()

    def _alice() -> None:
        with scoped_user("alice"):
            alice_inside.set()
            bob_inside.wait()
            saw_in_alice.append(current_user_id())

    def _bob() -> None:
        alice_inside.wait()
        with scoped_user("bob"):
            bob_inside.set()
            saw_in_bob.append(current_user_id())

    t_alice = threading.Thread(target=_alice)
    t_bob = threading.Thread(target=_bob)
    t_alice.start()
    t_bob.start()
    t_alice.join()
    t_bob.join()

    # NOTE: stdlib ``threading.Thread`` does NOT auto-copy the parent's
    # context, so each thread starts with the var unset. We're verifying
    # that values set inside thread A are invisible to thread B —
    # which is the property production code depends on.
    assert saw_in_alice == ["alice"]
    assert saw_in_bob == ["bob"]


def test_TC_103a_set_returns_None_yields() -> None:
    """REQ-103: the context manager yields None (not the set value)."""
    from langchain_mongodb_agent_log.core.context import scoped_user

    with scoped_user("alice") as yielded:
        assert yielded is None
