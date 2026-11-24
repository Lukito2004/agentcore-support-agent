import pytest

from model.settings import guardrail_config


def test_guardrail_is_applied_when_configured():
    config = guardrail_config({"GUARDRAIL_ID": "gr-123", "GUARDRAIL_VERSION": "1"})
    assert config["guardrail_id"] == "gr-123"
    assert config["guardrail_version"] == "1"
    assert config["guardrail_trace"] == "enabled"
    assert config["guardrail_latest_message"] is True
    assert config["guardrail_redact_input"] is True


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"GUARDRAIL_ID": "gr-123"},
        {"GUARDRAIL_VERSION": "1"},
        {"GUARDRAIL_ID": "", "GUARDRAIL_VERSION": "1"},
    ],
)
def test_no_guardrail_without_both_settings(env):
    assert guardrail_config(env) == {}
