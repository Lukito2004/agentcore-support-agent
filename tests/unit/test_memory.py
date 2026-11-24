import pytest

from memory import MEMORY_ID_ENV, memory_session_manager, retrieval_namespaces


def test_namespaces_are_scoped_to_the_actor():
    namespaces = retrieval_namespaces("user-123")
    assert set(namespaces) == {"/users/user-123/preferences", "/users/user-123/facts"}
    assert all("*" not in ns and "{" not in ns for ns in namespaces)


def test_different_actors_never_share_a_namespace():
    assert set(retrieval_namespaces("alice")).isdisjoint(retrieval_namespaces("mallory"))


@pytest.mark.parametrize("actor_id", ["", "../other-user", "a/b"])
def test_unsafe_actor_ids_are_rejected(actor_id):
    with pytest.raises(ValueError):
        retrieval_namespaces(actor_id)


def test_no_memory_configured_means_no_session_manager(monkeypatch):
    monkeypatch.delenv(MEMORY_ID_ENV, raising=False)
    assert memory_session_manager("session-1", "user-123") is None
