"""Unit tests for app/integrations/slack.py."""

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.integrations.slack import (
    _parse_command,
    _verify_slack_signature,
)


# ---------------------------------------------------------------------------
# _verify_slack_signature
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifySlackSignature:
    def _make_sig(self, secret: str, body: bytes, timestamp: str) -> str:
        base = f"v0:{timestamp}:{body.decode()}"
        return "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()

    def test_valid_signature_passes(self):
        secret = "test-secret"
        body = b"text=hello&response_url=http://x"
        ts = str(int(time.time()))
        sig = self._make_sig(secret, body, ts)
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = secret
            assert _verify_slack_signature(body, ts, sig) is True

    def test_invalid_signature_fails(self):
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = "real-secret"
            assert _verify_slack_signature(b"body", str(int(time.time())), "v0=badsig") is False

    def test_stale_timestamp_fails(self):
        secret = "test-secret"
        old_ts = str(int(time.time()) - 400)  # 400 seconds ago > 300s window
        body = b"body"
        sig = self._make_sig(secret, body, old_ts)
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = secret
            assert _verify_slack_signature(body, old_ts, sig) is False

    def test_no_secret_configured_returns_true(self):
        """When SLACK_SIGNING_SECRET is empty, verification is skipped (dev mode)."""
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = ""
            assert _verify_slack_signature(b"body", "123", "v0=anything") is True

    def test_malformed_timestamp_fails(self):
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = "secret"
            assert _verify_slack_signature(b"body", "not-a-number", "v0=x") is False


# ---------------------------------------------------------------------------
# _parse_command
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseCommand:
    def test_plain_goal(self):
        kind, goal, params = _parse_command("Check disk on prod-01")
        assert kind == "run"
        assert goal == "Check disk on prod-01"
        assert params == {}

    def test_template_with_params(self):
        kind, name, params = _parse_command("template disk-health-check host=prod-01 threshold_percent=90")
        assert kind == "template"
        assert name == "disk-health-check"
        assert params == {"host": "prod-01", "threshold_percent": "90"}

    def test_template_no_params(self):
        kind, name, params = _parse_command("template disk-health-check")
        assert kind == "template"
        assert name == "disk-health-check"
        assert params == {}

    def test_status_command(self):
        kind, run_id, params = _parse_command("status abc-123-xyz")
        assert kind == "status"
        assert run_id == "abc-123-xyz"
        assert params == {}

    def test_template_keyword_case_insensitive(self):
        kind, name, _ = _parse_command("TEMPLATE ssl-cert-check domain=x.com")
        assert kind == "template"
        assert name == "ssl-cert-check"

    def test_status_keyword_case_insensitive(self):
        kind, run_id, _ = _parse_command("STATUS run-id-123")
        assert kind == "status"
        assert run_id == "run-id-123"

    def test_empty_template_falls_back_to_run(self):
        """'template' with no name falls back to run."""
        kind, goal, _ = _parse_command("template")
        assert kind == "run"

    def test_leading_trailing_whitespace_stripped(self):
        kind, goal, _ = _parse_command("  Check disk  ")
        assert kind == "run"
        assert goal == "Check disk"

    def test_param_with_value_containing_no_equals_ignored(self):
        kind, name, params = _parse_command("template t host=prod-01 bare_word")
        assert "host" in params
        assert "bare_word" not in params


# ---------------------------------------------------------------------------
# Slack HTTP endpoint tests
# ---------------------------------------------------------------------------


def _make_slack_body(text: str = "Check disk on prod-01", command: str = "/orchestrate") -> bytes:
    from urllib.parse import urlencode
    return urlencode({
        "text": text,
        "command": command,
        "response_url": "https://hooks.slack.com/fake",
        "channel_id": "C123",
    }).encode()


@pytest.fixture()
def slack_client():
    """TestClient with Slack signing secret disabled (dev mode)."""
    from fastapi import FastAPI
    from app.integrations.slack import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
class TestSlackCommandEndpoint:
    def test_returns_200_with_ack(self, slack_client):
        body = _make_slack_body()
        ts = str(int(time.time()))
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = ""  # skip sig check
            s.slack_bot_token = ""
            s.max_concurrent_runs_per_key = 0
            response = slack_client.post(
                "/api/v1/integrations/slack/command",
                content=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": "v0=skip",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert "Processing" in data.get("text", "") or "processing" in data.get("text", "").lower()

    def test_invalid_signature_returns_401(self, slack_client):
        body = _make_slack_body()
        ts = str(int(time.time()))
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = "real-secret"
            response = slack_client.post(
                "/api/v1/integrations/slack/command",
                content=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": "v0=badsig",
                },
            )
        assert response.status_code == 401


@pytest.mark.unit
class TestSlackEventsEndpoint:
    def test_url_verification_challenge(self, slack_client):
        ts = str(int(time.time()))
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = ""
            response = slack_client.post(
                "/api/v1/integrations/slack/events",
                json={"type": "url_verification", "challenge": "test-challenge-token"},
                headers={
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": "v0=skip",
                },
            )
        assert response.status_code == 200
        assert response.json()["challenge"] == "test-challenge-token"

    def test_app_mention_returns_ok(self, slack_client):
        ts = str(int(time.time()))
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = ""
            s.slack_bot_token = ""
            response = slack_client.post(
                "/api/v1/integrations/slack/events",
                json={
                    "type": "event_callback",
                    "event": {
                        "type": "app_mention",
                        "text": "<@U123> Check disk on prod-01",
                        "channel": "C123",
                    },
                },
                headers={
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": "v0=skip",
                },
            )
        assert response.status_code == 200
        assert response.json().get("ok") is True

    def test_unknown_event_type_returns_ok(self, slack_client):
        ts = str(int(time.time()))
        with patch("app.integrations.slack.settings") as s:
            s.slack_signing_secret = ""
            response = slack_client.post(
                "/api/v1/integrations/slack/events",
                json={"type": "event_callback", "event": {"type": "reaction_added"}},
                headers={
                    "X-Slack-Request-Timestamp": ts,
                    "X-Slack-Signature": "v0=skip",
                },
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Teams HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def teams_client():
    from fastapi import FastAPI
    from app.integrations.slack import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
class TestTeamsMessageEndpoint:
    def test_message_activity_accepted(self, teams_client):
        with patch("app.integrations.slack.settings") as s:
            s.teams_app_id = ""  # skip token check
            s.teams_app_password = ""
            response = teams_client.post(
                "/api/v1/integrations/teams/message",
                json={
                    "type": "message",
                    "text": "Check disk on prod-01",
                    "serviceUrl": "https://smba.trafficmanager.net/",
                    "conversation": {"id": "conv-123"},
                    "id": "act-456",
                },
                headers={"Authorization": "Bearer fake-token"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

    def test_non_message_activity_ignored(self, teams_client):
        with patch("app.integrations.slack.settings") as s:
            s.teams_app_id = ""
            response = teams_client.post(
                "/api/v1/integrations/teams/message",
                json={"type": "typing"},
                headers={"Authorization": "Bearer fake"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
