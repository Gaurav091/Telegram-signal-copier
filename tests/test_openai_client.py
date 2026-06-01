import io
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from telegram_signal_copier.adapters.openai_client import OpenAIClient


class SimpleConfig:
    def __init__(self, providers, max_rpm=60, cooldown=1, max_cool=60, cache_ttl=300):
        self.openai_model = "gpt-test"
        self.ai_providers = providers
        self.ai_max_requests_per_minute = max_rpm
        self.ai_provider_cooldown_seconds = cooldown
        self.ai_provider_max_cooldown_seconds = max_cool
        self.ai_cache_ttl_seconds = cache_ttl
        self.cloudflare_account_id = None


def _make_requests_response(data: dict) -> MagicMock:
    """Build a mock requests.Response-like object."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data
    resp.text = json.dumps(data)
    resp.raise_for_status.return_value = None
    return resp


def _make_requests_http_error(status_code: int, body: str) -> Exception:
    """Build a mock requests.exceptions.HTTPError."""
    import requests
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = body
    exc = requests.exceptions.HTTPError(response=mock_resp)
    return exc


class OpenAIClientTests(unittest.TestCase):
    def test_cache_prevents_repeated_requests(self):
        config = SimpleConfig([{"name": "primary", "api_key": "k", "base_url": "https://example.test"}])
        client = OpenAIClient(config)

        response_data = {"choices": [{"message": {"content": json.dumps({"symbol": "EURUSD", "confidence": 0.9})}}]}

        calls = {"n": 0}

        def _post(url, **kwargs):
            calls["n"] += 1
            return _make_requests_response(response_data)

        with patch("requests.post", side_effect=_post):
            first = client.parse_signal("test payload")
            self.assertEqual(first.get("symbol"), "EURUSD")
            self.assertEqual(calls["n"], 1)

            second = client.parse_signal("test payload")
            self.assertEqual(second.get("symbol"), "EURUSD")
            # no extra network call due to cache
            self.assertEqual(calls["n"], 1)

    def test_token_bucket_limits(self):
        config = SimpleConfig([{"name": "primary", "api_key": "k", "base_url": "https://example.test"}], max_rpm=1)
        client = OpenAIClient(config)
        # first token available
        self.assertTrue(client._acquire_token())
        # second immediate token not available
        self.assertFalse(client._acquire_token())

    def test_circuit_breaker_trips_provider_on_429(self):
        providers = [
            {"name": "p1", "api_key": "k1", "base_url": "https://p1.example"},
            {"name": "p2", "api_key": "k2", "base_url": "https://p2.example"},
        ]
        config = SimpleConfig(providers)
        client = OpenAIClient(config)

        success_data = {"choices": [{"message": {"content": json.dumps({"symbol": "USDJPY", "confidence": 0.8})}}]}

        _post_calls = {"n": 0}

        def _post(url, **kwargs):
            n = _post_calls["n"]
            _post_calls["n"] += 1
            if n == 0:
                raise _make_requests_http_error(429, '{"error":"rate limit"}')
            return _make_requests_response(success_data)

        with patch("requests.post", side_effect=_post):
            res = client.parse_signal("circuit test")
            self.assertEqual(res.get("symbol"), "USDJPY")
            # provider 1 should have recorded a failure and been tripped
            p1 = client.providers[0]
            self.assertGreater(p1.get("failure_count", 0), 0)
            self.assertGreater(p1.get("trip_until", 0), time.time() - 1)

    def test_cloudflare_adapter_flattens_text_only_message_content(self):
        config = SimpleConfig(
            [{"name": "cloudflare", "api_key": "k", "base_url": "https://example.test", "model": "cf-model"}]
        )
        client = OpenAIClient(config)

        response_data = {"choices": [{"message": {"content": json.dumps({"intent": "INFORMATIONAL", "confidence": 0.9})}}]}
        seen_payload: dict = {}

        def _post(url, **kwargs):
            seen_payload.update(kwargs.get("json", {}))
            return _make_requests_response(response_data)

        with patch("requests.post", side_effect=_post):
            result = client.classify_intent("BUY GOLD")

        self.assertEqual(result.get("intent"), "INFORMATIONAL")
        self.assertIsInstance(seen_payload["messages"][1]["content"], str)
        self.assertEqual(seen_payload["messages"][1]["content"], "BUY GOLD")


if __name__ == "__main__":
    unittest.main()
