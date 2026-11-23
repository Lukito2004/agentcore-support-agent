import base64
import json

import pytest

from caller import LOCAL_DEV_CALLER, AuthError, SessionRegistry, caller_from_headers


def make_token(**claims) -> str:
    """Unsigned JWT; signature checks happen in the Runtime authorizer, not in this code."""

    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.signature"


VALID = {"sub": "user-123", "token_use": "access", "customer_id": "CUST-1001"}


def without(claim: str) -> dict:
    return {key: value for key, value in VALID.items() if key != claim}


@pytest.fixture(autouse=True)
def deployed(monkeypatch):
    monkeypatch.delenv("LOCAL_DEV", raising=False)


def test_caller_comes_from_token_claims():
    caller = caller_from_headers({"Authorization": f"Bearer {make_token(**VALID)}"})
    assert caller.actor_id == "user-123"
    assert caller.customer_id == "CUST-1001"


def test_header_name_is_case_insensitive():
    caller = caller_from_headers({"authorization": f"bearer {make_token(**VALID)}"})
    assert caller.customer_id == "CUST-1001"


def test_log_id_hides_the_raw_user_id():
    caller = caller_from_headers({"Authorization": f"Bearer {make_token(**VALID)}"})
    assert "user-123" not in caller.log_id
    assert len(caller.log_id) == 12


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        (None, "missing bearer token"),
        ({}, "missing bearer token"),
        ({"Authorization": "Basic abc"}, "expected a bearer token"),
        ({"Authorization": "Bearer not-a-jwt"}, "malformed"),
        ({"Authorization": "Bearer a.!!!.c"}, "malformed"),
        ({"Authorization": f"Bearer {make_token(**{**VALID, 'token_use': 'id'})}"}, "access token"),
        ({"Authorization": f"Bearer {make_token(**without('sub'))}"}, "subject"),
        ({"Authorization": f"Bearer {make_token(**without('customer_id'))}"}, "not linked"),
        (
            {"Authorization": f"Bearer {make_token(**{**VALID, 'customer_id': '1001'})}"},
            "not linked",
        ),
    ],
)
def test_unidentifiable_callers_are_rejected(headers, reason):
    with pytest.raises(AuthError, match=reason):
        caller_from_headers(headers)


def test_local_dev_falls_back_to_a_test_caller(monkeypatch):
    monkeypatch.setenv("LOCAL_DEV", "1")
    assert caller_from_headers({}) == LOCAL_DEV_CALLER


def test_session_is_bound_to_its_first_user():
    sessions = SessionRegistry()
    assert sessions.claim("session-1", "alice") is True
    assert sessions.claim("session-1", "alice") is True
    assert sessions.claim("session-1", "mallory") is False
    assert sessions.claim("session-2", "mallory") is True
