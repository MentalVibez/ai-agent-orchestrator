"""Unit tests for spend cap breach webhook notifications.

Tests:
- notify_cap_breach() POSTs correct payload when SPEND_CAP_WEBHOOK_URL is set
- notify_cap_breach() is a no-op when URL is empty
- notify_cap_breach() swallows httpx errors without raising
- Payload structure matches spec (event, api_key_id, monthly_spend_usd, cap_usd, text)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestNotifyCapBreach:
    @pytest.mark.asyncio
    async def test_posts_payload_when_url_configured(self):
        """Should POST JSON payload to the configured webhook URL."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_async_client_cm = MagicMock()
        mock_async_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.core.cap_notifications.settings") as mock_settings, \
             patch("app.core.cap_notifications.httpx") as mock_httpx:
            mock_settings.spend_cap_webhook_url = "https://hooks.example.com/notify"
            mock_httpx.AsyncClient.return_value = mock_async_client_cm

            from app.core.cap_notifications import notify_cap_breach

            await notify_cap_breach("kid_test_001", 12.50, 10.00)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        url_called = call_args[0][0]
        payload = call_args[1]["json"]

        assert url_called == "https://hooks.example.com/notify"
        assert payload["event"] == "spend_cap_breach"
        assert payload["api_key_id"] == "kid_test_001"
        assert payload["monthly_spend_usd"] == 12.5
        assert payload["cap_usd"] == 10.0
        assert "kid_test_001" in payload["text"]
        assert "10.00" in payload["text"]
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_noop_when_url_empty(self):
        """Should return immediately without making any HTTP calls when URL is empty."""
        with patch("app.core.cap_notifications.settings") as mock_settings, \
             patch("app.core.cap_notifications.httpx") as mock_httpx:
            mock_settings.spend_cap_webhook_url = ""

            from app.core.cap_notifications import notify_cap_breach

            await notify_cap_breach("kid_any", 5.0, 4.0)

        mock_httpx.AsyncClient.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_url_attribute_missing(self):
        """Should not crash when settings has no spend_cap_webhook_url attribute."""
        # Use a plain object with no spend_cap_webhook_url attribute so getattr returns ""
        class _EmptySettings:
            pass

        with patch("app.core.cap_notifications.settings", _EmptySettings()), \
             patch("app.core.cap_notifications.httpx") as mock_httpx:
            from app.core.cap_notifications import notify_cap_breach

            # getattr(settings, "spend_cap_webhook_url", "") → "" → no-op
            await notify_cap_breach("kid_any", 5.0, 4.0)

        mock_httpx.AsyncClient.assert_not_called()

    @pytest.mark.asyncio
    async def test_swallows_httpx_errors(self):
        """Network errors should be logged and swallowed — never raised to the caller."""
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=real_httpx.ConnectError("connection refused", request=MagicMock())
        )

        mock_async_client_cm = MagicMock()
        mock_async_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.core.cap_notifications.settings") as mock_settings, \
             patch("app.core.cap_notifications.httpx") as mock_httpx:
            mock_settings.spend_cap_webhook_url = "https://hooks.example.com/notify"
            mock_httpx.AsyncClient.return_value = mock_async_client_cm
            mock_httpx.ConnectError = real_httpx.ConnectError

            from app.core.cap_notifications import notify_cap_breach

            # Must not raise
            await notify_cap_breach("kid_err", 8.0, 5.0)

    @pytest.mark.asyncio
    async def test_swallows_raise_for_status_errors(self):
        """HTTP 4xx/5xx from the webhook should be logged and swallowed."""
        import httpx as real_httpx

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=real_httpx.HTTPStatusError(
                "500 Server Error",
                request=MagicMock(),
                response=MagicMock(),
            )
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_async_client_cm = MagicMock()
        mock_async_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.core.cap_notifications.settings") as mock_settings, \
             patch("app.core.cap_notifications.httpx") as mock_httpx:
            mock_settings.spend_cap_webhook_url = "https://hooks.example.com/notify"
            mock_httpx.AsyncClient.return_value = mock_async_client_cm

            from app.core.cap_notifications import notify_cap_breach

            await notify_cap_breach("kid_5xx", 8.0, 5.0)

    @pytest.mark.asyncio
    async def test_payload_spend_rounded_to_4_decimals(self):
        """monthly_spend_usd in payload should be rounded to 4 decimal places."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_async_client_cm = MagicMock()
        mock_async_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.core.cap_notifications.settings") as mock_settings, \
             patch("app.core.cap_notifications.httpx") as mock_httpx:
            mock_settings.spend_cap_webhook_url = "https://hooks.example.com/notify"
            mock_httpx.AsyncClient.return_value = mock_async_client_cm

            from app.core.cap_notifications import notify_cap_breach

            await notify_cap_breach("kid_round", 1.123456789, 1.0)

        payload = mock_client.post.call_args[1]["json"]
        # 4 decimal places
        assert payload["monthly_spend_usd"] == round(1.123456789, 4)
