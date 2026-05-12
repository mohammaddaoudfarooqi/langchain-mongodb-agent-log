"""Smoke test confirming the package imports and reports its version."""
from __future__ import annotations


def test_package_imports() -> None:
    import langchain_mongodb_agent_log as p

    assert p.__name__ == "langchain_mongodb_agent_log"
    assert p.__version__ == "0.2.0"


def test_public_api_names_listed() -> None:
    """Every name in __all__ must be a real string."""
    import langchain_mongodb_agent_log as p

    for name in p.__all__:
        assert isinstance(name, str) and name


def test_TC_107_scoped_user_and_current_user_id_at_package_root() -> None:
    """REQ-107 / INV-104: the v0.2 ContextVar primitives are importable
    from the package root via the lazy ``__getattr__`` mechanism, and
    are listed in ``__all__``.
    """
    import langchain_mongodb_agent_log as p

    # In __all__
    assert "scoped_user" in p.__all__
    assert "current_user_id" in p.__all__

    # Resolve via the lazy __getattr__
    from langchain_mongodb_agent_log import current_user_id, scoped_user

    assert callable(scoped_user)
    assert callable(current_user_id)
    # And they actually do something — round-trip
    with scoped_user("smoke"):
        assert current_user_id() == "smoke"
    assert current_user_id() is None
